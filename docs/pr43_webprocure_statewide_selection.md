# PR #43 selection: Connecticut and Rhode Island WebProcure profiles

## Merge and selection gate

PR #42 is present as merge commit `239a71c` and substantive commit `93a4c17`.
Its six Periscope profiles, connector profile keys and tests, authoritative
registry records, selection report, generated coverage reports, and updated
recommendation queue are present. This change does not recreate that work.

The pre-change generated queue ranks 15 fixture-operational sources awaiting
live validation at score 50. Live validation is outside this fixture-first
breadth tranche, so those tasks are excluded. The selected WebProcure tranche
is breadth implementation rank 1 with a selection score of 80: 30 points for
two primary statewide gaps, 25 for reusing one implemented connector, 15 for
two explicit GET-only profiles, and 10 for a shared deterministic fixture
contract. Missouri's profile is excluded because the repository identifies it
as a legacy bid board and current primary statewide authority is not established.

## Selection report

| Field | Result |
|---|---|
| Recommendation rank and score | Breadth implementation rank 1 after excluding generated live-validation ranks 1–15; selection score 80 |
| Platform family | `webprocure/proactis` |
| Jurisdictions | Connecticut (`CT`) and Rhode Island (`RI`) |
| Source IDs / roles | `ct-ctsource` and `ri-ocean-state-procures`; primary statewide sources |
| Connector/profile availability | Reuse `WebProcureConnector`; stable profiles `connecticut/ctsource` (customer 51) and `rhode-island/ocean-state-procures` (customer 46, owner OID 120002) |
| Source-identity evidence | Connecticut DAS CTsource guidance and Rhode Island Division of Purchases public site |
| Request-contract evidence | Fixed HTTPS WebProcure bid-board and full-text-search hosts, explicit tenant parameters, existing sanitized JSON fixture, and connector tests |
| Expected baseline / discovery increase | +2 / +2 jurisdictions |
| Expected detail / attachment / document-pipeline increase | 0 / 0 / 0; capability remains metadata-only or unknown until a separate public contract is established |
| Fixture-verification target | Profile identity, GET parameter construction, name/code jurisdiction filtering, pagination and bounds, deterministic deduplication, stable IDs, normalization, authoritative fallback backlinks, raw payloads, malformed response handling, transient retries, `Retry-After`, circuit breaker, health, host safety, and client ownership |
| Live-validation status | Not validated; live count and dates remain unchanged |
| Authentication / CAPTCHA | None observed in the sanitized fixture; current production behavior remains unknown |
| Remaining uncertainty | Current reachability and response contract, tenant participation, direct detail access, attachments, amendments, authentication walls, CAPTCHA, redirects, and document retrieval |

## Contract and security boundaries

Collection is asynchronous, bounded, anonymous, read-only, and GET-only. The
connector uses a fixed search endpoint and fixed tenant identifiers, caps pages
and query results, deduplicates source IDs, preserves raw source records, does
not follow redirects automatically, and rejects foreign or non-HTTPS direct
links in favor of the reviewed tenant bid board. Bounded retries include
exponential backoff, jitter, `Retry-After`, circuit breaking, and health state.

No login, vendor registration, credential or cookie handling, CAPTCHA bypass,
document download, bid workspace access, or submission is performed. Discovery
does not claim detail, attachment, amendment, or document-pipeline support.

## Coverage impact and deferred validation

The registry moves from 15 to 17 identified and fixture-verified primary
statewide sources. Baseline-operational and discovery-capable jurisdictions
increase from 15 to 17; primary-source gaps and Tier 0 jurisdictions fall from
41 to 39. Identified primary platform families increase from nine to ten.
Detail-capable and attachment-capable jurisdictions remain 15,
document-pipeline-compatible jurisdictions remain six, and live-verified
jurisdictions remain zero. Fixture verification is explicitly **not** live
verification, and no fixture date populates a live-verification field.

Deferred work is bounded anonymous validation of one discovery page per tenant
from a permitted network, followed by separate evidence for any public detail
or attachment contract. After this tranche the generated queue recommends live
validation of the 17 fixture-operational jurisdictions; the next breadth-first
non-live item remains authoritative statewide-source research for Alabama.
