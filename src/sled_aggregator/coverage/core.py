"""Deterministic, offline SLED coverage audit."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sled_aggregator.connectors.registry import connector_registry

SCHEMA_VERSION = "1.0"
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
    canonical = {x["canonical_name"] for x in connector_registry.inventory()}
    keys: set[str] = set()
    sources = sdata.get("sources", [])
    all_keys = {s.get("key") for s in sources}
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
                "document_pipeline_compatible": any(
                    s["document_access"] == "public" for s in profiles
                ),
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
                "score": score,
                "priority_band": band,
                "factors": factors,
                "recommended_next_action": item["recommendation"],
            }
        )
    return sorted(rows, key=lambda x: (-x["score"], x["family"]))


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
        value, gaps = tier(linked, inventory), gaps_for(jurisdiction, linked)
        records.append(
            {
                **jurisdiction,
                "coverage_tier": value,
                "source_keys": [s["key"] for s in linked],
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

    summary = {
        "jurisdiction_count": len(records),
        "source_count": len(sources),
        "implemented_connector_count": len(inventory_rows),
        "coverage_tier_distribution": distribution,
        "public_discovery_count": count("discovery_access", {"public"}),
        "public_detail_count": count("detail_access", {"public"}),
        "public_document_pipeline_count": sum(j["coverage_tier"] >= 5 for j in records),
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
        "prioritized_recommendations": recommendations(sdata.get("family_hypotheses", [])),
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
        "| Band | Score | Family | Factors | Next action |",
        "|---|---:|---|---|---|",
    ]
    lines += [
        f"| {r['priority_band']} | {r['score']} | {r['family']} | "
        + ", ".join(f"{k}={v}" for k, v in r["factors"].items())
        + f" | {r['recommended_next_action']} |"
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
