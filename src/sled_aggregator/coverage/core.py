"""Deterministic, offline SLED coverage audit."""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sled_aggregator.connectors.registry import connector_registry

SCHEMA_VERSION = "2.0"
ROOT = Path(__file__).resolve().parents[3]
JURISDICTIONS_PATH = ROOT / "data/coverage/jurisdictions.json"
SOURCES_PATH = ROOT / "data/coverage/sources.json"

JURISDICTION_TYPES = {"state", "district", "territory"}
SOURCE_LEVELS = {
    "statewide",
    "state agency",
    "local",
    "county",
    "municipality",
    "education",
    "transportation",
    "authority",
    "quasi-public",
    "territory-wide",
    "supplemental",
    "archive",
}
SOURCE_ROLES = {
    "primary",
    "supplemental",
    "document host",
    "award source",
    "archive",
    "external notice",
    "replacement",
    "legacy",
}
CONNECTOR_STATUSES = {
    "implemented",
    "partially_implemented",
    "configured",
    "configured_unverified",
    "fixture_only",
    "missing",
    "unsupported",
    "deprecated",
    "migrated",
    "intentionally_excluded",
}
VERIFICATION_STATUSES = {
    "fixture_verified",
    "live_public_verified",
    "configured_unverified",
    "public_metadata_only",
    "registration_required",
    "agency_enrollment_required",
    "login_required",
    "subscription_required",
    "payment_required",
    "captcha_required",
    "robots_policy_blocked",
    "automated_access_blocked",
    "changed_markup",
    "migrated",
    "legacy",
    "blocked",
    "unavailable",
    "unknown",
}
ACCESS = {
    "discovery_access": {"public", "gated", "blocked", "unavailable", "unknown"},
    "detail_access": {"public", "metadata_only", "gated", "blocked", "unavailable", "unknown"},
    "document_access": {
        "public",
        "mixed",
        "registration_required",
        "login_required",
        "subscription_required",
        "payment_required",
        "unavailable",
        "unknown",
    },
    "award_access": {"public", "metadata_only", "gated", "unavailable", "unknown"},
}
SOURCE_FIELDS = {
    "key",
    "jurisdiction_code",
    "name",
    "source_level",
    "source_role",
    "official_url",
    "discovery_url",
    "detail_url_pattern",
    "platform_family",
    "connector_name",
    "connector_status",
    "verification_status",
    "verification_signals",
    "discovery_access",
    "detail_access",
    "document_access",
    "award_access",
    "authoritative",
    "supplemental",
    "source_status",
    "authentication_requirement",
    "registration_requirement",
    "subscription_requirement",
    "captcha_status",
    "robots_policy_status",
    "automated_access_status",
    "migration_status",
    "replacement_source",
    "last_verified",
    "evidence_url",
    "fixture_references",
    "notes",
    "priority",
    "expected_coverage_impact",
    "covers_levels",
    "source_id",
    "jurisdiction_id",
    "jurisdiction_scope",
    "owning_public_entity",
    "official_landing_page",
    "public_bid_board_url",
    "public_search_url",
    "public_detail_url_pattern",
    "connector_key",
    "connector_alias",
    "portal_profile_key",
    "anonymous_discovery_classification",
    "anonymous_detail_classification",
    "attachment_classification",
    "document_pipeline_classification",
    "captcha_classification",
    "robots_access_notes",
    "allowed_http_methods",
    "evidence_type",
    "evidence_location",
    "fixture_location",
    "test_location",
    "last_verified_date",
    "known_limitations",
    "blocker_reason",
    "recommended_next_action",
}

STATEWIDE_SCOPES = {"statewide", "territory-wide"}
LIFECYCLE_STATUSES = {
    "unresearched",
    "source_identified",
    "evidence_pending",
    "connector_family_identified",
    "connector_available",
    "fixture_verified",
    "live_verified",
    "partially_operational",
    "operational",
    "blocked",
    "retired",
    "replaced",
}


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    file: str
    record: str
    field: str
    value: object
    correction: str

    def as_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def _issue(
    file: Path, record: str, field: str, value: object, correction: str, severity: str = "error"
) -> ValidationIssue:
    return ValidationIssue(severity, str(file.relative_to(ROOT)), record, field, value, correction)


