## Motivation
Add a reusable public, read-only connector for agency-specific Euna Procurement portals powered by Bonfire without crossing supplier-account boundaries.

## Bonfire and Euna platform relationship
Canonical family: `euna/bonfire`. Aliases: `bonfire`, `bonfirehub`, `euna-bonfire`, `euna/bonfire` (canonical lookup), `euna-procurement-bonfire`, `bonfire-interactive`, and `euna-procurement`. Bare `euna` is intentionally absent because IonWave, DemandStar, EqualLevel, and other Euna products are distinct parser families. Bonfire is transitioning to Euna Supplier Network branding while agency portals may continue on `bonfirehub.com`.

## Supported presets
| Key / host | Entity / jurisdiction | Verification | Platform / branding |
|---|---|---|---|
| `anacorteswa` / `anacortes.bonfirehub.com` | city / Anacortes, WA | fixture_verified | bonfire_current / legacy_bonfire |
| `bendoregon` / `bendoregon.bonfirehub.com` | city / Bend, OR | fixture_verified | bonfire_current / legacy_bonfire |
| `fairfaxcounty` / `fairfaxcounty.bonfirehub.com` | county / Fairfax County, VA | fixture_verified | public_upstream_fallback / legacy_bonfire |
| `fcps` / `fcps.bonfirehub.com` | school district / Fairfax County, VA | fixture_verified | euna_branded_bonfire / euna_procurement |
| `cnusdk12` / `cnusdk12.bonfirehub.com` | school district / Riverside County, CA | fixture_verified | bonfire_current / legacy_bonfire |
| `fsd1` / `fsd1.bonfirehub.com` | school district / Florence County, SC | fixture_verified | bonfire_current / legacy_bonfire |
| `region10` / `region10.bonfirehub.com` | cooperative purchasing organization / Texas | fixture_verified | bonfire_current / legacy_bonfire |
| `charlottenc` / `charlottenc.bonfirehub.com` | city / Charlotte, NC | registration_required | registration_required_portal / legacy_bonfire |
| `fixture-only` / `fixture-public.bonfirehub.com` | other public entity / Test Territory | fixture_verified, non-production | bonfire_current / legacy_bonfire |

## Platform variants
Models `bonfire_legacy`, `bonfire_current`, `euna_branded_bonfire`, `euna_supplier_network_redirect`, `public_upstream_fallback`, `registration_required_portal`, and `configured_unknown`, independently of branding and verification/access state.

## Public-access boundaries
Anonymous GET only. No account or supplier login was used; no CAPTCHA or registration was bypassed; no questions or responses were submitted. Public plan-holder/follower collection is disabled. JavaScript shells, login/registration pages, CAPTCHA/bot challenges, maintenance, malformed payloads, tenant removal, and migration do not become false empty results.

## Discovery
Fixture-tested shapes are `/`, `/portal/?tab=openOpportunities`, `/opportunities/{id}`, semantic server-rendered HTML, explicit public JSON, empty listings, login/registration/CAPTCHA/maintenance pages, and document links. Discovery is page/result bounded, duplicate suppressing, and supports project ID, solicitation number, keyword/title, status, department, and date filters. Current preset filtering is local rather than a guessed private remote API.

## Detail enrichment
Extracts opportunity ID, project/solicitation number, title, description/summary, organization, department, solicitation type, status, release/open/question/close dates, timezone configuration, pre-bid metadata, estimated value, codes/categories, contacts, authoritative upstream/direct URLs, public payload, and per-field provenance when present. Missing fields are not manufactured.

## Documents
Discovers solicitation packages (RFP/RFQ/IFB/ITB/RFI), specifications/SOW/PWS, pricing and bid forms, response templates, plans/drawings, exhibits/appendices, addenda/amendments, Q&A, pre-bid material, attendee/insurance/bonding forms, award/intent notices, tabulations, contracts, and cancellation notices through the canonical `DocumentCandidate` contract. Access is per resource: public candidates are retrievable; metadata-only, login-, registration-, and CAPTCHA-gated candidates remain non-retrievable metadata.

