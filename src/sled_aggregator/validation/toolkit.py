"""Safe, offline-first HAR evidence tooling for registered public sources."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SANITIZER_VERSION = "1.0"
REDACTED = "[REDACTED]"
SENSITIVE_NAMES = re.compile(
    r"authorization|cookie|api[-_]?key|token|secret|password|passwd|session|csrf|xsrf|"
    r"oauth|saml|code|_afrloop|_adf\.ctrl-state|oracle.*(?:state|session)|traceparent|x-request-id",
    re.I,
)
STATIC_MIMES = ("image/", "font/", "text/css", "javascript")
CAPABILITIES = (
    "source_identity",
    "landing_page",
    "discovery",
    "pagination",
    "filtering",
    "details",
    "attachments",
    "document_retrieval",
    "amendments",
    "awards",
    "normalization",
    "document_pipeline_handoff",
)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_label(value: str) -> str:
    if (
        not value
        or value.strip() != value
        or Path(value).is_absolute()
        or ".." in value
        or re.search(r"[\\/\x00-\x1f:]", value)
        or value.upper().split(".")[0]
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{x}" for x in range(1, 10)),
            *(f"LPT{x}" for x in range(1, 10)),
        }
    ):
        raise ValueError("capture label is unsafe")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise ValueError("capture label must already be a safe slug")
    return value.lower()


def validate_public_url(url: str, allowed_hosts: set[str]) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ValueError("only credential-free public HTTP(S) URLs are supported")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host not in allowed_hosts:
        raise ValueError("URL host is not registered for this capture")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("private or special-purpose addresses are forbidden")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _source_hosts(source: dict) -> set[str]:
    hosts = set()
    for key in (
        "official_url",
        "official_landing_page",
        "public_bid_board_url",
        "public_search_url",
    ):
        if source.get(key) and urlsplit(source[key]).hostname:
            hosts.add(urlsplit(source[key]).hostname.rstrip(".").lower())
    return hosts


def load_source(registry: Path, source_id: str) -> dict:
    data = json.loads(registry.read_text(encoding="utf-8"))
    sources = data["sources"] if isinstance(data, dict) else data
    try:
        return next(item for item in sources if item["source_id"] == source_id)
    except StopIteration as exc:
        raise ValueError(f"unknown registered source ID: {source_id}") from exc


def validate_workspace(path: Path, repo_root: Path) -> Path:
    resolved, root = path.resolve(), repo_root.resolve()
    forbidden = [root / "tests/fixtures", root / "data/coverage", root / "docs", root / "reports"]
    if resolved == root or any(resolved == item or item in resolved.parents for item in forbidden):
        raise ValueError("validation workspace cannot be a tracked or repository-root path")
    if (
        root in resolved.parents
        and resolved.name != ".sled-validation"
        and ".sled-validation" not in resolved.parts
    ):
        raise ValueError("repository-local captures must use .sled-validation")
    return resolved


@dataclass(frozen=True)
class CaptureConfig:
    source_id: str
    jurisdiction_id: str
    starting_url: str
    allowed_hosts: tuple[str, ...]
    label: str
    output_directory: Path = Path(".sled-validation")
    mode: str = "manual"
    max_duration: int = 900
    max_requests: int = 200
    max_redirects: int = 10
    max_response_body_bytes: int = 256_000
    max_total_capture_bytes: int = 25_000_000
    per_host_delay: float = 0.5
    navigation_timeout: int = 30
    retain_response_bodies: bool = False
    mime_allowlist: tuple[str, ...] = ("application/json", "text/html", "text/plain")
    path_allowlist: tuple[str, ...] = ()
    path_denylist: tuple[str, ...] = ("/login", "/signin", "/account", "/submit")
    user_agent: str = "SLED-Aggregator-HAR-Validator/1.0 (+anonymous-read-only)"
    public_read_only: bool = True

    @classmethod
    def from_registry(cls, source: dict, label: str, output: Path = Path(".sled-validation"), **kw):
        hosts = _source_hosts(source)
        url = (
            source.get("public_search_url")
            or source.get("public_bid_board_url")
            or source.get("official_landing_page")
            or source["official_url"]
        )
        return cls(
            source["source_id"],
            source["jurisdiction_id"],
            url,
            tuple(sorted(hosts)),
            label,
            output,
            **kw,
        )

    def validate(self, repo_root: Path) -> CaptureConfig:
        validate_label(self.label)
        hosts = {host.lower() for host in self.allowed_hosts}
        validate_public_url(self.starting_url, hosts)
        validate_workspace(self.output_directory, repo_root)
        if not self.public_read_only or self.mode not in {"manual", "import", "batch"}:
            raise ValueError("capture must be declared public/read-only in a supported mode")
        if (
            min(
                self.max_duration,
                self.max_requests,
                self.max_redirects,
                self.max_response_body_bytes,
                self.max_total_capture_bytes,
                self.navigation_timeout,
            )
            <= 0
        ):
            raise ValueError("capture budgets must be positive")
        if self.per_host_delay < 0:
            raise ValueError("per-host delay cannot be negative")
        return self


@dataclass
class AuditAction:
    entry: int
    location: str
    action: str
    fingerprint: str


def _fingerprint(value: object) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


def _redact_url(url: str, audit: list[AuditAction], index: int) -> str:
    parts = urlsplit(url)
    safe = []
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if SENSITIVE_NAMES.search(name) or "@" in value:
            audit.append(
                AuditAction(index, f"request.query.{name}", "redacted", _fingerprint(value))
            )
            value = REDACTED
        safe.append((name, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe), ""))


def _sanitize_headers(
    headers: list[dict], audit: list[AuditAction], index: int, side: str
) -> list[dict]:
    result = []
    for header in headers or []:
        if (
            SENSITIVE_NAMES.search(header.get("name", ""))
            or header.get("name", "").lower() == "www-authenticate"
        ):
            audit.append(
                AuditAction(
                    index,
                    f"{side}.headers.{header.get('name', '')}",
                    "removed",
                    _fingerprint(header.get("value", "")),
                )
            )
        else:
            result.append({"name": header.get("name", ""), "value": header.get("value", "")})
    return result


def _sanitize_entry(entry: dict, index: int, audit: list[AuditAction], max_body: int) -> dict:
    request, response = entry.get("request", {}), entry.get("response", {})
    request["url"] = _redact_url(request.get("url", ""), audit, index)
    request["headers"] = _sanitize_headers(request.get("headers", []), audit, index, "request")
    response["headers"] = _sanitize_headers(response.get("headers", []), audit, index, "response")
    for side in (request, response):
        if side.get("cookies"):
            audit.append(
                AuditAction(index, "cookies", "removed", _fingerprint(len(side["cookies"])))
            )
        side.pop("cookies", None)
    post = request.get("postData")
    if post:
        for param in post.get("params", []):
            if SENSITIVE_NAMES.search(param.get("name", "")) or "@" in param.get("value", ""):
                audit.append(
                    AuditAction(
                        index,
                        f"request.form.{param.get('name')}",
                        "redacted",
                        _fingerprint(param.get("value")),
                    )
                )
                param["value"] = REDACTED
        if "text" in post and (
            len(post["text"].encode()) > max_body
            or re.search(r"login|password|saml|oauth", post["text"], re.I)
        ):
            audit.append(AuditAction(index, "request.body", "removed", _fingerprint(post["text"])))
            post["text"] = "[BODY REMOVED]"
    content = response.get("content", {})
    mime = content.get("mimeType", "").lower()
    text = content.get("text")
    binary = content.get("encoding") == "base64" or not any(
        x in mime for x in ("json", "text", "xml", "html")
    )
    if text is not None and (
        binary
        or len(text.encode()) > max_body
        or re.search(r"login|password|account information|saml", text, re.I)
    ):
        audit.append(
            AuditAction(
                index,
                "response.body",
                "removed_binary" if binary else "removed",
                _fingerprint(text),
            )
        )
        content.pop("text", None)
        content.pop("encoding", None)
        content["_sledBodyRemoved"] = True
    for key in ("timings", "serverIPAddress", "connection", "_securityDetails"):
        entry.pop(key, None)
    return entry


def sanitize_har(
    input_path: Path,
    output_path: Path,
    *,
    source_id: str,
    max_body: int = 256_000,
    captured_at: str | None = None,
    sanitized_at: str | None = None,
) -> dict:
    """Sanitize without overwriting input. Output is canonical and deterministic for fixed timestamps."""
    if input_path.resolve() == output_path.resolve():
        raise ValueError("sanitized output must not overwrite raw input")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    audit: list[AuditAction] = []
    entries = [
        _sanitize_entry(entry, i, audit, max_body)
        for i, entry in enumerate(data.get("log", {}).get("entries", []))
    ]
    metadata = {
        "sanitizer_version": SANITIZER_VERSION,
        "source_id": source_id,
        "capture_timestamp": captured_at
        or data.get("log", {}).get("pages", [{}])[0].get("startedDateTime"),
        "sanitization_timestamp": sanitized_at or utc_now(),
        "input_hash": sha256(input_path),
    }
    clean = {
        "log": {
            "version": data.get("log", {}).get("version", "1.2"),
            "creator": {"name": "sled-aggregator", "version": SANITIZER_VERSION},
            "entries": entries,
        },
        "_sledValidation": metadata,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(clean, indent=2, sort_keys=True) + "\n"
    output_path.write_text(payload, encoding="utf-8")
    metadata["output_hash"] = sha256(output_path)
    report = {
        "metadata": metadata,
        "actions": [asdict(x) for x in audit],
        "action_count": len(audit),
    }
    output_path.with_suffix(output_path.suffix + ".audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    return report


@dataclass
class Finding:
    finding_type: str
    location: str
    severity: str
    redacted_fingerprint: str
    review_status: str = "unreviewed"


PATTERNS = {
    "bearer_token": re.compile(r"bearer\s+[a-z0-9._~+/-]{12,}", re.I),
    "jwt": re.compile(r"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\b"),
    "basic_auth": re.compile(r"basic\s+[a-zA-Z0-9+/=]{8,}", re.I),
    "email": re.compile(r"\b[^\s@]+@[^\s@]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)"),
    "private_ip": re.compile(
        r"\b(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)\d{1,3}\.\d{1,3}\b"
    ),
}


def scan_artifact(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = []
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            severity = "high" if kind in {"bearer_token", "jwt", "basic_auth"} else "medium"
            findings.append(
                Finding(kind, f"byte:{match.start()}", severity, _fingerprint(match.group()))
            )
    for match in re.finditer(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{32,}(?![A-Za-z0-9])", text):
        value = match.group()
        counts = {char: value.count(char) for char in set(value)}
        entropy = -sum((n / len(value)) * math.log2(n / len(value)) for n in counts.values())
        if entropy >= 4.2 and value not in {REDACTED}:
            findings.append(
                Finding("high_entropy", f"byte:{match.start()}", "high", _fingerprint(value))
            )
    return findings


def assert_safe(findings: list[Finding]) -> None:
    if any(item.severity == "high" and item.review_status != "resolved" for item in findings):
        raise ValueError("high-severity sensitive-data findings remain; artifact is not eligible")


def analyze_har(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    contracts, access = [], "not_observed"
    for i, entry in enumerate(data["log"].get("entries", [])):
        req, res = entry.get("request", {}), entry.get("response", {})
        url, status = req.get("url", ""), res.get("status", 0)
        mime = res.get("content", {}).get("mimeType", "")
        lower = (url + " " + res.get("content", {}).get("text", "")).lower()
        if status == 429:
            access = "rate_limited"
        elif "captcha" in lower or "verify you are human" in lower:
            access = "captcha_present"
        elif status in {401, 403} and any(x in lower for x in ("proxy", "connect tunnel")):
            access = "proxy_blocked"
        elif status in {401, 403} or any(x in lower for x in ("login", "sign in", "oauth")):
            access = "authentication_required"
        elif status == 0:
            access = "network_blocked"
        elif 200 <= status < 400 and access == "not_observed":
            access = "public_anonymous"
        kind = "navigation"
        if any(mime.startswith(prefix) for prefix in STATIC_MIMES) or re.search(
            r"\.(css|js|png|jpg|gif|woff2?)(?:\?|$)", url, re.I
        ):
            kind = "static_asset"
        elif re.search(r"analytics|google-analytics|doubleclick|telemetry", url, re.I):
            kind = "analytics"
        elif re.search(r"search|solicitation|opportunit|bid", url, re.I):
            kind = "search_data"
        if re.search(r"detail|solicitation/|opportunit(?:y|ies)/", url, re.I):
            kind = "detail"
        if re.search(r"attachment|document/list", url, re.I):
            kind = "attachment"
        if re.search(r"download|\.pdf(?:\?|$)", url, re.I):
            kind = "document"
        if re.search(r"amend|addend", url, re.I):
            kind = "amendment"
        if kind not in {"static_asset", "analytics"}:
            query = [name for name, _ in parse_qsl(urlsplit(url).query)]
            contracts.append(
                {
                    "entry": i,
                    "kind": kind,
                    "url": url,
                    "method": req.get("method"),
                    "status_code": status,
                    "mime_type": mime,
                    "query_parameters": sorted(query),
                    "response_schema_fingerprint": _fingerprint(
                        _json_shape(res.get("content", {}).get("text"))
                    ),
                }
            )
    observed = {
        "landing_page": bool(contracts),
        "discovery": any(x["kind"] == "search_data" for x in contracts),
        "details": any(x["kind"] == "detail" for x in contracts),
        "attachments": any(x["kind"] == "attachment" for x in contracts),
        "document_retrieval": any(x["kind"] == "document" for x in contracts),
        "amendments": any(x["kind"] == "amendment" for x in contracts),
    }
    capabilities = {
        name: (access if observed.get(name) else "not_observed") for name in CAPABILITIES
    }
    capabilities["source_identity"] = "fixture_only"
    return {"access_classification": access, "contracts": contracts, "capabilities": capabilities}


def _json_shape(text: str | None) -> object:
    try:
        value = json.loads(text or "")
        return sorted(value) if isinstance(value, dict) else type(value).__name__
    except (ValueError, TypeError):
        return "non-json"


def evidence_records(
    analysis: dict, metadata: dict, artifact: str, source: dict, capture_id: str
) -> list[dict]:
    contract_by_kind = {row["kind"]: row for row in analysis["contracts"]}
    map_kind = {
        "discovery": "search_data",
        "details": "detail",
        "attachments": "attachment",
        "document_retrieval": "document",
        "amendments": "amendment",
    }
    records = []
    for capability, classification in analysis["capabilities"].items():
        row = contract_by_kind.get(map_kind.get(capability, "navigation"), {})
        seed = f"{source['source_id']}:{capture_id}:{capability}"
        records.append(
            {
                "evidence_id": "har-" + hashlib.sha256(seed.encode()).hexdigest()[:16],
                "source_id": source["source_id"],
                "jurisdiction_id": source["jurisdiction_id"],
                "capture_id": capture_id,
                "capability": capability,
                "classification": classification,
                "evidence_type": "sanitized_har_contract",
                "sanitized_artifact_path": artifact,
                "official_url": source.get("official_url"),
                "observed_host": urlsplit(row.get("url", source.get("official_url", ""))).hostname,
                "request_method": row.get("method"),
                "status_code": row.get("status_code"),
                "mime_type": row.get("mime_type"),
                "verification_timestamp": metadata.get("capture_timestamp"),
                "sanitization_status": "sanitized_pending_review",
                "sanitizer_version": SANITIZER_VERSION,
                "input_hash": metadata.get("input_hash"),
                "output_hash": metadata.get("output_hash"),
                "limitations": ["HAR observation proves only the separately listed capability."],
                "recommended_next_action": "Review findings and approve eligible capabilities.",
                "reviewer_status": "unreviewed",
                "promotion_eligibility": False,
            }
        )
    return records


def approve_evidence(
    records: list[dict],
    reviewer: str,
    capabilities: set[str],
    findings: list[Finding],
    timestamp: str | None = None,
) -> dict:
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    assert_safe(findings)
    approved = []
    for record in records:
        if record["capability"] in capabilities:
            record["reviewer_status"] = "approved"
            record["sanitization_status"] = "reviewed_safe"
            record["promotion_eligibility"] = (
                record["classification"] == "public_anonymous"
                and record["capability"] != "source_identity"
            )
            approved.append(record["capability"])
    return {
        "reviewer": reviewer,
        "timestamp": timestamp or utc_now(),
        "artifact_hashes": sorted({r.get("output_hash") for r in records if r.get("output_hash")}),
        "findings_disposition": "no_unresolved_high_findings",
        "capabilities_approved": sorted(approved),
        "registry_changes_proposed": True,
        "records": records,
    }


def ingest_evidence(
    approval: dict, registry: Path, *, confirm: bool, dry_run: bool = False
) -> dict:
    if not confirm:
        raise ValueError("registry ingestion requires explicit confirmation")
    approved = [
        r
        for r in approval.get("records", [])
        if r.get("reviewer_status") == "approved"
        and r.get("sanitization_status") == "reviewed_safe"
    ]
    if not approved:
        raise ValueError("no reviewed safe evidence is approved")
    data = json.loads(registry.read_text())
    existing = {x.get("evidence_id") for x in data.get("evidence", [])}
    compact = [
        {
            "evidence_id": r["evidence_id"],
            "source_id": r["source_id"],
            "evidence_type": r["evidence_type"],
            "evidence_location": [r["sanitized_artifact_path"]],
            "capabilities": [r["capability"]],
            "verification_date": (r.get("verification_timestamp") or "")[:10],
            "notes": "; ".join(r["limitations"]),
        }
        for r in approved
        if r["evidence_id"] not in existing
    ]
    if not dry_run:
        data.setdefault("evidence", []).extend(compact)
        registry.write_text(json.dumps(data, indent=2) + "\n")
    return {"dry_run": dry_run, "records_added": len(compact), "live_verification_promoted": False}


def extract_fixture(path: Path, output: Path, *, approved: bool, max_entries: int = 3) -> dict:
    if not approved:
        raise ValueError("fixture extraction requires reviewed evidence")
    data = json.loads(path.read_text())
    entries = []
    transforms = []
    for i, entry in enumerate(data["log"].get("entries", [])):
        mime = entry.get("response", {}).get("content", {}).get("mimeType", "")
        if any(mime.startswith(prefix) for prefix in STATIC_MIMES):
            continue
        if entry.get("response", {}).get("content", {}).get("_sledBodyRemoved"):
            continue
        entries.append(entry)
        transforms.append({"entry": i, "action": "selected_minimal_contract_entry"})
        if len(entries) >= max_entries:
            break
    fixture = {
        "schema_version": 1,
        "entries": entries,
        "transformations": transforms,
        "live_verification": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    return fixture


GUIDED_CHECKLIST = (
    "landing-page visit",
    "keyword search",
    "empty/wildcard search",
    "filter change",
    "page-two navigation or infinite scroll",
    "solicitation-detail view",
    "attachment-list view",
    "one bounded public document request",
    "amendment/addendum view",
    "return to results",
)


def capture_manual(config: CaptureConfig, repo_root: Path) -> Path:
    """Launch optional Playwright in a fresh visible context; CI must never call this."""
    config.validate(repo_root)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("manual capture requires the optional 'validation' dependency") from exc
    raw = config.output_directory / "raw" / f"{validate_label(config.label)}.har"
    raw.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            record_har_path=str(raw),
            record_har_content="embed" if config.retain_response_bodies else "omit",
            user_agent=config.user_agent,
        )
        request_count = 0

        def route_handler(route):
            nonlocal request_count
            request_count += 1
            try:
                validate_public_url(route.request.url, set(config.allowed_hosts))
            except ValueError:
                route.abort()
                return
            if request_count > config.max_requests or route.request.method not in {"GET", "HEAD"}:
                route.abort()
                return
            route.continue_()

        context.route("**/*", route_handler)
        page = context.new_page()
        page.goto(config.starting_url, timeout=config.navigation_timeout * 1000)
        print(
            "Anonymous read-only capture started. Complete the guided checklist; press Enter to flush and close."
        )
        print("Do not log in, register, solve CAPTCHA, submit bids, or perform vendor actions.")
        input()
        context.close()
        browser.close()
    return raw