def validate(jdata: dict | None = None, sdata: dict | None = None) -> list[ValidationIssue]:
    jdata, sdata = jdata or load(JURISDICTIONS_PATH), sdata or load(SOURCES_PATH)
    issues: list[ValidationIssue] = []
    for path, data in ((JURISDICTIONS_PATH, jdata), (SOURCES_PATH, sdata)):
        if data.get("schema_version") != SCHEMA_VERSION:
            issues.append(
                _issue(
                    path,
                    "registry",
                    "schema_version",
                    data.get("schema_version"),
                    f"use supported version {SCHEMA_VERSION}",
                )
            )
    jurisdictions = jdata.get("jurisdictions", [])
    codes = [j.get("code") for j in jurisdictions]
    names = [j.get("name") for j in jurisdictions]
    counts = {
        kind: sum(j.get("type") == kind for j in jurisdictions) for kind in JURISDICTION_TYPES
    }
    expected = {"state": 50, "district": 1, "territory": 5}
    if len(jurisdictions) != 56:
        issues.append(
            _issue(
                JURISDICTIONS_PATH,
                "registry",
                "jurisdictions",
                len(jurisdictions),
                "include exactly 56 primary jurisdictions",
            )
        )
    for kind, count in expected.items():
        if counts[kind] != count:
            issues.append(
                _issue(
                    JURISDICTIONS_PATH,
                    "registry",
                    "type",
                    counts[kind],
                    f"include exactly {count} {kind} records",
                )
            )
    if len(codes) != len(set(codes)):
        issues.append(
            _issue(
                JURISDICTIONS_PATH, "registry", "code", codes, "remove duplicate jurisdiction codes"
            )
        )
    if len(names) != len(set(names)):
        issues.append(
            _issue(
                JURISDICTIONS_PATH, "registry", "name", names, "remove duplicate canonical names"
            )
        )
    required_jurisdiction_fields = {
        "jurisdiction_id",
        "jurisdiction_name",
        "jurisdiction_type",
        "postal_code",
        "fips_code",
        "primary_source_id",
        "supplemental_source_ids",
        "coverage_tier",
        "coverage_status",
        "operational_status",
        "discovery_status",
        "detail_status",
        "attachment_status",
        "document_pipeline_status",
        "live_validation_status",
        "last_verified_at",
        "known_gaps",
        "next_action",
        "notes",
    }
    for jurisdiction in jurisdictions:
        code = str(jurisdiction.get("code", "<missing>"))
        missing = sorted(required_jurisdiction_fields - set(jurisdiction))
        if missing:
            issues.append(
                _issue(
                    JURISDICTIONS_PATH,
                    code,
                    "required_fields",
                    missing,
                    "add all authoritative jurisdiction control-plane fields",
                )
            )
        if jurisdiction.get("jurisdiction_id") != code:
            issues.append(
                _issue(
                    JURISDICTIONS_PATH,
                    code,
                    "jurisdiction_id",
                    jurisdiction.get("jurisdiction_id"),
                    "match the stable code",
                )
            )
        if jurisdiction.get("jurisdiction_type") not in JURISDICTION_TYPES:
            issues.append(
                _issue(
                    JURISDICTIONS_PATH,
                    code,
                    "jurisdiction_type",
                    jurisdiction.get("jurisdiction_type"),
                    "use state, district, or territory",
                )
            )
        if jurisdiction.get("coverage_status") not in LIFECYCLE_STATUSES:
            issues.append(
                _issue(
                    JURISDICTIONS_PATH,
                    code,
                    "coverage_status",
                    jurisdiction.get("coverage_status"),
                    "use an explicit lifecycle status",
                )
            )
    canonical = {x["canonical_name"] for x in connector_registry.inventory()}
    keys: set[str] = set()
    sources = sdata.get("sources", [])
    all_keys = {s.get("key") for s in sources}
    evidence = sdata.get("evidence", [])
    evidence_ids = [item.get("evidence_id") for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        issues.append(
            _issue(
                SOURCES_PATH,
                "evidence",
                "evidence_id",
                evidence_ids,
                "use unique stable evidence IDs",
            )
        )
    for item in evidence:
        if item.get("source_id") not in all_keys:
            issues.append(
                _issue(
                    SOURCES_PATH,
                    str(item.get("evidence_id")),
                    "source_id",
                    item.get("source_id"),
                    "reference an existing source",
                )
            )
        location = item.get("location")
        if (
            location
            and not str(location).startswith(("http://", "https://"))
            and not (ROOT / location).is_file()
        ):
            issues.append(
                _issue(
                    SOURCES_PATH,
                    str(item.get("evidence_id")),
                    "location",
                    location,
                    "reference a committed artifact or official HTTP(S) URL",
                )
            )
    for jurisdiction in jurisdictions:
        primary = jurisdiction.get("primary_source_id")
        if primary and primary not in all_keys:
            issues.append(
                _issue(
                    JURISDICTIONS_PATH,
                    jurisdiction["code"],
                    "primary_source_id",
                    primary,
                    "reference an existing source",
                )
            )
        if primary:
            source = next((s for s in sources if s.get("key") == primary), {})
            if (
                source.get("jurisdiction_code") != jurisdiction["code"]
                or source.get("source_level") not in STATEWIDE_SCOPES
            ):
                issues.append(
                    _issue(
                        JURISDICTIONS_PATH,
                        jurisdiction["code"],
                        "primary_source_id",
                        primary,
                        "reference an authoritative statewide source in this jurisdiction",
                    )
                )
        if jurisdiction.get("operational_status") == "baseline_operational" and not primary:
            issues.append(
                _issue(
                    JURISDICTIONS_PATH,
                    jurisdiction["code"],
                    "operational_status",
                    "baseline_operational",
                    "register a qualifying primary statewide source",
                )
            )
    for source in sources:
        key = str(source.get("key", "<missing>"))
        unknown = set(source) - SOURCE_FIELDS
        if unknown:
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "unknown_fields",
                    sorted(unknown),
                    "remove unknown or misspelled fields",
                )
            )
        if key in keys:
            issues.append(_issue(SOURCES_PATH, key, "key", key, "use a unique stable source key"))
        keys.add(key)
        for field, allowed in (
            ("source_level", SOURCE_LEVELS),
            ("source_role", SOURCE_ROLES),
            ("connector_status", CONNECTOR_STATUSES),
            ("verification_status", VERIFICATION_STATUSES),
            *ACCESS.items(),
        ):
            if source.get(field) not in allowed:
                issues.append(
                    _issue(
                        SOURCES_PATH, key, field, source.get(field), f"use one of {sorted(allowed)}"
                    )
                )
        if source.get("jurisdiction_code") not in codes:
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "jurisdiction_code",
                    source.get("jurisdiction_code"),
                    "reference a canonical jurisdiction code",
                )
            )
        connector = source.get("connector_name")
        if (
            connector
            and connector not in canonical
            and source.get("connector_status")
            not in {"missing", "unsupported", "intentionally_excluded"}
        ):
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "connector_name",
                    connector,
                    "use a canonical registered connector or mark it missing",
                )
            )
        for field in ("official_url", "discovery_url", "evidence_url"):
            value = source.get(field)
            if not value:
                continue
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                issues.append(
                    _issue(SOURCES_PATH, key, field, value, "use an absolute public HTTP(S) URL")
                )
            elif (
                parsed.username
                or parsed.password
                or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                or parsed.hostname.endswith((".local", ".internal"))
            ):
                issues.append(
                    _issue(
                        SOURCES_PATH,
                        key,
                        field,
                        value,
                        "remove credentials and private/local hosts",
                    )
                )
        if source.get("authoritative") and not source.get("official_url"):
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "official_url",
                    None,
                    "provide the primary source's authoritative URL",
                )
            )
        if source.get("verification_status") == "live_public_verified" and (
            not source.get("evidence_url") or not source.get("last_verified")
        ):
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "verification_status",
                    "live_public_verified",
                    "add public evidence URL and verification date",
                )
            )
        if source.get("verification_status") == "fixture_verified" and not source.get(
            "fixture_references"
        ):
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "fixture_references",
                    None,
                    "reference at least one committed fixture",
                )
            )
        if source.get("verification_status") == "fixture_verified" and not any(
            item.get("source_id") == key for item in evidence
        ):
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "evidence",
                    None,
                    "add evidence records for affirmative fixture claims",
                )
            )
        if source.get("document_pipeline_classification") == "compatible":
            from sled_aggregator.services.document_orchestration import PIPELINE_CONNECTORS

            if source.get("connector_name") not in PIPELINE_CONNECTORS:
                issues.append(
                    _issue(
                        SOURCES_PATH,
                        key,
                        "document_pipeline_classification",
                        "compatible",
                        "register the connector in PIPELINE_CONNECTORS",
                    )
                )
        replacement = source.get("replacement_source")
        if replacement and not replacement.startswith("external:") and replacement not in all_keys:
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "replacement_source",
                    replacement,
                    "reference an existing key or prefix an external source with external:",
                )
            )
        if source.get("migration_status") == "migrated" and source.get("source_status") == "active":
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "source_status",
                    "active",
                    "mark migrated sources legacy or explicitly dual-published",
                )
            )
        if (
            source.get("source_status") == "active"
            and source.get("verification_status") == "unavailable"
        ):
            issues.append(
                _issue(
                    SOURCES_PATH,
                    key,
                    "source_status",
                    "active",
                    "do not mark an unavailable source active",
                )
            )
    return issues


