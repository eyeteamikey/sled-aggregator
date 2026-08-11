"""Safe, offline-first HAR evidence tooling for registered public sources."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import shutil
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Queue
from typing import TypedDict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SANITIZER_VERSION = "1.0"
REDACTED = "[REDACTED]"
SENSITIVE_NAMES = re.compile(
    r"authorization|cookie|api[-_]?key|token|secret|password|passwd|session|csrf|xsrf|"
    r"oauth|saml|code|viewstate|javax\.faces|jsessionid|_afrloop|_adf\.ctrl-state|"
    r"oracle.*(?:state|session)|traceparent|x-request-id|username|supplier|phone|email",
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

TELEMETRY_HOST_PATTERNS = ("google-analytics", "googletagmanager", "hotjar", "doubleclick")
CAPTURE_OUTCOMES = (
    "capture_succeeded",
    "capture_partially_succeeded",
    "initialization_failed",
    "operator_aborted",
    "capture_timed_out",
    "browser_closed",
    "safety_policy_blocked",
    "browser_incompatible",
    "browser_failed",
    "diagnostic_summary_failed",
)
DIAGNOSTIC_SCHEMA_VERSION = 1
SPINNER_REASONS = (
    "blocked_dependency",
    "javascript_exception",
    "request_failed",
    "expected_request_not_observed",
    "response_not_received",
    "response_received_spinner_remained",
    "browser_channel_incompatibility",
    "unknown_after_diagnostics",
)
SUPPORTED_BROWSERS = ("chromium", "chrome", "msedge")
REQUEST_POLICY_MODES = ("observe", "first-party", "full")
BIDBUY_SEARCH_PATH = "/bso/view/search/external/advancedSearchBid.xhtml"
BIDBUY_SEARCH_FORM_SELECTOR = "#bidSearchResultsForm"
BIDBUY_RESULT_SELECTOR = '.ui-datatable:visible, [id*="bidSearchResults"]:visible'
BIDBUY_POPULATED_ROW_SELECTOR = (
    '.ui-datatable:visible tbody tr:visible:not(.ui-datatable-empty-message):not(.ui-skeleton):has(td:not(:empty)), '
    '[id*="bidSearchResults"]:visible tbody tr:visible:not(.ui-datatable-empty-message):not(.ui-skeleton):has(td:not(:empty))'
)
BIDBUY_EMPTY_RESULTS = re.compile(
    r"no\s+(records|results|bids)\s+found", re.IGNORECASE
)
BIDBUY_SPINNER_SELECTOR = ".ui-blockui:visible, .ui-widget-overlay:visible"
MUTATION_PATTERN = re.compile(
    r"login|sign[-_]?in|register|create.?account|password|upload|bid|quote|proposal|"
    r"supplier|profile|cart|response.?line|save|update|delete|publish|award|checkout|"
    r"payment|acknowledge|accept.?terms|submit",
    re.I,
)


@dataclass(frozen=True)
class ValidationRequestRule:
    methods: tuple[str, ...]
    hosts: tuple[str, ...]
    path_pattern: str
    purpose: str
    allowed_content_types: tuple[str, ...] = (
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "text/plain",
    )
    prohibited_field_name_patterns: tuple[str, ...] = (
        "password",
        "username",
        "upload",
        "file",
        "bid",
        "quote",
        "proposal",
        "payment",
        "save",
        "update",
        "delete",
        "submit",
        "acknowledge",
        "acceptTerms",
    )
    maximum_request_body_size: int = 256_000
    requires_anonymous: bool = True
    read_only: bool = True


@dataclass(frozen=True)
class RequestDecision:
    allowed: bool
    rule: str
    classification: str
    reason: str
    essential: bool


class DiagnosticEvent(TypedDict, total=False):
    """Normalized, sanitized browser diagnostic; only type and timestamp are required."""

    diagnostic_schema_version: int
    event_type: str
    timestamp: str
    source_id: str
    method: str
    request_method: str
    host: str
    path: str
    resource_type: str
    classification: str
    reason: str
    status_code: int
    first_party: bool
    blocked: bool
    essential: bool
    sanitized_message: str


DIAGNOSTIC_EVENT_ALIASES = {
    "request": "request_observed",
    "response": "response_received",
    "requestfailed": "request_failed",
    "policy": "request_blocked",
    "console": "console_error",
    "pageerror": "page_error",
}


def normalize_diagnostic(value: object) -> DiagnosticEvent:
    """Normalize heterogeneous browser events without inventing optional request fields."""
    if not isinstance(value, dict):
        value = {"sanitized_message": sanitize_diagnostic_message(value)}
    event_type = value.get("event_type") or value.get("event")
    if not isinstance(event_type, str) or not event_type.strip():
        return {
            "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "event_type": "diagnostic_schema_error",
            "timestamp": str(value.get("timestamp") or utc_now()),
            "classification": "malformed_diagnostic",
            "sanitized_message": sanitize_diagnostic_message(
                value.get("sanitized_message") or value.get("message") or "missing event_type"
            ),
        }
    event_type = DIAGNOSTIC_EVENT_ALIASES.get(event_type, event_type)
    normalized: DiagnosticEvent = {
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "event_type": event_type,
        "timestamp": str(value.get("timestamp") or utc_now()),
    }
    aliases = {
        "status": "status_code",
        "likely_essential": "essential",
        "message": "sanitized_message",
    }
    allowed = set(DiagnosticEvent.__annotations__) - {
        "diagnostic_schema_version",
        "event_type",
        "timestamp",
    }
    for key, raw in value.items():
        destination = aliases.get(key, key)
        if destination not in allowed or raw is None:
            continue
        if destination in {"sanitized_message", "reason"}:
            normalized[destination] = sanitize_diagnostic_message(raw)
        else:
            normalized[destination] = raw
    if event_type == "request_blocked":
        normalized["blocked"] = True
    if value.get("csp_violation"):
        normalized["classification"] = "csp_violation"
    return normalized


def normalize_diagnostics(values: object) -> list[DiagnosticEvent]:
    if not isinstance(values, (list, tuple)):
        return [normalize_diagnostic(values)]
    return [normalize_diagnostic(value) for value in values]


def classify_request(
    config: CaptureConfig,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    field_names: tuple[str, ...] = (),
    body_size: int = 0,
    resource_type: str = "",
) -> RequestDecision:
    """Classify from contract shape only; request values are never retained or logged."""
    method, headers = method.upper(), {k.lower(): v for k, v in (headers or {}).items()}
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), parts.path or "/"
    first_party = host in config.allowed_hosts
    essential = first_party and resource_type in {"document", "xhr", "fetch", "navigation"}
    if any(p in host for p in TELEMETRY_HOST_PATTERNS):
        return RequestDecision(
            False,
            "telemetry-default-deny",
            "nonessential_third_party",
            "analytics/telemetry omitted",
            False,
        )
    if method in {"PUT", "PATCH", "DELETE", "CONNECT", "TRACE"}:
        return RequestDecision(
            False, "unsafe-method-deny", "mutation", f"{method} is always blocked", essential
        )
    if not first_party:
        return RequestDecision(
            False, "host-allowlist", "third_party", "host is not allowlisted", False
        )
    if method in {"GET", "HEAD", "OPTIONS"}:
        return RequestDecision(
            True, "safe-resource-method", "safe_resource", "safe resource method", essential
        )
    if method != "POST":
        return RequestDecision(
            False, "method-default-deny", "mutation", "method is not permitted", essential
        )
    content_type = headers.get("content-type", "").split(";", 1)[0].lower()
    if "authorization" in headers or "proxy-authorization" in headers:
        return RequestDecision(
            False, "credentials-deny", "authentication", "credential header present", essential
        )
    if MUTATION_PATTERN.search(path):
        # BidBuy's reviewed detail path contains 'bid' and is allowed only through an exact rule.
        matching = [
            r
            for r in config.request_rules
            if host in r.hosts and re.fullmatch(r.path_pattern, path)
        ]
        if not matching:
            return RequestDecision(
                False, "mutation-path-deny", "mutation", "prohibited action in path", essential
            )
    for rule in config.request_rules:
        if (
            method not in rule.methods
            or host not in rule.hosts
            or not re.fullmatch(rule.path_pattern, path)
        ):
            continue
        prohibited = re.compile("|".join(rule.prohibited_field_name_patterns), re.I)
        if any(prohibited.search(name) for name in field_names):
            return RequestDecision(
                False, rule.purpose, "mutation", "prohibited form-field name", essential
            )
        if body_size > rule.maximum_request_body_size:
            return RequestDecision(
                False, rule.purpose, "oversize", "request body exceeds rule limit", essential
            )
        if content_type and content_type not in rule.allowed_content_types:
            return RequestDecision(
                False, rule.purpose, "unsupported_content", "content type is not allowed", essential
            )
        return RequestDecision(
            True,
            rule.purpose,
            "conditional_read_only_post",
            "reviewed source-specific POST contract",
            essential,
        )
    return RequestDecision(
        False,
        "post-default-deny",
        "unclassified_post",
        "POST destination is not registered",
        essential,
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
        raise ValueError(
            "Repository-local captures must use .sled-validation.\nRetry:\n"
            "python -m sled_aggregator.validation capture --source <source> --label <label> "
            "--workspace .\\.sled-validation"
        )
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
    action_timeout: int = 30
    browser: str = "chromium"
    request_policy_mode: str = "full"
    profile_directory: Path | None = None
    retain_response_bodies: bool = False
    mime_allowlist: tuple[str, ...] = ("application/json", "text/html", "text/plain")
    path_allowlist: tuple[str, ...] = ()
    path_denylist: tuple[str, ...] = ("/login", "/signin", "/account", "/submit")
    user_agent: str = "SLED-Aggregator-HAR-Validator/1.0 (+anonymous-read-only)"
    public_read_only: bool = True
    request_rules: tuple[ValidationRequestRule, ...] = ()

    @classmethod
    def from_registry(cls, source: dict, label: str, output: Path = Path(".sled-validation"), **kw):
        hosts = _source_hosts(source)
        url = (
            source.get("public_search_url")
            or source.get("public_bid_board_url")
            or source.get("official_landing_page")
            or source["official_url"]
        )
        rules = tuple(
            ValidationRequestRule(**rule)
            for rule in source.get("validation_request_policy", {}).get("browser_capture_rules", [])
        )
        return cls(
            source["source_id"],
            source["jurisdiction_id"],
            url,
            tuple(sorted(hosts)),
            label,
            output,
            request_rules=rules,
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
        if self.browser not in SUPPORTED_BROWSERS:
            raise ValueError(
                "unsupported browser channel; use one of: chromium, chrome, msedge. "
                "Install the selected channel or retry with --browser chromium"
            )
        if self.request_policy_mode not in REQUEST_POLICY_MODES:
            raise ValueError("request policy must be one of: observe, first-party, full")
        if self.profile_directory:
            profile = self.profile_directory.resolve()
            workspace = self.output_directory.resolve()
            if workspace not in profile.parents:
                raise ValueError("persistent browser profiles must be inside .sled-validation")
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


def raw_risk_inventory(path: Path) -> dict:
    """Return safe category counts; never return matching values."""
    checks = {
        "cookies_present": r'"(?:Cookie|Set-Cookie|cookies)"',
        "authorization_headers_present": r'"(?:Authorization|Proxy-Authorization)"',
        "view_state_fields_present": r"javax\.faces\.ViewState|ViewState",
        "email_candidates": PATTERNS["email"],
        "tracking_identifiers_present": r"_ga|_gid|hotjar|google-analytics|traceparent",
    }
    counts = dict.fromkeys(checks, 0)
    overlap = ""
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), ""):
            text = overlap + chunk
            for name, pattern in checks.items():
                compiled = re.compile(pattern, re.I) if isinstance(pattern, str) else pattern
                counts[name] += sum(match.end() > len(overlap) for match in compiled.finditer(text))
            overlap = text[-256:]
    return counts


def import_har(input_path: Path, workspace: Path, source_id: str, repo_root: Path) -> dict:
    """Copy an operator HAR into protected raw storage and immediately sanitize/scan it."""
    validate_workspace(workspace, repo_root)
    if not input_path.is_file():
        raise ValueError("manual HAR input does not exist")
    capture_id = f"{validate_label(source_id)}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    raw = workspace / "raw" / f"{capture_id}.har"
    sanitized = workspace / "sanitized" / f"{capture_id}.har"
    if raw.exists():
        raise ValueError("raw import destination already exists; choose a new capture")
    raw.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, raw)
    inventory = raw_risk_inventory(raw)
    report = sanitize_har(raw, sanitized, source_id=source_id)
    findings = scan_artifact(sanitized)
    manifest = {
        "capture_id": capture_id,
        "source_id": source_id,
        "capture_mode": "manual-browser",
        "raw_path": str(raw),
        "sanitized_path": str(sanitized),
        "raw_risk_inventory": inventory,
        "sanitized_hash": report["metadata"]["output_hash"],
        "approval_eligible": not any(x.severity == "high" for x in findings),
        "sensitive_findings": {
            "high": sum(x.severity == "high" for x in findings),
            "medium": sum(x.severity == "medium" for x in findings),
        },
        "next_commands": [
            f"python -m sled_aggregator.validation scan {sanitized} --output "
            f"{workspace / 'reports' / (capture_id + '-findings.json')}",
            f"python -m sled_aggregator.validation analyze {sanitized} --output "
            f"{workspace / 'reports' / (capture_id + '-analysis.json')}",
            f"python -m sled_aggregator.validation report {sanitized} --analysis "
            f"{workspace / 'reports' / (capture_id + '-analysis.json')} --source {source_id} "
            f"--capture-id {capture_id} --output {workspace / 'evidence' / (capture_id + '.json')}",
            f"python -m sled_aggregator.validation approve "
            f"{workspace / 'evidence' / (capture_id + '.json')} "
            f"{workspace / 'reports' / (capture_id + '-findings.json')} --reviewer <reviewer> "
            f"--capability discovery --output "
            f"{workspace / 'evidence' / (capture_id + '-approved.json')}",
            f"python -m sled_aggregator.validation ingest "
            f"{workspace / 'evidence' / (capture_id + '-approved.json')} --dry-run --confirm",
        ],
    }
    manifest_path = workspace / "reports" / f"{capture_id}-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


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


def sanitize_diagnostic_message(message: object, limit: int = 500) -> str:
    """Return useful browser text without URLs, values, or secret-bearing assignments."""
    text = str(message).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"https?://[^\s'\"<>]+", lambda m: _safe_request_url(m.group()), text)
    text = re.sub(
        r"(?i)\b(cookie|authorization|token|secret|session|csrf|viewstate|javax\.faces[^= ]*)"
        r"\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    text = PATTERNS["email"].sub(REDACTED, text)
    return text[:limit]


def _safe_request_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))


def _request_diagnostic(request, **extra) -> dict:
    parts = urlsplit(request.url)
    redirected_from = getattr(request, "redirected_from", None)
    return {
        "method": request.method,
        "host": parts.hostname,
        "path": parts.path or "/",
        "resource_type": request.resource_type,
        "redirected_from": (
            urlsplit(redirected_from.url).path if redirected_from is not None else None
        ),
        **extra,
    }


def evaluate_bidbuy_startup(
    diagnostics: list[dict],
    *,
    overlay_visible: bool,
    results_state_visible: bool,
    diagnostic_probe_failed: bool = False,
    result_state: str | None = None,
) -> dict:
    """Evaluate BidBuy's startup contract from sanitized browser observations."""
    diagnostics = normalize_diagnostics(diagnostics)
    expected = [
        row
        for row in diagnostics
        if row.get("event_type") == "request_observed"
        and row.get("method") == "POST"
        and row.get("path") == BIDBUY_SEARCH_PATH
    ]
    responses = [
        row
        for row in diagnostics
        if row.get("event_type") == "response_received"
        and row.get("request_method") == "POST"
        and row.get("path") == BIDBUY_SEARCH_PATH
        and 200 <= row.get("status_code", 0) < 400
    ]
    html_ok = any(
        row.get("event_type") == "response_received"
        and row.get("resource_type") == "document"
        and row.get("first_party")
        and 200 <= row.get("status_code", 0) < 400
        for row in diagnostics
    )
    jsf_scripts_ok = any(
        row.get("event_type") == "response_received"
        and row.get("resource_type") == "script"
        and row.get("first_party")
        and ("javax.faces.resource" in row.get("path", "") or "primefaces" in row.get("path", "").lower())
        and 200 <= row.get("status_code", 0) < 400
        for row in diagnostics
    )
    blocked_essential = any(
        row.get("event_type") == "request_blocked" and row.get("essential")
        for row in diagnostics
    )
    script_error = any(
        row.get("event_type") == "page_error"
        or (
            row.get("event_type") == "console_error"
            and row.get("classification") == "csp_violation"
        )
        for row in diagnostics
    )
    failed_first_party = any(
        row.get("event_type") == "request_failed" and row.get("first_party")
        for row in diagnostics
    )
    success = bool(
        html_ok
        and jsf_scripts_ok
        and expected
        and responses
        and not overlay_visible
        and results_state_visible
        and not diagnostic_probe_failed
    )
    reason = None
    message = None
    if not success:
        if diagnostic_probe_failed:
            reason = "unknown_after_diagnostics"
            message = "BidBuy result-state inspection failed; capture classification is unknown."
        elif blocked_essential:
            reason = "blocked_dependency"
        elif script_error:
            reason = "javascript_exception"
        elif failed_first_party:
            reason = "request_failed"
        elif not expected:
            reason = "expected_request_not_observed"
            message = (
                "BidBuy initialization failed: the expected anonymous JSF results request "
                "was not observed."
            )
        elif not responses:
            reason = "response_not_received"
        elif overlay_visible:
            reason = "response_received_spinner_remained"
            message = (
                "BidBuy initialization failed: the results loading overlay remained visible "
                "after the configured timeout."
            )
        else:
            reason = "unknown_after_diagnostics"
    outcome = "capture_succeeded" if success else "initialization_failed"
    if diagnostic_probe_failed:
        outcome = "capture_partially_succeeded"
    if reason == "blocked_dependency":
        outcome = "safety_policy_blocked"
    return {
        "capture_outcome": outcome,
        "startup_succeeded": success,
        "expected_initial_jsf_post_observed": bool(expected),
        "results_response_received": bool(responses),
        "expected_first_party_html_received": html_ok,
        "required_jsf_primefaces_script_received": jsf_scripts_ok,
        "loading_overlay_visible": overlay_visible,
        "results_or_empty_state_visible": results_state_visible,
        "result_state": result_state or ("observed" if results_state_visible else "unknown"),
        "diagnostic_probe_failed": diagnostic_probe_failed,
        "suspected_spinner_reason": reason,
        "message": message,
    }


