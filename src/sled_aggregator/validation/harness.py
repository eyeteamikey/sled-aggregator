from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

CLASSIFICATIONS = {
    "live_verified", "fixture_verified", "public_but_changed", "authentication_required",
    "captcha_blocked", "network_blocked", "rate_limited", "retired", "replaced",
    "not_observed", "unknown",
}
SENSITIVE_KEYS = {"authorization", "cookie", "token", "key", "secret", "password", "session"}


@dataclass(frozen=True)
class HarnessConfig:
    request_budget: int = 3
    timeout: float = 10.0
    max_pages: int = 1
    max_results: int = 10
    rate_limit_seconds: float = 1.0
    retries: int = 1
    user_agent: str = "SLED-Aggregator-Public-Validator/0.1 (+read-only)"
    dry_run: bool = False

    def __post_init__(self) -> None:
        if self.request_budget < 1 or self.max_pages < 1 or self.max_results < 1:
            raise ValueError("request and collection limits must be positive")
        if self.timeout <= 0 or self.rate_limit_seconds < 0 or self.retries < 0:
            raise ValueError("timeout must be positive and retry/rate limits non-negative")


@dataclass
class Observation:
    request_url: str
    status_code: int | None = None
    content_type: str | None = None
    redirects: list[str] = field(default_factory=list)
    response_shape: str | None = None
    classification: str = "unknown"
    error: str | None = None


@dataclass
class ValidationResult:
    source_id: str
    jurisdiction_id: str
    platform_family: str
    environment: str
    observed_at: str
    dry_run: bool
    requests_used: int
    request_budget: int
    capabilities: dict[str, str]
    observations: list[Observation]
    promotion_eligible: bool
    limitations: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, "[REDACTED]" if key.lower() in SENSITIVE_KEYS else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _shape(body: bytes, content_type: str) -> str:
    shape: object
    if "json" in content_type.lower():
        try:
            value = json.loads(body[:1_000_000])
            shape = sorted(value) if isinstance(value, dict) else type(value).__name__
        except (ValueError, UnicodeDecodeError):
            shape = "invalid-json"
    else:
        text = body[:100_000].decode("utf-8", "replace").lower()
        tags = sorted({part.split()[0].rstrip(">") for part in text.split("<")[1:] if part})
        shape = tags[:50]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]


def _classify(response: httpx.Response) -> str:
    text = response.content[:100_000].decode("utf-8", "replace").lower()
    if response.status_code == 429:
        return "rate_limited"
    if any(term in text for term in ("captcha", "recaptcha", "hcaptcha", "verify you are human")):
        return "captcha_blocked"
    if response.status_code in {401, 403} or any(
        term in text for term in ("sign in", "log in", "authentication required")
    ):
        return "authentication_required"
    if response.status_code in {404, 410}:
        return "retired"
    if 200 <= response.status_code < 300:
        return "live_verified"
    return "unknown"


class ValidationHarness:
    def __init__(
        self,
        config: HarnessConfig,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(UTC))

    def validate(self, source: dict) -> ValidationResult:
        url = source["public_search_url"] or source["public_bid_board_url"]
        clean_url = redact_url(url)
        capabilities = {name: "not_observed" for name in (
            "source_identity", "landing_access", "search_access", "search_contract", "pagination",
            "empty_results", "detail_access", "attachment_metadata", "document_retrieval", "addenda",
            "redirects", "content_type", "authentication", "captcha", "rate_limiting", "retries",
            "response_shape", "normalization", "document_handoff", "idempotency",
        )}
        if self.config.dry_run:
            return ValidationResult(source["source_id"], source["jurisdiction_id"],
                source["platform_family"], "dry-run", self.clock().isoformat(), True, 0,
                self.config.request_budget, capabilities, [Observation(clean_url, classification="not_observed")],
                False, ["No network request was made."])

        observations: list[Observation] = []
        attempts = min(self.config.request_budget, self.config.retries + 1)
        headers = {"User-Agent": self.config.user_agent, "Accept": "text/html,application/json"}
        with httpx.Client(transport=self.transport, timeout=self.config.timeout,
                          follow_redirects=True, headers=headers) as client:
            for attempt in range(attempts):
                if attempt:
                    self.sleep(self.config.rate_limit_seconds)
                try:
                    response = client.get(url)
                    classification = _classify(response)
                    redirects = [redact_url(str(item.url)) for item in response.history]
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    observations.append(Observation(clean_url, response.status_code, content_type,
                        redirects, _shape(response.content, content_type), classification))
                    if classification != "rate_limited" and response.status_code < 500:
                        break
                except (httpx.ProxyError, httpx.ConnectError, httpx.TimeoutException) as exc:
                    observations.append(Observation(clean_url, classification="network_blocked",
                        error=type(exc).__name__))
        primary = observations[-1].classification
        capabilities["source_identity"] = "fixture_verified"
        capabilities["landing_access"] = primary
        capabilities["search_access"] = primary
        capabilities["content_type"] = primary if observations[-1].content_type else "not_observed"
        capabilities["response_shape"] = primary if observations[-1].response_shape else "not_observed"
        capabilities["redirects"] = primary if observations[-1].redirects else "not_observed"
        capabilities["authentication"] = ("authentication_required" if primary == "authentication_required"
                                               else "not_observed")
        capabilities["captcha"] = "captcha_blocked" if primary == "captcha_blocked" else "not_observed"
        capabilities["rate_limiting"] = "rate_limited" if primary == "rate_limited" else "not_observed"
        expected_shapes = source.get("validation_response_fingerprints", [])
        promotion = (
            primary == "live_verified"
            and observations[-1].response_shape in expected_shapes
        )
        limitations = [] if promotion else ["Response did not establish promotion eligibility."]
        return ValidationResult(source["source_id"], source["jurisdiction_id"],
            source["platform_family"], "codex-cloud", self.clock().isoformat(), False,
            len(observations), self.config.request_budget, capabilities, observations, promotion, limitations)


def render_json(results: list[ValidationResult]) -> str:
    return json.dumps([item.as_dict() for item in sorted(results, key=lambda x: x.source_id)], indent=2,
                      sort_keys=True) + "\n"


def render_markdown(results: list[ValidationResult]) -> str:
    lines = ["# Bounded public-source validation", "", "| Source | Requests | Landing | Promotion |",
             "|---|---:|---|---|"]
    for item in sorted(results, key=lambda x: x.source_id):
        lines.append(f"| `{item.source_id}` | {item.requests_used}/{item.request_budget} | "
                     f"{item.capabilities['landing_access']} | {'yes' if item.promotion_eligible else 'no'} |")
    return "\n".join(lines) + "\n"