def connector_inventory(sources: list[dict]) -> list[dict]:
    result = []
    for item in connector_registry.inventory():
        family = item["canonical_name"]
        profiles = [s for s in sources if s.get("connector_name") == family]
        stem = str(item["implementation_module"]).rsplit(".", 1)[-1]
        fixtures = sorted(
            {
                *(str(p.relative_to(ROOT)) for p in (ROOT / "tests/fixtures").glob(f"{stem}*")),
                *(
                    reference
                    for profile in profiles
                    for reference in profile.get("fixture_references", [])
                ),
            }
        )
        tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob(f"test_{stem}*"))
        result.append(
            {
                **item,
                "registry_presence": True,
                "profile_count": len(profiles),
                "supported_jurisdictions": sorted({s["jurisdiction_code"] for s in profiles}),
                "discovery_capability": True,
                "detail_capability": any(s["detail_access"] == "public" for s in profiles),
                "document_link_capability": any(
                    s["document_access"] in {"public", "mixed"} for s in profiles
                ),
                "document_pipeline_compatible": bool(item["document_pipeline_compatible"])
                and bool(fixtures)
                and bool(tests)
                and any(s["document_access"] in {"public", "mixed"} for s in profiles),
                "request_method_policy": "bounded public read-only",
                "fixture_count": len(fixtures),
                "test_references": tests,
                "implementation_status": "implemented",
                "documented_limitations": "Profile and access claims remain tenant-specific.",
            }
        )
    return result


def tier(sources: list[dict], inventory: dict[str, dict]) -> int:
    authoritative = [s for s in sources if s.get("authoritative")]
    if not authoritative:
        return 0
    current = [
        s
        for s in sources
        if s.get("source_status") == "active" and s.get("migration_status") != "migrated"
    ]
    if not current or all(
        s.get("connector_status") in {"missing", "unsupported", "migrated", "deprecated"}
        for s in current
    ):
        return 1
    if all(
        s.get("connector_status") in {"configured", "configured_unverified", "fixture_only"}
        for s in current
    ):
        return 2
    usable = [s for s in current if s.get("connector_name") in inventory]
    if not usable:
        return 1
    best = 3 if any(s["discovery_access"] == "public" for s in usable) else 2
    if any(
        s["detail_access"] == "public" and s["document_access"] in {"public", "mixed"}
        for s in usable
    ):
        best = 4
    if any(
        s["document_access"] == "public"
        and inventory[s["connector_name"]]["document_pipeline_compatible"]
        for s in usable
    ):
        best = 5
    if any(s["verification_status"] == "live_public_verified" for s in usable) and best >= 5:
        best = 6
    if any(s["verification_status"] in {"changed_markup", "migrated"} for s in usable):
        best = min(best, 2)
    if all(s["document_access"] not in {"public", "mixed"} for s in usable):
        best = min(best, 3)
    return best


def gaps_for(jurisdiction: dict, sources: list[dict]) -> list[str]:
    gaps: set[str] = set()
    if not any(s.get("authoritative") for s in sources):
        gaps.add("no_source_identified")
    if not sources:
        if jurisdiction["type"] == "territory":
            gaps.add("territory_gap")
        return sorted(gaps)
    if any(s["connector_status"] == "missing" for s in sources):
        gaps.add("connector_missing")
    if any(s["connector_status"] in {"configured", "configured_unverified"} for s in sources):
        gaps.add("fixture_missing")
    if not any(s["verification_status"] == "live_public_verified" for s in sources):
        gaps.add("live_verification_missing")
    if any(s["discovery_access"] == "blocked" for s in sources):
        gaps.add("discovery_blocked")
    if any(s["detail_access"] == "blocked" for s in sources):
        gaps.add("detail_blocked")
    if any(
        s["document_access"]
        in {"registration_required", "login_required", "subscription_required", "payment_required"}
        for s in sources
    ):
        gaps.add("documents_gated")
    if any(s["document_access"] == "unavailable" for s in sources):
        gaps.add("documents_unavailable")
    statuses = {s["verification_status"] for s in sources}
    for status, gap in (
        ("captcha_required", "captcha_blocked"),
        ("robots_policy_blocked", "robots_blocked"),
        ("automated_access_blocked", "automated_access_blocked"),
        ("changed_markup", "changed_markup"),
    ):
        if status in statuses:
            gaps.add(gap)
    if any(
        s.get("migration_status") == "migrated" and not s.get("replacement_source") for s in sources
    ):
        gaps.add("migrated_without_replacement")
    levels = {s["source_level"] for s in sources}
    if not levels & {"local", "county", "municipality"}:
        gaps.add("incomplete_local_coverage")
    if "education" not in levels:
        gaps.add("incomplete_education_coverage")
    if "transportation" not in levels:
        gaps.add("incomplete_transportation_coverage")
    if not any(s["award_access"] == "public" for s in sources):
        gaps.add("incomplete_award_coverage")
    return sorted(gaps)


