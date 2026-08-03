# PR #42 selection: six statewide Periscope BuySpeed profiles

## Merge and selection gate

PR #41 is present as merge commit `e69379d` and substantive commit `db8783b`.
Its Iowa and Utah JAGGAER profiles, fixtures, connector tests, authoritative
registry records, generated reports, and recommendation updates are present.
Both jurisdictions are baseline-operational and no longer appear as incomplete;
this change does not recreate PR #41.

The pre-change generated queue ranks nine fixture-operational sources awaiting
live validation at score 50. This PR is a breadth-first fixture implementation,
so validation-only tasks are excluded. The selected Periscope tranche is breadth
implementation rank 1 with a selection score of 100: 40 points for six primary
statewide gaps, 25 for reusing one implemented connector, 15 for six explicit
GET-only portal profiles, 10 for the shared deterministic fixture contract, and
10 for including an inhabited territory. It outranks the generated single-state
coverage corrections (starting at rank 10 and score 20) under the mandated
existing-profile-first priority.

## Selection report

| Field | Result |
|---|---|
| Recommendation rank and score | Breadth implementation rank 1 after excluding generated live-validation ranks 1–9; selection score 100 |
| Platform family | `periscope/buyspeed` (Periscope S2G / BuySpeed Online) |
| Jurisdictions | Illinois (`IL`), Massachusetts (`MA`), Nevada (`NV`), New Jersey (`NJ`), Oregon (`OR`), and U.S. Virgin Islands (`VI`) |
| Source IDs / roles | `il-bidbuy`, `ma-commbuys`, `nv-nevadaepro`, `nj-njstart`, `or-oregonbuys`, and `vi-gvibuy`; primary statewide or territory-wide sources |
| Connector/profile availability | Reuse `PeriscopeBuySpeedConnector`; all six explicit portal presets and public advanced-search routes already exist and now have stable profile keys |
| Source-identity evidence | Official jurisdiction procurement guidance for BidBuy, COMMBUYS, NevadaEPro, NJSTART, OregonBuys, and GVIBUY |
| Request-contract evidence | Allowlisted HTTPS base hosts, explicit `/bso/view/search/external/advancedSearchBid.xhtml` GET routes, and sanitized shared HTML/JSON fixtures |
| Expected baseline / discovery / detail increase | +6 / +6 / +6 jurisdictions |
| Expected attachment increase | +6 manifest-capable jurisdictions |
| Expected document-pipeline increase | 0; deliberately `manifest_only` until anonymous document retrieval and an adapter are established |
| Fixture-verification target | Profile registration, GET construction, query encoding, bounds, pagination, stable IDs, normalization, details, attachment manifests, deduplication, malformed and access-wall handling, retries, circuit breaker, health, host safety, raw preservation, and client ownership |
| Live-validation status | Not validated; live count and dates remain unchanged |
| Authentication / CAPTCHA | None observed in sanitized fixtures; production behavior and individual attachment access remain unknown |
| Remaining uncertainty | Current production reachability and markup, tenant-specific form/session behavior, complete statewide participation, redirects, and anonymous document retrieval |

## Contract and security boundaries

The connector performs bounded, asynchronous, read-only GET collection. It does
not follow redirects automatically, caps pages and results, validates configured
HTTPS hosts through fixed portal profiles, deterministically deduplicates records,
preserves raw payloads and authoritative backlinks, classifies malformed and
transient responses, honors `Retry-After`, and exposes circuit-breaker and health
state. Discovery records document metadata only and does not download files.

No login, supplier registration, credential or cookie storage, CAPTCHA handling,
bid workspace access, or bid submission is performed. Attachment discovery is
`manifest_only`; no claim of public document-pipeline retrieval is made.

## Coverage impact and deferred validation

The registry moves from 13 to 19 identified primary statewide sources and from
nine to 15 fixture-verified, baseline-operational, discovery-capable,
detail-capable, and attachment-capable jurisdictions. Identified primary
platform families increase from eight to nine. Primary-source gaps and Tier 0
jurisdictions fall from 47 to 41. Document-pipeline-compatible jurisdictions
remain six, and live-verified jurisdictions remain zero. Fixture verification is
explicitly **not** live verification, and fixture dates do not populate live
verification fields.

Deferred work is bounded anonymous validation of one discovery page, one detail,
and at most one clearly public small attachment per tenant from a permitted
network. After this tranche the generated queue recommends live validation of
the 15 fixture-operational jurisdictions; the next breadth-first non-live item is
the Alabama statewide-source correction.