def inspect_bidbuy_result_state(page) -> dict:
    """Inspect independent BidBuy UI states without allowing diagnostics to abort capture."""
    state = {
        "overlay_visible": False,
        "search_form_present": False,
        "results_container_present": False,
        "results_found": False,
        "empty_results_found": False,
        "result_state": "unknown",
        "diagnostic_probe_failed": False,
        "diagnostics": [],
    }

    def failure(probe: str, error: object) -> None:
        state["diagnostic_probe_failed"] = True
        state["diagnostics"].append(
            normalize_diagnostic(
                {
                    "event_type": "result_state_probe_failed",
                    "classification": probe,
                    "sanitized_message": sanitize_diagnostic_message(error),
                }
            )
        )

    try:
        if page.is_closed():
            raise RuntimeError("page is closed")
        # Accessing the owning context detects a context closed between navigation and probes.
        _ = page.context.pages
    except Exception as exc:
        failure("page_state", exc)
        state["result_state"] = "probe_failed"
        return state

    probes = (
        ("spinner", lambda: page.locator(BIDBUY_SPINNER_SELECTOR).count() > 0),
        ("search_form", lambda: page.locator(BIDBUY_SEARCH_FORM_SELECTOR).count() > 0),
        ("results_container", lambda: page.locator(BIDBUY_RESULT_SELECTOR).count() > 0),
        ("results", lambda: page.locator(BIDBUY_POPULATED_ROW_SELECTOR).count() > 0),
        ("empty_results", lambda: page.get_by_text(BIDBUY_EMPTY_RESULTS).count() > 0),
    )
    for name, probe in probes:
        try:
            value = probe()
        except Exception as exc:
            failure(name, exc)
            continue
        if name == "spinner":
            state["overlay_visible"] = value
        elif name == "search_form":
            state["search_form_present"] = value
        elif name == "results_container":
            state["results_container_present"] = value
        elif name == "results":
            state["results_found"] = value
        else:
            state["empty_results_found"] = value

    if state["diagnostic_probe_failed"]:
        state["result_state"] = "probe_failed"
    else:
        if state["overlay_visible"]:
            state["result_state"] = "spinner_visible"
        elif state["results_found"]:
            state["result_state"] = "populated_results_observed"
        elif state["empty_results_found"]:
            state["result_state"] = "explicit_empty_results_observed"
        elif state["results_container_present"]:
            state["result_state"] = "results_container_empty"
        elif state["search_form_present"]:
            state["result_state"] = "search_form_only"
    return state