def recommendations(hypotheses: list[dict]) -> list[dict]:
    rows = []
    for item in hypotheses:
        factors = {
            k: item[k]
            for k in (
                "jurisdictions_unlocked",
                "statewide_impact",
                "public_access",
                "documents",
                "reuse",
                "complexity",
                "maintenance_risk",
                "blocked_penalty",
                "territory_impact",
            )
        }
        score = (
            factors["jurisdictions_unlocked"] * 4
            + factors["statewide_impact"] * 3
            + factors["public_access"] * 3
            + factors["documents"] * 2
            + factors["reuse"] * 3
            + factors["territory_impact"] * 2
            - factors["complexity"] * 2
            - factors["maintenance_risk"] * 2
            - factors["blocked_penalty"] * 5
        )
        band = "P1" if score >= 30 else "P2" if score >= 20 else "P3" if score >= 10 else "P4"
        rows.append(
            {
                "family": item["family"],
                "evidence_status": item.get("evidence_status", "research_only_hypothesis"),
                "score": score,
                "priority_band": band,
                "factors": factors,
                "recommended_next_action": item["recommendation"],
            }
        )
    return sorted(rows, key=lambda x: (-x["score"], x["family"]))


def recommendation_queue(records: list[dict], sources: list[dict]) -> list[dict]:
    """Create planning work only from registered sources and explicit registry gaps."""
    rows: list[dict] = []
    order = 1
    for record in records:
        primary = next((s for s in sources if s["key"] == record.get("primary_source_id")), None)
        if (
            primary
            and primary.get("verification_status") in {"fixture_verified", "live_public_verified"}
            and not record["live_verified"]
        ):
            rows.append(
                {
                    "recommended_order": order,
                    "proposed_title": f"Validate {record['name']} anonymous statewide collection",
                    "task_type": "live_validation",
                    "jurisdiction_ids": [record["code"]],
                    "source_ids": [primary["key"]],
                    "connector_family": primary["platform_family"],
                    "evidence_available": primary.get("fixture_references", []),
                    "evidence_required": ["dated bounded anonymous live-validation result"],
                    "expected_baseline_coverage_increase": 0,
                    "expected_document_pipeline_increase": 0,
                    "risk_level": "medium",
                    "dependencies": [],
                    "score": 50,
                    "priority_band": "P1",
                }
            )
            order += 1
    for record in records:
        primary = next((s for s in sources if s["key"] == record.get("primary_source_id")), None)
        if not primary or primary.get("verification_status") in {
            "fixture_verified",
            "live_public_verified",
        }:
            continue
        rows.append(
            {
                "recommended_order": order,
                "proposed_title": f"Capture {record['name']} public procurement contract",
                "task_type": "public_contract_capture",
                "jurisdiction_ids": [record["code"]],
                "source_ids": [primary["key"]],
                "connector_family": primary.get("platform_family"),
                "evidence_available": primary.get("evidence_location", []),
                "evidence_required": [
                    "platform and tenant evidence",
                    "sanitized anonymous public request and response contract",
                ],
                "expected_baseline_coverage_increase": 1,
                "expected_document_pipeline_increase": 0,
                "risk_level": "high",
                "dependencies": [],
                "score": 20,
                "priority_band": "P2",
            }
        )
        order += 1
    for record in records:
        if not record["local_evidence_only"] and record.get("primary_source_id"):
            continue
        actual = [s for s in sources if s["jurisdiction_code"] == record["code"]]
        if not actual:
            continue  # unidentified sources are intentionally never ranked
        rows.append(
            {
                "recommended_order": order,
                "proposed_title": f"Research authoritative statewide coverage for {record['name']}",
                "task_type": "coverage_correction"
                if record["local_evidence_only"]
                else "source_research",
                "jurisdiction_ids": [record["code"]],
                "source_ids": [s["key"] for s in actual],
                "connector_family": None,
                "evidence_available": [p for s in actual for p in s.get("fixture_references", [])],
                "evidence_required": ["official primary statewide source evidence"],
                "expected_baseline_coverage_increase": 0,
                "expected_document_pipeline_increase": 0,
                "risk_level": "high",
                "dependencies": [],
                "score": 20,
                "priority_band": "P2",
            }
        )
        order += 1
    return rows


def closeout_plan(report: dict) -> dict:
    """Build an offline, executable plan for closing breadth and validating fixtures."""
    records = report["jurisdiction_records"]
    sources = report["source_records"]
    primary_by_id = {s["key"]: s for s in sources}
    unidentified = [j for j in records if not j.get("primary_source_id")]
    unclassified = [
        primary_by_id[j["primary_source_id"]]
        for j in records
        if j.get("primary_source_id")
        and not primary_by_id[j["primary_source_id"]].get("platform_family")
    ]
    connector_missing = [
        primary_by_id[j["primary_source_id"]]
        for j in records
        if j.get("primary_source_id")
        and primary_by_id[j["primary_source_id"]].get("platform_family")
        and not primary_by_id[j["primary_source_id"]].get("connector_name")
    ]
    awaiting_live = [j for j in records if j["fixture_verified"] and not j["live_verified"]]
    blockers = [
        {
            "source_id": s["key"],
            "jurisdiction_id": s["jurisdiction_code"],
            "authentication": s.get("authentication_requirement", "unknown"),
            "captcha": s.get("captcha_classification", "unknown"),
            "robots": s.get("robots_access_notes", "unknown"),
            "blocker": s.get("blocker_reason"),
        }
        for s in sources
        if s.get("blocker_reason")
        or s.get("authentication_requirement") not in {None, "none", "unknown"}
        or s.get("captcha_classification")
        not in {None, "none", "none_observed_in_fixture", "unknown"}
        or s.get("robots_access_notes") not in {None, "not_live_validated", "unknown"}
    ]
    validation_tasks = []
    for order, jurisdiction in enumerate(awaiting_live, 1):
        source = primary_by_id[jurisdiction["primary_source_id"]]
        validation_tasks.append(
            {
                "order": order,
                "task_type": "bounded_anonymous_live_validation",
                "jurisdiction_id": jurisdiction["code"],
                "source_id": source["key"],
                "platform_family": source["platform_family"],
                "method_policy": source.get("allowed_http_methods", ["GET"]),
                "entry_url": source.get("public_bid_board_url") or source["official_url"],
                "capture": [
                    "timestamp and final allowlisted URL",
                    "status, content type, and redirect chain",
                    "bounded discovery result and stable identifier",
                    "detail response when publicly linked",
                    "attachment metadata only; do not download during discovery",
                    "authentication, CAPTCHA, robots, rate-limit, proxy, and network observations",
                ],
                "promotion_requirements": [
                    "successful bounded anonymous production request",
                    "response matches the registered fixture contract",
                    "dated sanitized evidence contains no credentials, cookies, or personal data",
                    "registry last_verified fields and generated reports are updated",
                ],
            }
        )
    summary = report["summary"]
    return {
        "schema_version": "1.0",
        "as_of": report["as_of"],
        "breadth_complete": not connector_missing,
        "breadth_totals": {
            "target_jurisdictions": len(records),
            "primary_sources_identified": sum(bool(j.get("primary_source_id")) for j in records),
            "platform_families_identified": sum(bool(j["platform_family"]) for j in records),
            "registered_connector_profiles": sum(
                bool(j["connector"] and primary_by_id[j["primary_source_id"]].get("portal_profile_key"))
                for j in records
                if j.get("primary_source_id")
            ),
            "fixture_verified": sum(j["fixture_verified"] for j in records),
            "discovery_capable": summary["discovery_capable_jurisdiction_count"],
            "detail_capable": summary["detail_capable_jurisdiction_count"],
            "attachment_capable": summary["attachment_capable_jurisdiction_count"],
            "document_pipeline_compatible": summary[
                "document_pipeline_capable_jurisdiction_count"
            ],
            "live_verified": summary["live_validated_jurisdiction_count"],
            "production_monitored": 0,
            "tier_0_remaining": summary["coverage_tier_distribution"]["0"],
            "blocked_jurisdictions": len({x["jurisdiction_id"] for x in blockers}),
        },
        "unidentified_primary_sources": [j["code"] for j in unidentified],
        "unclassified_primary_sources": [s["key"] for s in unclassified],
        "platform_identified_connector_missing": [s["key"] for s in connector_missing],
        "fixture_verified_awaiting_live": [j["primary_source_id"] for j in awaiting_live],
        "access_blockers": blockers,
        "validation_tasks": validation_tasks,
        "promotion_rule": "Fixture evidence may be promoted only after a dated, bounded, anonymous production request succeeds and its sanitized response matches the registered contract; production monitoring requires a separate recurring health signal.",
    }


