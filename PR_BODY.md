## Motivation
DemandStar is now named Euna OpenBids, while legacy DemandStar URLs and agency workflows remain in use. The aggregator needs a stable, reusable connector identity for this product without conflating it with Euna Bonfire or IonWave.

## Description
Adds the canonical `euna/openbids-demandstar` connector, explicit non-ambiguous aliases, configurable agency profiles, tenant-qualified UUID-safe identities, semantic HTML/embedded-JSON parsing, provenance, and access-aware document candidates.

## Platform and access boundaries
The connector is anonymous, public-read-only, and GET-only. Public metadata remains available downstream when individual documents are registration-, login-, subscription-, or payment-gated. It never registers, authenticates, pays, purchases subscriptions, submits bids, acknowledges addenda, joins planholder lists, bypasses CAPTCHA or other controls, or retrieves private supplier responses.

## Discovery and detail behavior
Discovery has configurable and hard-bounded page sizes, page/result ceilings, duplicate page and opportunity suppression, stable ordering, local filters, malformed-shape detection, and optional public detail enrichment. Original upstream IDs are preserved and canonical identities include the profile key.

## Document pipeline integration
Public solicitation packages, addenda, Q&A, tabulations, and awards become deduplicated `DocumentCandidate` records for the existing manifest, safe downloader, parser, targeted OCR, structured extraction, and version reconciliation pipeline. Gated candidates retain access metadata but are not anonymously retrievable, making incomplete document coverage visible.

## Resilience and safety
Profiles validate explicit DemandStar and official-document host allowlists. HTTPS-only URL validation rejects private/reserved addresses and unapproved hosts. Requests use bounded timeouts, transient retries (429/502/503/504), exponential backoff, jitter, Retry-After, per-profile failure state, circuit breaking, cooldown, and recovery.

## Migration handling
Active, legacy, migrated, configured-unverified, and unavailable profile states retain historical provenance. Migrated/legacy profiles are not crawled as current DemandStar sources and may record replacement platform metadata without registering that replacement under this family.

## Verification status
Behavior is `fixture_verified` against small sanitized Euna OpenBids/DemandStar fixtures. Fixture tests demonstrate parser and connector behavior against captured inputs; they do not prove every live agency or endpoint remains anonymously accessible. No live checks were performed.

## Testing
- `PYTHONPATH=src python -m unittest discover -s tests -v` (185 tests)
- `PYTHONPATH=src python -m compileall -q src tests`
- `ruff check .`
- `ruff format --check` on task files
- `git diff --check`

## Known limitations
Anonymous metadata and file availability vary by agency. The connector fails closed on unsupported markup and does not use authenticated dashboards, premium nationwide search, browser automation, or unbounded agency enumeration. Payment-, subscription-, registration-, and login-gated files remain metadata only.

## Codex Cloud publication notes
No fetch, pull, push, `gh`, remote mutation, authentication, or live portal request was used. This local commit is ready for inspection and publication through the Codex Cloud **Create PR** button.
