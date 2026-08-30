"""Deterministic tenant-level validation metrics derived from the coverage registry."""

from __future__ import annotations

import json
from collections import Counter

from sled_aggregator.connectors.registry import connector_registry

from .core import ROOT, SOURCES_PATH, load

CORE_SLED_ORGANIZATIONS = 103_947
METRICS_PATH = ROOT / "data/coverage/sled_validation_metrics.json"
REPORT_PATH = ROOT / "docs/coverage/sled_validation_metrics.md"
NEXT_WAVE_PATH = ROOT / "data/coverage/next_validation_wave.json"
EVIDENCE_TIERS = (
    "production_monitored",
    "scheduled_live_verified",
    "live_public_verified",
    "public_metadata_only",
    "official_link_verified",
    "fixture_verified",
    "configured_unverified",
    "blocked",
    "not_researched",
)
CAPABILITIES = (
    "listing_discovery",
    "keyword_search",
    "filters",
    "sorting",
    "pagination",
    "opportunity_details",
    "public_contacts",
    "amendments_addenda",
    "public_q_and_a",
    "awards",
    "vendors_bidders_awardees",
    "attachment_metadata",
    "anonymous_document_download",
    "document_text_extraction",
    "OCR_when_required",
)
BUYER_CLASSES = (
    "county",
    "municipality",
    "K–12",
    "higher education",
    "special district",
    "housing",
    "transit",
    "port",
    "airport",
    "tribal",
    "regional",
    "cooperative",
)


def derive_metrics(sdata: dict | None = None) -> dict:
    data = sdata or load(SOURCES_PATH)
    sources = data["sources"]
    tenant_ids = {row["tenant_id"] for row in sources if row.get("connector_name")}
    platform_families = {row["platform_family"] for row in sources if row.get("platform_family")}
    tenants_by_family: dict[str, set[str]] = {}
    for row in sources:
        if row.get("connector_name"):
            tenants_by_family.setdefault(row["connector_name"], set()).add(row["tenant_id"])
    tier_counts = Counter(row["evidence_tier"] for row in sources)
    cap_counts = {
        capability: dict(
            sorted(Counter(row["capabilities"][capability] for row in sources).items())
        )
        for capability in CAPABILITIES
    }
    live_listing = sum(
        row["capabilities"]["listing_discovery"] == "live_verified" for row in sources
    )
    detail = sum(
        row["capabilities"]["opportunity_details"] in {"live_verified", "metadata_only"}
        for row in sources
    )
    attachment = sum(
        row["capabilities"]["attachment_metadata"] == "live_verified" for row in sources
    )
    downloads = sum(
        row["capabilities"]["anonymous_document_download"] == "live_verified" for row in sources
    )
    extraction = sum(
        row["capabilities"]["document_text_extraction"] in {"live_verified", "fixture_verified"}
        for row in sources
    )
    discovered_entities = len({row["owning_public_entity"] for row in sources})
    normalized_tenants = len(tenant_ids)
    official_evidence = sum(
        bool(row.get("evidence_url") or row.get("official_landing_page"))
        for row in sources
        if row.get("connector_name")
    )
    scheduled = tier_counts["production_monitored"] + tier_counts["scheduled_live_verified"]

    def stage(name: str, completed: int, denominator: int, meaning: str) -> dict:
        return {
            "stage": name,
            "completed": completed,
            "remaining": denominator - completed,
            "percentage": round(completed * 100 / denominator, 4) if denominator else 0.0,
            "denominator": denominator,
            "meaning": meaning,
        }

    stages = [
        stage(
            "core_potential_portal_owners",
            CORE_SLED_ORGANIZATIONS,
            CORE_SLED_ORGANIZATIONS,
            "Fixed universe of potential portal-owning core SLED organizations; not a validation claim.",
        ),
        stage(
            "official_source_discovered",
            discovered_entities,
            CORE_SLED_ORGANIZATIONS,
            "Entities with an official procurement source recorded, measured against the core universe.",
        ),
        stage(
            "normalized_portal_tenant",
            normalized_tenants,
            discovered_entities,
            "Connector-backed unique tenants among entities with a discovered source.",
        ),
        stage(
            "official_link_evidence",
            official_evidence,
            normalized_tenants,
            "Normalized tenants with an official government starting link recorded.",
        ),
        stage(
            "live_listing_validation",
            live_listing,
            normalized_tenants,
            "Normalized tenants with point-in-time anonymous listing evidence.",
        ),
        stage(
            "detail_validation",
            detail,
            normalized_tenants,
            "Normalized tenants with live full-detail or explicitly metadata-only detail evidence.",
        ),
        stage(
            "document_validation",
            downloads,
            normalized_tenants,
            "Normalized tenants with an anonymously downloaded representative document; metadata alone does not qualify.",
        ),
        stage(
            "scheduled_production_monitoring",
            scheduled,
            normalized_tenants,
            "Normalized tenants with scheduled-live or production-monitoring evidence.",
        ),
    ]
    next_wave = load(NEXT_WAVE_PATH)["targets"]
    return {
        "schema_version": "1.0",
        "as_of": data["as_of"],
        "core_sled_potential_portal_owners": CORE_SLED_ORGANIZATIONS,
        "counts": {
            "registered_source_records": len(sources),
            "unique_portal_tenants": normalized_tenants,
            "unique_platform_families": len(platform_families),
            "connector_families_implemented": len(connector_registry.inventory()),
            "connector_families_with_two_independent_tenants": sum(
                len(v) >= 2 for v in tenants_by_family.values()
            ),
            "public_anonymous_listings_verified": live_listing,
            "details_verified": detail,
            "attachment_metadata_verified": attachment,
            "anonymous_document_downloads_verified": downloads,
            "document_extraction_pipeline_verified": extraction,
            "captcha_or_waf_blocked_tenants": sum(
                any(v == "blocked" for v in row["capabilities"].values()) for row in sources
            ),
            "login_or_registration_gated_tenants": sum(
                row.get("document_access") in {"registration_required", "login_required"}
                or row.get("discovery_access") == "gated"
                for row in sources
            ),
        },
        "evidence_tier_distribution": {tier: tier_counts[tier] for tier in EVIDENCE_TIERS},
        "capability_distribution": cap_counts,
        "buyer_class_distribution": {
            kind: sum(row["buyer_class"] == kind for row in sources) for kind in BUYER_CLASSES
        },
        "coverage_funnel": stages,
        "next_wave_target_count": len(next_wave),
        "derivation": {
            "source_registry": "data/coverage/sources.json",
            "next_wave": "data/coverage/next_validation_wave.json",
            "generator": "sled_aggregator.coverage.validation_metrics",
        },
    }