## Addenda
Public addendum/amendment metadata, number, dates, URL, access state, and related files are categorized for shared `addendum_to`, `amendment_to`, `replaces`, and `supplement` reconciliation rather than reconciled in the connector.

## Questions and answers
Public Q&A metadata and files are discoverable when anonymous. The connector never submits questions or accesses authenticated discussions; shared PR #15 logic decides effective-fact impact.

## Awards
Public award/intent notices and bid tabulations are categorized. No sealed responses, evaluation records, private scorecards, or supplier data are requested.

## Registration-required content
Visible restricted filenames are retained with `registration_required`/`public_metadata_only`, `publicly_retrievable=false`, and the referring opportunity URL, and are not retrieval queued. Submission login does not make otherwise public project metadata private.

## Upstream fallbacks
Only explicitly configured authoritative agency pages are eligible. Fairfax County configures its solicitation page and retains both URLs/provenance; arbitrary agency crawling, aggregators, and search pages are excluded.

## Portal migration handling
Classifies Euna Supplier Network destinations separately and validates every redirect against exact configured hosts. It does not silently enter a centralized authenticated dashboard.

## Pipeline integration
The connector emits normalized opportunities plus candidate/access/provenance metadata. Existing services persist opportunities, upsert manifest candidates, queue only eligible public documents, safely download, parse/native-text-or-targeted-OCR, extract evidence, reconcile addenda, preserve historical facts, update effective snapshots, and write the change ledger. No connector-specific downloader, parser database, or migration was added.

## Resilience and SSRF safety
Bounded exponential retry/jitter supports numeric and HTTP-date Retry-After and 408/425/429/500/502/503/504. Per-tenant connector instances isolate cookies and circuit state, own only clients they create, and expose health snapshots. Exact tenant/allowlisted hosts, HTTPS, safe ports, and global address checks reject deceptive hosts, credentials, localhost/private/link-local/metadata addresses, dangerous schemes, unsafe redirects, and guessed storage URLs.

## Registry and documentation
Production registration preserves all prior connectors. README and architecture docs cover identity, presets, variants, access boundaries, discovery, documents, migration, resilience, pipeline separation, tenant extension, and follow-up PR #18 (IonWave).

## Testing
171 unittest cases passed repository-wide; 5 Bonfire test methods exercise the fixture-backed behavior in grouped scenarios. Exact commands:
- `PYTHONPATH=src python -m unittest discover -s tests -v`
- `PYTHONPATH=src python -m unittest tests.test_connector_registry tests.test_euna_bonfire_connector tests.test_document_pipeline tests.test_document_extraction tests.test_solicitation_intelligence -v`
- `PYTHONPATH=src python -m compileall -q src tests`
- `pyright src/sled_aggregator/connectors/euna_bonfire.py tests/test_euna_bonfire_connector.py`
- `pyright src tests/test_euna_bonfire_connector.py` (repository baseline has 48 errors and 1 missing-optional-dependency warning outside this connector, plus the connector URL typing issue subsequently corrected)
- `ruff check .`
- `git diff --check`
- `git status --short --branch`

## Live verification
Two bounded anonymous GET smoke attempts (Anacortes and Bend) were blocked by the environment CONNECT proxy with HTTP 403 before reaching either portal. Therefore no preset is marked `live_public_verified`; no attachment body was requested. Fixture verification is not live production proof.

## Known limitations
Public markup may differ by tenant; no protected or invented API is used. Central Supplier Network routes are not interchangeable with agency portals. Registration policy varies, metadata visibility does not prove file access, and one tenant is not statewide coverage.

## Follow-up work
SLED Connector PR #18: Euna Procurement/IonWave. Later: DemandStar, PlanetBids, BidNet Direct, Public Purchase, SAP Ariba, Workday Strategic Sourcing, remaining state systems, live validation harness, markup-change detection, preset expansion, scheduled runs, and capability-profile matching.