def build_report(
    as_of: str | None = None, jdata: dict | None = None, sdata: dict | None = None
) -> dict:
    jdata, sdata = jdata or load(JURISDICTIONS_PATH), sdata or load(SOURCES_PATH)
    sources = sorted(
        sdata["sources"], key=lambda s: (s["jurisdiction_code"], s.get("priority", 99), s["key"])
    )
    inventory_rows = connector_inventory(sources)
    inventory = {x["canonical_name"]: x for x in inventory_rows}
    records, mappings, all_gaps = [], [], []
    for jurisdiction in sorted(jdata["jurisdictions"], key=lambda j: j["code"]):
        linked = [s for s in sources if s["jurisdiction_code"] == jurisdiction["code"]]
        statewide = [s for s in linked if s.get("source_level") in STATEWIDE_SCOPES]
        value, gaps = tier(statewide, inventory), gaps_for(jurisdiction, statewide)
        primary = next(
            (s for s in statewide if s["key"] == jurisdiction.get("primary_source_id")), None
        )
        fixture = bool(primary and primary.get("verification_status") == "fixture_verified")
        discovery = bool(primary and fixture and primary.get("discovery_access") == "public")
        details = bool(discovery and primary.get("detail_access") == "public")
        attachments = bool(details and primary.get("document_access") in {"public", "mixed"})
        pipeline = bool(
            attachments and primary.get("document_pipeline_classification") == "compatible"
        )
        live = bool(
            primary
            and primary.get("verification_status") == "live_public_verified"
            and primary.get("last_verified")
        )
        baseline = bool(primary and discovery and primary.get("connector_name") in inventory)
        records.append(
            {
                **jurisdiction,
                "coverage_tier": value,
                "source_keys": [s["key"] for s in linked],
                "statewide_source_keys": [s["key"] for s in statewide],
                "local_evidence_only": bool(linked and not statewide),
                "primary_source_name": primary.get("name") if primary else None,
                "platform_family": primary.get("platform_family") if primary else None,
                "connector": primary.get("connector_name") if primary else None,
                "fixture_verified": fixture,
                "discovery_capable": discovery,
                "detail_capable": details,
                "attachment_capable": attachments,
                "document_pipeline_capable": pipeline,
                "live_verified": live,
                "baseline_operational": baseline,
                "authentication": primary.get("authentication_requirement")
                if primary
                else "unknown",
                "captcha": primary.get("captcha_classification") if primary else "unknown",
                "blocker": primary.get("blocker_reason")
                if primary
                else "primary statewide source not evidence-backed",
                "gaps": gaps,
            }
        )
        all_gaps.extend(
            {"jurisdiction_code": jurisdiction["code"], "gap_type": gap} for gap in gaps
        )
        mappings.extend(
            {
                "jurisdiction_code": jurisdiction["code"],
                "source_key": s["key"],
                "coverage_tier": value,
            }
            for s in linked
        )
    distribution = {str(i): sum(j["coverage_tier"] == i for j in records) for i in range(7)}

    def count(field: str, values: set[str]) -> int:
        return sum(s[field] in values for s in sources)

    operational_distribution: dict[str, int] = {}
    for record in records:
        status = record["operational_status"]
        operational_distribution[status] = operational_distribution.get(status, 0) + 1
    family_counts: dict[str, int] = {}
    for record in records:
        if record["platform_family"]:
            family_counts[record["platform_family"]] = (
                family_counts.get(record["platform_family"], 0) + 1
            )
    summary = {
        "jurisdiction_count": len(records),
        "source_count": len(sources),
        "implemented_connector_count": len(inventory_rows),
        "coverage_tier_distribution": distribution,
        "operational_status_distribution": dict(sorted(operational_distribution.items())),
        "baseline_operational_count": sum(j["baseline_operational"] for j in records),
        "discovery_capable_jurisdiction_count": sum(j["discovery_capable"] for j in records),
        "detail_capable_jurisdiction_count": sum(j["detail_capable"] for j in records),
        "attachment_capable_jurisdiction_count": sum(j["attachment_capable"] for j in records),
        "document_pipeline_capable_jurisdiction_count": sum(
            j["document_pipeline_capable"] for j in records
        ),
        "live_validated_jurisdiction_count": sum(j["live_verified"] for j in records),
        "lacking_primary_source_count": sum(not j.get("primary_source_id") for j in records),
        "local_evidence_only_count": sum(j["local_evidence_only"] for j in records),
        "authentication_blocked_jurisdiction_count": sum(
            j["authentication"] not in {"none", "unknown"} for j in records
        ),
        "captcha_affected_jurisdiction_count": sum(
            j["captcha"] not in {"none", "none_observed_in_fixture", "unknown"} for j in records
        ),
        "connector_family_counts": dict(sorted(family_counts.items())),
        "public_discovery_count": count("discovery_access", {"public"}),
        "public_detail_count": count("detail_access", {"public"}),
        "public_document_pipeline_count": sum(
            bool(inventory.get(s.get("connector_name"), {}).get("document_pipeline_compatible"))
            and s.get("document_access") in {"public", "mixed"}
            and bool(s.get("fixture_references"))
            and s.get("verification_status") in {"fixture_verified", "live_public_verified"}
            for s in sources
        ),
        "metadata_only_count": count("detail_access", {"metadata_only"}),
        "registration_required_count": count("document_access", {"registration_required"}),
        "login_required_count": count("document_access", {"login_required"}),
        "subscription_required_count": count("document_access", {"subscription_required"}),
        "payment_required_count": count("document_access", {"payment_required"}),
        "captcha_count": count("verification_status", {"captcha_required"}),
        "robots_policy_count": count("verification_status", {"robots_policy_blocked"}),
        "automated_access_block_count": count("verification_status", {"automated_access_blocked"}),
        "changed_markup_count": count("verification_status", {"changed_markup"}),
        "migrated_source_count": sum(s.get("migration_status") == "migrated" for s in sources),
        "missing_source_count": sum(not j["source_keys"] for j in records),
        "unverified_source_count": sum(
            s["verification_status"] != "live_public_verified" for s in sources
        ),
    }
    issues = validate(jdata, sdata)
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of or sdata["as_of"],
        "summary": summary,
        "connector_inventory": inventory_rows,
        "jurisdiction_records": records,
        "source_records": sources,
        "jurisdiction_source_mappings": mappings,
        "gap_analysis": all_gaps,
        "prioritized_recommendations": recommendation_queue(records, sources),
        "validation_warnings": [i.as_dict() for i in issues if i.severity == "warning"],
        "generation_metadata": {
            "generator": "sled_aggregator.coverage",
            "network_requests": False,
            "ordering": "jurisdiction code, source priority, stable key",
        },
    }