def render_markdown(metrics: dict) -> str:
    c = metrics["counts"]
    lines = [
        "# SLED validation reconciliation",
        "",
        f"As of **{metrics['as_of']}**. All counts are derived offline from `data/coverage/sources.json`; fixture evidence is never promoted to live evidence.",
        "",
        "## Current metrics",
        "",
    ]
    lines += [
        f"- Registered source records: **{c['registered_source_records']}**",
        f"- Unique normalized portal tenants: **{c['unique_portal_tenants']}**",
        f"- Unique platform families: **{c['unique_platform_families']}**",
        f"- Implemented connector families: **{c['connector_families_implemented']}**",
        f"- Connector families represented by two independent tenants: **{c['connector_families_with_two_independent_tenants']}**",
        "",
        "## Coverage funnel",
        "",
        "| Stage | Completed | Remaining | Percentage | Denominator | Meaning |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in metrics["coverage_funnel"]:
        lines.append(
            f"| `{row['stage']}` | {row['completed']:,} | {row['remaining']:,} | {row['percentage']:.4f}% | {row['denominator']:,} | {row['meaning']} |"
        )
    lines += [
        "",
        "Percentages are stage-specific. In particular, the 103,947 organization universe is used only where stated; tenant-validation percentages use normalized tenants and never imply percent of all SLED complete.",
        "",
        "## Evidence tiers",
        "",
        "| Evidence tier | Tenants/records |",
        "| --- | ---: |",
    ]
    lines += [f"| `{k}` | {v} |" for k, v in metrics["evidence_tier_distribution"].items()]
    lines += [
        "",
        "## Capability outcomes",
        "",
        f"- Anonymous listings live-verified: **{c['public_anonymous_listings_verified']}**",
        f"- Details live-verified or explicitly metadata-only: **{c['details_verified']}**",
        f"- Attachment metadata live-verified: **{c['attachment_metadata_verified']}**",
        f"- Anonymous representative downloads verified: **{c['anonymous_document_downloads_verified']}**",
        f"- Document extraction pipeline fixture/live verified: **{c['document_extraction_pipeline_verified']}**",
        f"- CAPTCHA/WAF-blocked tenants: **{c['captcha_or_waf_blocked_tenants']}**",
        f"- Login/registration-gated tenants: **{c['login_or_registration_gated_tenants']}**",
        "",
        "The complete per-capability status distribution is in `data/coverage/sled_validation_metrics.json`. A visible tab, attachment name, or fixture parser does not count as an anonymous download.",
        "",
        "## Buyer classes",
        "",
        "| Buyer class | Records |",
        "| --- | ---: |",
    ]
    lines += [f"| {k} | {v} |" for k, v in metrics["buyer_class_distribution"].items()]
    lines += [
        "",
        "## Reconciled wave boundary",
        "",
        "Public Purchase, DemandStar/OpenBids, CGI Advantage/VSS, BidNet Direct, Euna Bonfire, and PlanetBids now have two tenant records apiece. Their point-in-time evidence remains tenant-specific. No family is classified as scheduled-live or production-monitored. Public Purchase details/documents are gated; Bonfire details were WAF-blocked; CGI stateful actions and PlanetBids background requests still need desktop HAR capture; BidNet and DemandStar documents require registration.",
        "",
        "## Next wave",
        "",
        f"The machine-readable plan contains **{metrics['next_wave_target_count']}** targets: six deepening tasks and four new-family or materially distinct validation tasks. See `data/coverage/next_validation_wave.json`.",
        "",
    ]
    return "\n".join(lines)


def write_metrics() -> dict:
    metrics = derive_metrics()
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    REPORT_PATH.write_text(render_markdown(metrics))
    return metrics
