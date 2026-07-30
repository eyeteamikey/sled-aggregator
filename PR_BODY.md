## Motivation

Coverage claims need an auditable control plane that distinguishes known portals, executable
connectors, fixture evidence, current live behavior, metadata, documents, and access restrictions.

## Description

Adds strict versioned jurisdiction/source registries, repository-derived connector inventory,
deterministic tier and gap analysis, transparent recommendations, an offline CLI, JSON/CSV/Markdown
reports, documentation, and regression tests. No procurement connector is added.

## Jurisdiction scope

The audit covers 50 states, D.C., and five inhabited territories (56 primary jurisdictions). Tribal
procurement is a separate future layer and is not included in this denominator.

## Coverage schema

Schema 1.0 validates canonical jurisdiction counts and uniqueness, strict vocabularies, connector
joins, migration relationships, verification evidence, safe public URLs, and contradictory states.
Unknown fields and unsupported future schema versions fail clearly.

## Connector inventory

The inventory groups the authoritative runtime connector registry by implementation class, deriving
canonical names and aliases rather than duplicating them. It joins source profiles and reports
capabilities, fixtures, tests, orphaned implementations, and public-read-only policy.

## Coverage tiers

Deterministic tiers preserve the semantic progression from no known authoritative source (0), through
identified/configured/metadata/detail/document-pipeline coverage, to bounded production verification
(6). Fixture-only profiles remain tier 2. Gating, changed markup, and migration prevent inflated tiers.

## Gap analysis

Jurisdictions retain multiple simultaneous gaps across missing sources/connectors/profiles/fixtures,
live verification, blocked discovery/detail, gated or unavailable documents, CAPTCHA, robots,
automation, migration, local/education/transportation/award depth, and territories.

## Prioritization

Recommendations expose impact, anonymous access, documents, reuse, complexity, maintenance,
blocking, authority, and territory factors plus deterministic scores and stable tie-breaking. Initial
rankings are deterministic planning aids, not proof that a connector will work.

## Generated reports

Committed application JSON, flat one-row-per-jurisdiction-source CSV, and review-oriented Markdown
are generated with the declared 2026-07-30 as-of date and stable ordering.

## Verification methodology

The audit does not perform network requests by default and never requires credentials. A configured
source is not necessarily live-verified. Fixture verification is not live verification. Metadata-only
coverage is not document-pipeline coverage. Registration-, login-, subscription-, payment-, CAPTCHA-,
and robots-gated sources remain gaps.

## Testing

- `PYTHONPATH=src python -m unittest discover -s tests -v` (245 tests)
- `PYTHONPATH=src python -m compileall src tests`
- `ruff check .`
- `ruff format --check` for changed Python files
- `PYTHONPATH=src python -m sled_aggregator.coverage validate`
- two report generations with matching SHA-256 manifests
- `git diff --check`

The repository-wide `ruff format --check .` continues to identify eight pre-existing files that are
not formatted; this PR deliberately does not reformat unrelated work. All changed Python files pass.

## Initial findings

The runtime registry contains 19 implemented connector families. The conservative seed has 7 source
profiles across 7 jurisdictions, all fixture-verified and none live-verified. Six jurisdictions are
tier 2; fifty remain tier 0 because Rhode Island's sole seeded source is supplemental rather than an
authoritative statewide source. There is no claimed tier 5/6 production coverage.

## Known limitations

This initial audit seeds only claims directly demonstrated by committed profiles, fixtures, and
documentation. It intentionally leaves unknown or missing data unknown. Statewide sources do not
prove local, education, transportation, authority, or quasi-public depth. Tenant markup, public
access, documents, and migrations may change.

## Codex Cloud publication notes

No fetch, pull, push, GitHub authentication, shell PR command, or remote modification was used. The
PR is ready for publication through the Codex Cloud Create PR button.