def render_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


CSV_FIELDS = (
    "jurisdiction_code",
    "jurisdiction_name",
    "jurisdiction_type",
    "coverage_tier",
    "source_key",
    "source_name",
    "source_level",
    "source_role",
    "platform_family",
    "connector_name",
    "connector_status",
    "verification_status",
    "discovery_access",
    "detail_access",
    "document_access",
    "award_access",
    "primary_source",
    "source_status",
    "migration_status",
    "replacement_source",
    "last_verified",
    "evidence_url",
    "priority",
    "gap_reason",
    "recommended_next_action",
)


def render_csv(report: dict) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    sources = {s["key"]: s for s in report["source_records"]}
    for j in report["jurisdiction_records"]:
        keys = j["source_keys"] or [None]
        for key in keys:
            s = sources.get(key, {})
            row = {
                "jurisdiction_code": j["code"],
                "jurisdiction_name": j["name"],
                "jurisdiction_type": j["type"],
                "coverage_tier": j["coverage_tier"],
                "source_key": key or "",
                "source_name": s.get("name", ""),
                "source_level": s.get("source_level", ""),
                "source_role": s.get("source_role", ""),
                "platform_family": s.get("platform_family", ""),
                "connector_name": s.get("connector_name", ""),
                "connector_status": s.get("connector_status", "missing" if not key else ""),
                "verification_status": s.get("verification_status", "unknown"),
                "discovery_access": s.get("discovery_access", "unknown"),
                "detail_access": s.get("detail_access", "unknown"),
                "document_access": s.get("document_access", "unknown"),
                "award_access": s.get("award_access", "unknown"),
                "primary_source": s.get("authoritative", False),
                "source_status": s.get("source_status", ""),
                "migration_status": s.get("migration_status", ""),
                "replacement_source": s.get("replacement_source", ""),
                "last_verified": s.get("last_verified", ""),
                "evidence_url": s.get("evidence_url", ""),
                "priority": s.get("priority", ""),
                "gap_reason": ";".join(j["gaps"]),
                "recommended_next_action": "Identify an authoritative source."
                if not key
                else "Verify bounded anonymous live behavior.",
            }
            writer.writerow(row)
    return output.getvalue()


def render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# Nationwide SLED Coverage Audit",
        "",
        f"**Data as of:** {report['as_of']}",
        f"**Schema version:** {report['schema_version']}",
        "**Generation:** deterministic and offline (no network requests)",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    labels = [
        ("jurisdiction_count", "Primary jurisdictions"),
        ("source_count", "Sources"),
        ("implemented_connector_count", "Implemented connectors"),
        ("public_discovery_count", "Public discovery"),
        ("public_detail_count", "Public detail"),
        ("public_document_pipeline_count", "Public document pipeline"),
        ("metadata_only_count", "Metadata only"),
        ("registration_required_count", "Registration required"),
        ("login_required_count", "Login required"),
        ("subscription_required_count", "Subscription required"),
        ("payment_required_count", "Payment required"),
        ("captcha_count", "CAPTCHA blocked"),
        ("robots_policy_count", "Robots-policy blocked"),
        ("automated_access_block_count", "Automated-access blocked"),
        ("changed_markup_count", "Changed markup"),
        ("migrated_source_count", "Migrated sources"),
        ("missing_source_count", "Jurisdictions without a configured source"),
        ("unverified_source_count", "Sources without live verification"),
    ]
    lines += [f"| {label} | {s[key]} |" for key, label in labels]
    lines += [
        "",
        "### Coverage-tier distribution",
        "",
        "| Tier | Jurisdictions |",
        "|---:|---:|",
    ] + [f"| {k} | {v} |" for k, v in s["coverage_tier_distribution"].items()]
    lines += [
        "",
        "## Jurisdiction matrix",
        "",
        "| Code | Jurisdiction | Type | Tier | Sources | Gaps |",
        "|---|---|---|---:|---|---|",
    ]
    lines += [
        f"| {j['code']} | {j['name']} | {j['type']} | {j['coverage_tier']} | {', '.join(j['source_keys']) or '—'} | {', '.join(j['gaps'])} |"
        for j in report["jurisdiction_records"]
    ]
    lines += [
        "",
        "## Remaining platform-family gaps and prioritized next work",
        "",
        "| Order | Type | Jurisdictions | Sources | Proposed title |",
        "|---:|---|---|---|---|",
    ]
    lines += [
        f"| {r['recommended_order']} | {r['task_type']} | {', '.join(r['jurisdiction_ids'])} | "
        f"{', '.join(r['source_ids'])} | {r['proposed_title']} |"
        for r in report["prioritized_recommendations"]
    ]
    lines += [
        "",
        "## Methodology and limitations",
        "",
        "Tier 0 has no authoritative source; tier 1 identifies a source without executable integration; tier 2 is configured, unverified, or fixture-only; tier 3 verifies metadata discovery; tier 4 supports details and document links; tier 5 requires public document-pipeline compatibility; tier 6 additionally requires bounded live-public verification plus operational health. Changed markup and migrations downgrade coverage. Gated documents prevent full-document coverage.",
        "",
        "The denominator is 50 states, the District of Columbia, and five inhabited territories. Tribal procurement is a separate future layer. Statewide sources do not imply complete local, education, transportation, authority, or quasi-public coverage. Fixture verification is not live verification. Configured coverage is not production verification. Unknown values remain unknown. Rankings are deterministic planning aids, not proof that a connector will work.",
        "",
        "Registration, login, subscription, payment, CAPTCHA, robots-policy, and automated-access restrictions remain explicit gaps. Migrations count only when a current replacement is configured. Add evidence only from committed fixtures/documentation or a bounded public verification with its date and public evidence URL.",
        "",
    ]
    return "\n".join(lines)