def run_operator_phase(page, max_duration: int, *, input_stream=None, output=print) -> str:
    """Wait for an explicit operator command while independently enforcing the deadline."""
    commands: Queue[str] = Queue()
    stream = input_stream or sys.stdin

    def read_commands() -> None:
        while True:
            line = stream.readline()
            if line == "":
                commands.put("EOF")
                return
            commands.put(line.strip().upper())

    threading.Thread(target=read_commands, daemon=True).start()
    deadline = time.monotonic() + max_duration
    while True:
        if page.is_closed():
            return "browser_closed"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "capture_timed_out"
        try:
            command = commands.get(timeout=min(0.1, remaining))
        except Empty:
            continue
        if command == "FINISH":
            return "finished"
        if command in {"ABORT", "EOF"}:
            return "operator_aborted"
        if command == "STATUS":
            state = inspect_bidbuy_result_state(page)
            output(json.dumps({"result_state": state["result_state"]}, sort_keys=True))
        elif command:
            output("Unknown command. Use STATUS, FINISH, or ABORT.")


def build_capture_summary(
    config: CaptureConfig,
    diagnostics: object,
    counts: dict,
    startup: dict,
    browser_info: dict,
) -> tuple[list[DiagnosticEvent], dict]:
    """Build request counters only from schema-valid blocked-request diagnostics."""
    normalized = normalize_diagnostics(diagnostics)
    blocked = [row for row in normalized if row.get("event_type") == "request_blocked"]
    summary = {
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "requests_allowed_by_method": counts.get("allowed", {}),
        "requests_blocked_by_method": counts.get("blocked", {}),
        "blocked_first_party_requests": sum(
            1 for row in blocked if row.get("host") in config.allowed_hosts
        ),
        "blocked_third_party_requests": sum(
            1
            for row in blocked
            if row.get("host") and row.get("host") not in config.allowed_hosts
        ),
        "essential_first_party_request_blocked": any(
            row.get("host") in config.allowed_hosts and bool(row.get("essential"))
            for row in blocked
        ),
        "diagnostic_schema_errors": sum(
            row.get("event_type") == "diagnostic_schema_error" for row in normalized
        ),
        **startup,
        "browser": browser_info,
    }
    summary.setdefault("capture_outcome", "capture_partially_succeeded")
    summary.setdefault("startup_succeeded", False)
    return normalized, summary


