# Coverage registry guide

## Purpose and scope

The versioned JSON registries under `data/coverage/` are the machine-readable source of truth for
the offline audit. The primary denominator is 50 states, D.C., and the five inhabited territories
(American Samoa, Guam, Northern Mariana Islands, Puerto Rico, and U.S. Virgin Islands). Tribes are a
separate future layer because tribal sovereignty and procurement sources cannot be modeled as state
subdivisions. Schema `1.0` rejects unsupported versions, unknown source fields, invalid vocabulary,
unsafe URLs, broken relationships, and unsupported live claims; future incompatible changes require
a documented version and migration.

## Vocabulary

Source levels are statewide, state agency, local, county, municipality, education, transportation,
authority, quasi-public, territory-wide, supplemental, and archive. Roles are primary,
supplemental, document host, award source, archive, external notice, replacement, and legacy.

Connector status means:

- `implemented`: executable code and canonical registry integration exist.
- `partially_implemented`: only some declared behavior is executable.
- `configured` / `configured_unverified`: a profile exists without verified behavior.
- `fixture_only`: executable behavior is demonstrated only by committed captures.
- `missing` / `unsupported`: no connector exists or the family is outside current support.
- `deprecated`, `migrated`, and `intentionally_excluded`: non-current or deliberately excluded.

Primary verification statuses distinguish `fixture_verified`, `live_public_verified`,
`configured_unverified`, `public_metadata_only`, registration/enrollment/login/subscription/payment
requirements, CAPTCHA/robots/automation blocks, changed markup, migration, legacy, blocked,
unavailable, and unknown. Discovery, detail, document, and award access are independent. Unknown is
not treated as false. Fixture evidence never becomes live evidence.

## Tiers and gaps

Tiers 0–6 mean no source; identified source; configured/fixture-only; verified metadata discovery;
details and document links; compatible public document pipeline; and bounded live-production
verification with health/scheduling/failure reporting. Document gating caps coverage below tier 5;
changed markup and migration downgrade it. The report retains simultaneous source, connector,
fixture, live-verification, discovery, detail, document, CAPTCHA, robots, automation, migration,
local, education, transportation, award, and territory gaps.

A statewide portal can cover several levels only when `covers_levels` says so. It never silently
establishes local depth. Metadata-only or gated documents are not full-document coverage. A legacy
source does not count as current without a configured replacement.

## Connector inventory and prioritization

The audit groups the authoritative runtime `connector_registry` by connector class. Canonical name,
aliases, module, jurisdictions, and read-only policy therefore are not manually duplicated. Coverage
profiles are joined by canonical connector name; fixture/test references and access-derived
capabilities are added deterministically. Zero-profile connectors remain visible as orphans.

Recommendations expose every integer factor: jurisdictions unlocked, statewide impact, anonymous
access, documents, reuse, complexity, maintenance risk, blocking, and territory impact. Scores and
family-name tie breaks are deterministic. Bands are planning aids, not evidence that a connector or
tenant works; blocked and unstable sources require research rather than bypasses.

## Maintenance and CLI

Add a jurisdiction only through a schema migration (the primary denominator is fixed at 56). To add
or update a source, use a stable key and canonical jurisdiction/connector names, record each access
surface honestly, include an official URL for authoritative sources, and add committed fixtures for
`fixture_verified`. A live claim additionally requires a verification date and public evidence URL.
Never add credentials, cookies, private hosts, or private endpoints.

```bash
PYTHONPATH=src python -m sled_aggregator.coverage validate
PYTHONPATH=src python -m sled_aggregator.coverage report --format markdown --output /tmp/audit.md
PYTHONPATH=src python -m sled_aggregator.coverage gaps
PYTHONPATH=src python -m sled_aggregator.coverage recommend
```

These commands never make network calls. Regenerate all committed formats with the explicit
`--as-of` date shown in the README, then run them a second time and confirm `git diff` is unchanged.