def render(report: dict, format: str) -> str:
    return {"json": render_json, "csv": render_csv, "markdown": render_markdown}[format](report)


def render_capability_matrix(report: dict) -> str:
    lines = [
        "# Authoritative 56-jurisdiction capability matrix",
        "",
        "Fixture verification is not live verification. Local evidence is excluded from statewide completion.",
        "",
        "| Jurisdiction | Primary source | Family | Connector | Discovery | Details | Attachments | Pipeline | Fixture | Live | Auth | CAPTCHA | Tier | Operational | Blocker | Next action |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|---|---|---|",
    ]

    def yes(value: bool) -> str:
        return "yes" if value else "no"

    for j in report["jurisdiction_records"]:
        lines.append(
            f"| {j['name']} ({j['code']}) | {j['primary_source_name'] or '—'} | {j['platform_family'] or '—'} | {j['connector'] or '—'} | {yes(j['discovery_capable'])} | {yes(j['detail_capable'])} | {yes(j['attachment_capable'])} | {yes(j['document_pipeline_capable'])} | {yes(j['fixture_verified'])} | {yes(j['live_verified'])} | {j['authentication']} | {j['captcha']} | {j['coverage_tier']} | {j['operational_status']} | {j['blocker'] or '—'} | {j['next_action']} |"
        )
    return "\n".join(lines) + "\n"


def milestone_report(report: dict) -> dict:
    """Build the PR #50 checkpoint exclusively from committed repository evidence."""
    records = report["jurisdiction_records"]
    primary = [
        source
        for source in report["source_records"]
        if source.get("authoritative") and source.get("source_level") in STATEWIDE_SCOPES
    ]
    validations: dict[str, dict] = {}
    for path in sorted((ROOT / "reports/validation").glob("*.json")):
        try:
            rows = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            source_id = row.get("source_id")
            if source_id and (
                source_id not in validations
                or row.get("observed_at", "") > validations[source_id].get("observed_at", "")
            ):
                validations[source_id] = {**row, "evidence_report": str(path.relative_to(ROOT))}
    attempted = sorted(validations)
    blocked = {kind: [] for kind in ("authentication_required", "captcha_blocked", "network_blocked")}
    for source_id, result in validations.items():
        classifications = {
            observation.get("classification") for observation in result.get("observations", [])
        }
        for kind in blocked:
            if kind in classifications:
                blocked[kind].append(source_id)
    for rows in blocked.values():
        rows.sort()

    counts = {
        "total_jurisdictions": len(records),
        "primary_statewide_sources_identified": sum(bool(row.get("primary_source_id")) for row in records),
        "platform_families_identified": sum(bool(row.get("platform_family")) for row in records),
        "registered_statewide_profiles": sum(bool(row.get("connector")) for row in records),
        "fixture_verified_jurisdictions": sum(row["fixture_verified"] for row in records),
        "discovery_capable_jurisdictions": sum(row["discovery_capable"] for row in records),
        "detail_capable_jurisdictions": sum(row["detail_capable"] for row in records),
        "attachment_capable_jurisdictions": sum(row["attachment_capable"] for row in records),
        "document_pipeline_compatible_jurisdictions": sum(row["document_pipeline_capable"] for row in records),
        "live_verified_jurisdictions": sum(row["live_verified"] for row in records),
        "production_monitored_jurisdictions": sum(row.get("operational_status") == "production_monitored" for row in records),
        "network_blocked_validation_sources": len(blocked["network_blocked"]),
        "authentication_required_validation_sources": len(blocked["authentication_required"]),
        "captcha_blocked_validation_sources": len(blocked["captcha_blocked"]),
        "tier_0_jurisdictions": sum(row["coverage_tier"] == 0 for row in records),
        "jurisdictions_lacking_primary_source": sum(not row.get("primary_source_id") for row in records),
    }
    queue = closeout_plan(report)
    unattempted = [task for task in queue["validation_tasks"] if task["source_id"] not in attempted]
    connector_work = [task for task in report["prioritized_recommendations"] if task["task_type"] != "live_validation"]
    matrix = [
        {
            "jurisdiction_id": row["code"], "primary_source_id": row.get("primary_source_id"),
            "discovery": row["discovery_capable"], "detail": row["detail_capable"],
            "attachments": row["attachment_capable"], "document_pipeline": row["document_pipeline_capable"],
        }
        for row in records
    ]
    return {
        "schema_version": "1.0", "as_of": report["as_of"],
        "executive_summary": "Fixture breadth is closed; bounded first-pass production validation remains in progress.",
        "coverage_totals": counts,
        "jurisdictions_by_tier": {
            str(tier_number): [row["code"] for row in records if row["coverage_tier"] == tier_number]
            for tier_number in range(7)
        },
        "primary_statewide_source_inventory": [source["key"] for source in primary],
        "connector_family_inventory": report["summary"]["connector_family_counts"],
        "platform_reuse_by_jurisdiction": {row["code"]: row["platform_family"] for row in records if row["platform_family"]},
        "fixture_verified_sources": [row["primary_source_id"] for row in records if row["fixture_verified"]],
        "live_verified_sources": [row["primary_source_id"] for row in records if row["live_verified"]],
        "production_monitored_sources": [row["primary_source_id"] for row in records if row.get("operational_status") == "production_monitored"],
        "capability_matrix": matrix,
        "validation_blockers": blocked,
        "manual_evidence_capture_sources": [task["source_ids"][0] for task in connector_work],
        "remaining_tier_0_jurisdictions": [row["code"] for row in records if row["coverage_tier"] == 0],
        "remaining_connector_profile_work": connector_work,
        "remaining_document_adapter_work": [row["code"] for row in records if row["attachment_capable"] and not row["document_pipeline_capable"]],
        "ordered_live_validation_queue": unattempted,
        "validation_attempt_evidence": [validations[key] for key in sorted(validations)],
        "estimated_prs_remaining_fixture_breadth": 0 if queue["breadth_complete"] else math.ceil(len(connector_work) / 2),
        "estimated_prs_remaining_first_pass_validation": math.ceil(len(unattempted) / 3),
        "definition_of_done": {
            "all_primary_sources_identified": counts["primary_statewide_sources_identified"] == counts["total_jurisdictions"],
            "all_platforms_classified": counts["platform_families_identified"] == counts["total_jurisdictions"],
            "all_connector_profiles_registered": counts["registered_statewide_profiles"] == counts["total_jurisdictions"],
            "all_fixture_verified_discovery": counts["discovery_capable_jurisdictions"] == counts["total_jurisdictions"],
            "all_detail_capable": counts["detail_capable_jurisdictions"] == counts["total_jurisdictions"],
            "all_attachment_capable": counts["attachment_capable_jurisdictions"] == counts["total_jurisdictions"],
            "all_document_pipeline_compatible": counts["document_pipeline_compatible_jurisdictions"] == counts["total_jurisdictions"],
            "all_live_verified": counts["live_verified_jurisdictions"] == counts["total_jurisdictions"],
            "any_production_monitored": counts["production_monitored_jurisdictions"] > 0,
        },
    }