def write_capture_reports(
    *,
    config: CaptureConfig,
    raw: Path,
    diagnostics: object,
    counts: dict,
    startup: dict,
    browser_info: dict,
    summary_builder=build_capture_summary,
) -> dict:
    """Write normal or fallback reporting after HAR finalization; never raise for aggregation."""
    label = validate_label(config.label)
    report = config.output_directory / "reports" / f"{label}-capture.json"
    summary_path = config.output_directory / "reports" / f"{label}-summary.json"
    manifest = config.output_directory / "reports" / f"{label}-capture-manifest.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    reporting_failed = False
    try:
        normalized, summary = summary_builder(
            config, diagnostics, counts, startup, browser_info
        )
    except Exception as exc:
        reporting_failed = True
        normalized = normalize_diagnostics(diagnostics)
        normalized.append(
            normalize_diagnostic(
                {
                    "event_type": "diagnostic_summary_failed",
                    "classification": "reporting_failure",
                    "sanitized_message": exc,
                }
            )
        )
        summary = {
            "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "capture_outcome": "diagnostic_summary_failed",
            "startup_succeeded": False,
            "diagnostic_schema_errors": sum(
                row.get("event_type") == "diagnostic_schema_error" for row in normalized
            ),
            "sanitized_message": sanitize_diagnostic_message(exc),
        }
    payload = {
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostics": normalized,
        "summary": summary,
    }
    report.write_text(json.dumps(payload, indent=2) + "\n")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    manifest_payload = {
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "capture_outcome": summary["capture_outcome"],
        "raw_har": str(raw),
        "diagnostic_report": str(report),
        "capture_manifest": str(manifest),
        "summary": str(summary_path),
    }
    manifest.write_text(json.dumps(manifest_payload, indent=2) + "\n")
    return {**manifest_payload, "reporting_failed": reporting_failed}


