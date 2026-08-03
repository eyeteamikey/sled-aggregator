# PR #41 selection: Iowa IMPACS and Utah U3P JAGGAER profiles

## Merge and selection gate

PR #40 is present as merge commit `8c4c4ae` and substantive commit `6fe906a`.
Its Maine CGI Advantage VSS profile, fixtures, connector tests, authoritative
registry entry, selection report, generated reports, and updated queue are
present. Maine is baseline-operational and no longer appears as incomplete.
This change does not recreate PR #40.

The pre-change generated queue ranks seven fixture-operational sources awaiting
live validation at score 50. This PR is a breadth-first implementation tranche,
so those validation-only tasks are excluded. The implementation selection is
breadth rank 1 with a documented selection score of 90: 40 points for two
primary statewide gaps, 25 for reuse of one implemented connector, 15 for
explicit enabled tenant profiles and deterministic GET routes, and 10 for
committed shared-family fixtures. No higher-value multi-jurisdiction existing
profile tranche has equivalent repository evidence.

## Selection report

| Field | Result |
|---|---|
| Recommendation rank and score | Breadth implementation rank 1 after excluding generated live-validation ranks 1–7; selection score 90 |
| Platform family | `jaggaer/sciquest` (JAGGAER ONE public event) |
| Jurisdictions | Iowa (`IA`) and Utah (`UT`) |
| Source IDs / roles | `ia-impacs` and `ut-u3p`; primary statewide sources |
| Connector requirement | Reuse `JaggaerSciQuestConnector` with existing explicit `iowa/impacs` and `utah/u3p` profiles |
| Source-identity evidence | Iowa DAS bid-opportunities guidance and Utah Division of Purchasing current-bids guidance |
| Public-contract evidence | Explicit `DASIowa` and `StateOfUtah` `CustomerOrg` values, the allowlisted `bids.sciquest.com` public-event router, and sanitized listing/detail fixtures |
| Expected baseline / discovery / detail increase | +2 / +2 / +2 jurisdictions |
| Expected attachment increase | +2 manifest-capable jurisdictions |
| Expected document-pipeline increase | 0; deliberately `manifest_only` until a document adapter is established |
| Fixture-verification target | Tenant routing, GET query construction, stable IDs, normalization, details, attachments, access classification, bounds, deduplication, malformed responses, retries, circuit breaker, host safety, and client ownership |
| Live-validation status | Not validated; live count and dates remain unchanged |
| Authentication / CAPTCHA | None observed in sanitized fixtures; individual document links may require login; production behavior remains unknown |
| Remaining uncertainty | Current production reachability and markup, completeness across participating entities, attachment retrieval, redirects, and tenant-specific document behavior |

## Contract and security boundaries

Both profiles use only anonymous, bounded, read-only GET requests. The connector
retains authoritative backlinks and raw payloads, validates hosts and redirects,
deduplicates stable identities and documents, applies page/result ceilings,
classifies transient failures and `Retry-After`, and exposes circuit and health
state. Discovery records attachment metadata only; it never downloads documents.
The sources remain `manifest_only` because no JAGGAER document adapter is yet
registered with `DocumentOrchestrationService`.

The implementation does not log in, register a supplier, store or replay
credentials or cookies, solve CAPTCHA, enter a response workspace, submit a bid,
follow unvalidated redirects, or allow arbitrary hosts. A login-required link is
preserved as restricted metadata rather than retrieved.

## Coverage impact and deferred validation

The authoritative registry moves from 11 to 13 identified primary sources and
from seven to nine fixture-verified, baseline-operational, discovery-capable,
detail-capable, and attachment-capable jurisdictions. Primary platform families
increase from seven to eight because one shared JAGGAER family covers both new
jurisdictions. Primary-source gaps and Tier 0 jurisdictions fall from 49 to 47.
Document-pipeline-compatible jurisdictions remain six, and live-verified
jurisdictions remain zero. Fixture verification is explicitly **not** live
verification; no fixture date populates a live-verification field.

Deferred work is a bounded anonymous validation of one discovery page, one
detail, and at most one clearly public small attachment per tenant from a
permitted network, followed by a JAGGAER document adapter if retrieval is proven.
After this tranche, the generated queue recommends the nine fixture-operational
jurisdictions for live validation; the next breadth-first non-live item is the
Alabama statewide-source correction (generated rank 10, score 20).