def render_milestone_markdown(milestone: dict) -> str:
    counts = milestone["coverage_totals"]
    lines = ["# PR #50 authoritative 56-jurisdiction milestone", "", milestone["executive_summary"], "", "## Coverage totals", ""]
    lines.extend(f"- **{key.replace('_', ' ')}:** {value}" for key, value in counts.items())
    lines.extend(["", "## Definition of done", ""])
    lines.extend(f"- **{key.replace('_', ' ')}:** {'yes' if value else 'no'}" for key, value in milestone["definition_of_done"].items())
    lines.extend(["", "## Validation blockers observed in committed evidence", ""])
    for kind, source_ids in milestone["validation_blockers"].items():
        lines.append(f"- **{kind.replace('_', ' ')}:** {', '.join(f'`{value}`' for value in source_ids) or 'None'}")
    lines.extend(["", "## Remaining work", "", f"- Fixture-breadth PRs: {milestone['estimated_prs_remaining_fixture_breadth']}", f"- First-pass validation PRs (three sources per PR): {milestone['estimated_prs_remaining_first_pass_validation']}"])
    return "\n".join(lines) + "\n"


def generated_reports(report: dict) -> dict[str, str]:
    missing = [j for j in report["jurisdiction_records"] if not j.get("primary_source_id")]
    blocked = [s for s in report["source_records"] if s.get("blocker_reason")]
    pipeline = [j for j in report["jurisdiction_records"] if j["document_pipeline_capable"]]
    families = report["summary"]["connector_family_counts"]
    queue = report["prioritized_recommendations"]
    closeout = closeout_plan(report)

    def md_list(title: str, rows: list[str]) -> str:
        return "# " + title + "\n\n" + ("\n".join(rows) if rows else "None.") + "\n"

    milestone = milestone_report(report)
    return {
        "coverage-summary.json": render_json(report),
        "capability-matrix.md": render_capability_matrix(report),
        "connector-family-reuse.md": md_list(
            "Connector-family reuse",
            [f"- `{k}`: {v} primary statewide jurisdiction(s)" for k, v in families.items()],
        ),
        "missing-coverage.md": md_list(
            "Missing primary statewide coverage",
            [f"- {j['name']} ({j['code']}): {j['next_action']}" for j in missing],
        ),
        "blocked-sources.md": md_list(
            "Blocked sources", [f"- `{s['key']}`: {s['blocker_reason']}" for s in blocked]
        ),
        "document-pipeline-readiness.md": md_list(
            "Document-pipeline ready jurisdictions",
            [f"- {j['name']} ({j['code']}): `{j['primary_source_id']}`" for j in pipeline],
        ),
        "next-pr-queue.json": json.dumps(queue, indent=2, sort_keys=True) + "\n",
        "live-validation-tasks.json": json.dumps(
            closeout["validation_tasks"], indent=2, sort_keys=True
        )
        + "\n",
        "breadth-closeout.json": json.dumps(closeout, indent=2, sort_keys=True) + "\n",
        "manual-capture-instructions.md": md_list(
            "Manual capture instructions",
            [
                "Fixture verification is not live verification. Never log in, register, solve CAPTCHA, submit a bid, or retain credentials/cookies.",
                "For each task in `live-validation-tasks.json`, open only the registered entry URL, use the allowed method policy, and stop at any access control.",
                "Record UTC time, final URL and redirects, status/content type, a bounded result, stable ID, public detail response, and attachment metadata without downloading during discovery.",
                "Sanitize personal data, tokens, cookies, authorization headers, and vendor data before committing evidence.",
                "Record login, CAPTCHA, rate-limit/Retry-After, robots, proxy, and network blockers exactly; never infer success through a blocker.",
                "Promote to live verification only when the dated anonymous response matches the registered contract; require separate recurring evidence for production monitoring.",
            ],
        ),
        "pr50-milestone.json": json.dumps(milestone, indent=2, sort_keys=True) + "\n",
        "pr50-milestone.md": render_milestone_markdown(milestone),
    }


def write_generated_reports(directory: Path | None = None) -> None:
    directory = directory or ROOT / "reports/coverage"
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in generated_reports(build_report()).items():
        (directory / name).write_text(content)


def report_drift(directory: Path | None = None) -> list[str]:
    directory = directory or ROOT / "reports/coverage"
    return [
        name
        for name, content in generated_reports(build_report()).items()
        if not (directory / name).is_file() or (directory / name).read_text() != content
    ]