def capture_artifact_paths(config: CaptureConfig, raw: Path) -> dict[str, str]:
    label = validate_label(config.label)
    reports = config.output_directory / "reports"
    candidates = {
        "raw_har": raw,
        "diagnostic_report": reports / f"{label}-capture.json",
        "capture_manifest": reports / f"{label}-capture-manifest.json",
        "summary": reports / f"{label}-summary.json",
    }
    return {name: str(path) for name, path in candidates.items() if path.exists()}


def close_capture_resources(context, browser, record) -> None:
    """Best-effort resource closure that records, rather than raises, close diagnostics."""
    try:
        context.close()
    except Exception as exc:
        record("context_close_failed", sanitized_message=exc)
    if browser is not None:
        try:
            browser.close()
        except Exception as exc:
            record("browser_close_failed", sanitized_message=exc)


def capture_manual(config: CaptureConfig, repo_root: Path) -> Path:
    """Launch optional Playwright in a fresh visible context; CI must never call this."""
    config.validate(repo_root)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Manual browser capture requires the validation extra.\nFrom the repository root run:\n"
            'python -m pip install -e ".[dev,validation]"\npython -m playwright install chromium'
        ) from exc
    raw = config.output_directory / "raw" / f"{validate_label(config.label)}.har"
    raw.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        channel = None if config.browser == "chromium" else config.browser
        launch = {
            "headless": False,
            "channel": channel,
        }
        browser = None
        try:
            if config.profile_directory:
                config.profile_directory.mkdir(parents=True, exist_ok=True)
                context = pw.chromium.launch_persistent_context(
                    str(config.profile_directory),
                    **launch,
                    record_har_path=str(raw),
                    record_har_content="embed" if config.retain_response_bodies else "omit",
                    user_agent=config.user_agent,
                )
            else:
                browser = pw.chromium.launch(**launch)
                context = browser.new_context(
                    record_har_path=str(raw),
                    record_har_content="embed" if config.retain_response_bodies else "omit",
                    user_agent=config.user_agent,
                )
        except Exception as exc:
            report = config.output_directory / "reports" / f"{validate_label(config.label)}-capture.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps(
                    {
                        "diagnostics": [
                            {
                                "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                                "event_type": "browser_launch_failed",
                                "timestamp": utc_now(),
                                "sanitized_message": sanitize_diagnostic_message(exc),
                            }
                        ],
                        "summary": {
                            "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                            "capture_outcome": "browser_failed",
                            "suspected_spinner_reason": "browser_channel_incompatibility",
                            "requested_channel": config.browser,
                        },
                    },
                    indent=2,
                )
                + "\n"
            )
            raise RuntimeError(
                f"browser channel {config.browser!r} could not be launched; "
                "install that channel or retry with --browser chromium. "
                f"Diagnostic report: {report}"
            ) from None
        request_count = 0
        event_sequence = 0
        diagnostics = []
        counts = {"allowed": {}, "blocked": {}}

        def record(event_type: str, **fields) -> None:
            nonlocal event_sequence
            event_sequence += 1
            diagnostics.append(
                normalize_diagnostic(
                    {"timestamp": utc_now(), "event_type": event_type, **fields}
                )
            )
            # Sequence is used only in-memory to separate initialization from operator work.
            diagnostics[-1]["sequence"] = event_sequence

        def on_request(request) -> None:
            record("request_observed", **_request_diagnostic(request))

        def on_response(response) -> None:
            request = response.request
            parts = urlsplit(response.url)
            first_party = (parts.hostname or "").lower() in config.allowed_hosts
            record(
                "response_received",
                status_code=response.status,
                host=parts.hostname,
                path=parts.path or "/",
                resource_type=request.resource_type,
                request_method=request.method,
                first_party=first_party,
                redirect=response.status in {301, 302, 303, 307, 308},
            )

        def on_request_failed(request) -> None:
            parts = urlsplit(request.url)
            record(
                "request_failed",
                **_request_diagnostic(request),
                first_party=(parts.hostname or "").lower() in config.allowed_hosts,
                reason=sanitize_diagnostic_message(request.failure or "unknown"),
            )

        def route_handler(route):
            nonlocal request_count
            request_count += 1
            request = route.request
            fields = tuple(
                name for name, _ in parse_qsl(request.post_data or "", keep_blank_values=True)
            )
            decision = classify_request(
                config,
                request.method,
                request.url,
                headers=request.headers,
                field_names=fields,
                body_size=len((request.post_data or "").encode()),
                resource_type=request.resource_type,
            )
            bucket = "allowed" if decision.allowed else "blocked"
            if config.request_policy_mode == "first-party" and not decision.essential:
                route.continue_()
                return
            counts[bucket][request.method] = counts[bucket].get(request.method, 0) + 1
            if request_count > config.max_requests or not decision.allowed:
                parts = urlsplit(request.url)
                record(
                    "request_blocked",
                    source_id=config.source_id,
                    method=request.method,
                    host=parts.hostname,
                    path=parts.path,
                    resource_type=request.resource_type,
                    initiator_category="browser_page",
                    rule=decision.rule,
                    classification=decision.classification,
                    reason=(
                        "request budget exceeded"
                        if request_count > config.max_requests
                        else decision.reason
                    ),
                    essential=decision.essential,
                )
                route.abort()
                return
            route.continue_()

        if config.request_policy_mode != "observe":
            context.route("**/*", route_handler)
        page = context.new_page()
        # Every page-level diagnostic listener is attached before the first navigation.
        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        page.on(
            "console",
            lambda message: record(
                "console_error",
                classification=(
                    "csp_violation"
                    if "content security policy" in message.text.lower()
                    else "mixed_content"
                    if "mixed content" in message.text.lower()
                    else message.type
                ),
                sanitized_message=message.text,
            ),
        )
        page.on(
            "pageerror",
            lambda error: record("page_error", sanitized_message=error),
        )
        page.set_default_timeout(config.action_timeout * 1000)
        page.goto(
            config.starting_url,
            timeout=config.navigation_timeout * 1000,
            wait_until="domcontentloaded",
        )
        overlay_visible = False
        results_state_visible = False
        if config.source_id == "il-bidbuy":
            try:
                page.wait_for_function(
                    r"""() => {
                      const overlays = [...document.querySelectorAll('.ui-blockui, .ui-widget-overlay')];
                      const visible = overlays.some(e => {
                        const s = getComputedStyle(e); const r = e.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && r.width && r.height;
                      });
                      const rows = [...document.querySelectorAll('.ui-datatable tbody tr, [id*="bidSearchResults"] tbody tr')]
                        .filter(r => !r.matches('.ui-datatable-empty-message,.ui-skeleton') && r.offsetParent !== null && r.querySelector('td:not(:empty)'));
                      const empty = /no\s+(records|results|bids)\s+found/i.test(document.body.innerText);
                      return !visible && !!(rows.length || empty);
                    }""",
                    timeout=config.action_timeout * 1000,
                )
            except Exception as exc:
                record(
                    "startup_wait_incomplete",
                    sanitized_message=exc,
                )
            inspection = inspect_bidbuy_result_state(page)
            for diagnostic in inspection["diagnostics"]:
                record(
                    diagnostic.get("event_type", "diagnostic_schema_error"),
                    classification=diagnostic.get("classification"),
                    sanitized_message=diagnostic.get("sanitized_message", "malformed probe"),
                )
            overlay_visible = inspection["overlay_visible"]
            results_state_visible = bool(
                inspection["results_found"] or inspection["empty_results_found"]
            )
            startup = evaluate_bidbuy_startup(
                diagnostics,
                overlay_visible=overlay_visible,
                results_state_visible=results_state_visible,
                diagnostic_probe_failed=inspection["diagnostic_probe_failed"],
                result_state=inspection["result_state"],
            )
        else:
            startup = {
                "capture_outcome": "capture_partially_succeeded",
                "startup_succeeded": None,
                "suspected_spinner_reason": None,
            }
        initial_sequence = event_sequence
        if not startup.get("startup_succeeded"):
            print("WARNING: Initial BidBuy results request has not completed.")
        print(
            "The browser will remain open for manual inspection. Do not log in, register, "
            "upload files, solve CAPTCHA, or initiate vendor/bid actions. Type FINISH in the "
            "terminal when the public walkthrough is complete. STATUS prints live state; "
            "ABORT cancels the walkthrough."
        )
        try:
            phase_result = run_operator_phase(page, config.max_duration)
        except KeyboardInterrupt:
            phase_result = "operator_aborted"

        # Final evaluation deliberately follows all manual interaction.
        final_inspection = inspect_bidbuy_result_state(page)
        for diagnostic in final_inspection["diagnostics"]:
            record(
                diagnostic.get("event_type", "diagnostic_schema_error"),
                classification=diagnostic.get("classification"),
                sanitized_message=diagnostic.get("sanitized_message", "malformed probe"),
            )
        operator_posts = [
            row for row in diagnostics
            if row.get("event_type") == "request_observed"
            and row.get("method") == "POST"
            and row.get("path") == BIDBUY_SEARCH_PATH
            and row.get("sequence", 0) > initial_sequence
        ]
        operator_requests = [
            row for row in diagnostics
            if row.get("event_type") == "request_observed"
            and row.get("sequence", 0) > initial_sequence
        ]
        operator_paths = [str(row.get("path", "")).lower() for row in operator_requests]
        startup["initial_automatic_request_observed"] = startup.get(
            "expected_initial_jsf_post_observed", False
        )
        startup["operator_initiated_search_observed"] = bool(operator_posts)
        startup["capabilities"] = {
            "initial_automatic_request": startup["initial_automatic_request_observed"],
            "operator_initiated_search": bool(operator_posts),
            "pagination": any("page" in path for path in operator_paths),
            "detail_navigation": any("detail" in path or "viewbid" in path for path in operator_paths),
            "attachment_metadata": any("attachment" in path for path in operator_paths),
            "attachment_download": any(
                row.get("method") == "GET"
                and any(word in str(row.get("path", "")).lower() for word in ("download", "document"))
                for row in operator_requests
            ),
        }
        startup["final_visible_result_state"] = final_inspection["result_state"]
        startup["final_evaluation_after_manual_phase"] = True
        if phase_result != "finished":
            startup["capture_outcome"] = phase_result
        elif final_inspection["result_state"] in {
            "populated_results_observed", "explicit_empty_results_observed"
        } and operator_posts:
            startup["capture_outcome"] = "capture_succeeded"
        elif startup.get("startup_succeeded") or operator_posts:
            startup["capture_outcome"] = "capture_partially_succeeded"
        else:
            startup["capture_outcome"] = "initialization_failed"
        try:
            browser_version = (
                browser.version if browser is not None else context.browser.version
            )
        except Exception as exc:
            browser_version = "unknown"
            record("browser_state_unavailable", sanitized_message=exc)
        browser_info = {
            "requested_channel": config.browser,
            "resolved_channel": channel or "bundled-chromium",
            "version": browser_version,
            "headless": False,
            "profile_type": "persistent" if config.profile_directory else "ephemeral",
            "request_policy_mode": config.request_policy_mode,
        }
        # Closing the context flushes Playwright's HAR. Reporting happens only afterward.
        close_capture_resources(context, browser, record)
        artifacts = write_capture_reports(
            config=config,
            raw=raw,
            diagnostics=diagnostics,
            counts=counts,
            startup=startup,
            browser_info=browser_info,
        )
        summary = json.loads(Path(artifacts["summary"]).read_text())
        print(json.dumps({**summary, **capture_artifact_paths(config, raw)}, indent=2))
        if artifacts["reporting_failed"]:
            return raw
        if config.source_id == "il-bidbuy" and startup["capture_outcome"] == "initialization_failed":
            message = startup.get("message") or "BidBuy initialization failed after diagnostics."
            raise RuntimeError(
                f"{message}\nPartial raw HAR preserved at: {raw}\n"
                f"Sanitized diagnostic report: {artifacts['diagnostic_report']}\n"
                "Next step: retry with --browser chrome or --browser msedge and an alternate "
                "--request-policy mode; if initialization still fails, use import-har with a "
                "successful anonymous manual-browser HAR."
            )
    return raw
