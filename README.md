# TrustEST SLED Aggregator

Backend-first procurement-intelligence service for discovering, normalizing,
and evaluating State, Local, Education, and Tribal opportunities.

The aggregator is the intake layer for a broader teaming-intelligence product.
It is intentionally limited to public, authorized, read-only procurement data.
It does not submit bids, bypass CAPTCHA, automate login walls, or circumvent
portal controls.

## Initial capabilities

- FastAPI service with versioned routes and health checks
- Canonical opportunity and solicitation-document models
- Reusable platform-family connector contract and registry
- Opportunity normalization and deterministic deduplication
- Document eligibility classification
- Access-state handling for public and restricted documents
- Configuration for targeted OCR and bounded ZIP processing
- PostgreSQL-ready runtime configuration
- SQLAlchemy persistence adapter and Alembic migration baseline
- Unit tests for normalization, classification, and connector registration
- Public WebProcure/PROACTIS discovery for Connecticut (CTsource), Missouri's
  legacy bid board, and Rhode Island (Ocean State Procures)
- Configurable Periscope S2G/BuySpeed public discovery presets for Illinois,
  Massachusetts, Nevada, New Jersey, Oregon, and the U.S. Virgin Islands
- Docker and GitHub Actions development baseline
- Virginia eVA public opportunity-board discovery with lot/round consolidation,
  IVDetails/IVDetailsV2 enrichment, and access-aware document metadata

## Architecture

```text
Portal connector
      |
      v
RawOpportunity ---> OpportunityNormalizer ---> CanonicalOpportunity
                                                |
Attachment metadata ---> DocumentClassifier ----+
                                                |
                                      downstream intelligence
                         matching | teaming | bid/no-bid | alerts | exports
```

Connectors are organized by platform family rather than jurisdiction. A single
connector may support multiple states, territories, agencies, counties, school
systems, or public authorities when they share the same portal implementation.

## Quick start

Requirements:

- Python 3.12+
- Docker (optional)

Create an environment and install the development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run the API:

```bash
uvicorn sled_aggregator.main:app --reload
```

Run checks:

```bash
python -m unittest discover -s tests -v
python -m compileall src tests
ruff check .
```

Or with Docker:

```bash
docker compose up --build
```

## API baseline

- `GET /health`
- `GET /api/v1/opportunities`
- `POST /api/v1/opportunities/normalize`
- `POST /api/v1/documents/classify`
- `GET /api/v1/connectors`

The opportunity service is repository-backed. PostgreSQL is the production
adapter; an in-memory adapter supports deterministic unit testing.

## Data principles

1. Store normalized text, structured fields, metadata, provenance, hashes, and
   links back to the opportunity and source document.
2. Retrieve only documents likely to contain the solicitation package,
   including RFP/RFQ/IFB, SOW/PWS, specifications, amendments, Q&A, pricing,
   evaluation, and submission instructions.
3. Run OCR only on image-only pages or standalone images.
4. Expand ZIP packages only inside configurable size, file-count, depth, path,
   encryption, and type safeguards.
5. Keep the newest valid active document record; historical redlines are
   deferred.
6. For login-, CAPTCHA-, or policy-restricted files, retain metadata and link
   back to the portal without attempting circumvention.
7. Use parsed data for summaries, matching, bid/no-bid, teaming, compliance,
   alerts, proposal planning, search, and user downloads.

## Adding a connector

Implement `BaseConnector`, declare its platform-family name and supported
jurisdictions, then register it:

```python
from sled_aggregator.connectors.base import BaseConnector
from sled_aggregator.connectors.registry import connector_registry

class ExampleConnector(BaseConnector):
    platform_family = "example"
    jurisdictions = ("Example State",)

    async def discover(self, query):
        ...

connector_registry.register(ExampleConnector)
```

Connector implementations must enforce public/read-only behavior, use bounded
timeouts and rate limits, and return source URLs and access-state metadata.

### WebProcure/PROACTIS

The reusable WebProcure connector searches only the public full-text endpoint
and supports bounded keyword or wildcard discovery for Connecticut, Missouri,
and Rhode Island. It performs GET requests only: it does not submit bids,
register vendors, automate login, bypass CAPTCHA or robots controls, store
credentials, or retrieve restricted documents. Restricted content remains at
its authoritative portal link.

Every result retains its complete source record. An authoritative direct URL is
used when supplied; otherwise the connector links to the configured public bid
board (including Rhode Island's owner-organization OID). Transient 429, 502,
503, and 504 responses and connection failures receive bounded exponential
backoff with jitter and `Retry-After` support. Repeated failed collection runs
open a configurable cooldown circuit, and connector health reports availability,
failure count, status, and failure time.

The production full-text endpoint has recently returned 502 and 503 responses.
Automated tests therefore use fixtures and test transports rather than requiring
live portal availability.

### Virginia eVA

The `virginia/eva` connector (aliases `eva`, `virginia-business-opportunities`,
and `cgi/eva`) models the public `PublicSearch.jsp` and `AllOpportunities.jsp`
routes, including URL-encoded `status` and `agencyname` filters. It follows only
public GET links to the separately parsed `IVDetails.jsp` and `IVDetailsV2.jsp`
variants. The stable source identity is `rfp_id_lot`; `rfp_id_round` is version
provenance, and the highest round is emitted rather than duplicated.

Discovery is independently bounded by page, result, and detail limits. It stops
on empty or repeated pages and supports keywords, reference/lot ID, agency,
status, notice type, issue/closing dates, NIGP, and locality through configurable
query parameters. Known IFB/RFP/RFQ/RFI, Quick Quote, unsealed, sole-source,
emergency, award, cancellation, amendment, and notice types are mapped
conservatively; the verbatim source value always remains in `raw_payload`.

Document discovery retains authoritative eVA URLs, lot/round, apparent type,
category, dates, attachment ID, and anonymous-session/account access state.
It does not download, extract, or OCR attachments. Login, registration, session
expiration, CAPTCHA, maintenance, and HTTP 403 pages fail closed; a stable 403
is not retried and means only that this execution environment is blocked, not
that vendor authentication is universally required. Transient failures retain
the standard bounded retry, Retry-After, jitter, circuit, health, and HTTP-client
ownership behavior.

CI is fixture-only and does not contact eVA. A July 29, 2026 live check of
robots.txt, search, board, open-status, and one agency-filtered board was blocked
by the execution environment's CONNECT proxy (HTTP 403 before an origin
response). Those routes are therefore `blocked`; list/detail parsing and
document visibility are `fixture_verified`; both detail route templates are
`configured_unverified`. No opportunity IDs were guessed or enumerated.

### Texas Electronic State Business Daily

The `texas/esbd` connector (aliases `esbd`, `texas-esbd`, and
`texas-smartbuy-esbd`) is a Texas-specific, public, read-only adapter for the
Electronic State Business Daily presented at `https://www.txsmartbuy.gov/esbd`.
It deliberately excludes Texas SmartBuy contracts and catalog products, CMBL
vendor/registration records, Vendor Performance Tracking, shopping, and bid
submission. The broad alias `texas-smartbuy` is reserved for a possible future
contract/catalog connector.

Discovery is asynchronous and bounded by configured page size, maximum pages,
details, results, and concurrency. The query model supports keyword,
solicitation ID, agency name/member number, status, NIGP class/item, posting
and response dates. Punctuation is removed only from outbound NIGP filters while
displayed codes remain intact. Empty or repeated pages stop a run, source IDs
are deduplicated, and output order is deterministic. Parameter names and the
detail template are `configured_unverified`; sanitized parsing is
`fixture_verified`.

An official ESBD internal ID is preferred for identity. If absent, the
agency/member number plus solicitation ID prevents same-number bids from
colliding. Addendum and award changes retain that identity. ESBD's documented
post-deadline visibility gap is not treated as deletion: observations record
`last_seen_at`, preserve source status, and declare an absence-is-not-deletion
policy in provenance.

Displayed deadlines use `America/Chicago`, including CST/CDT transitions; dates
without a time are left unset rather than inventing midnight. Provenance retains
the displayed deadline and available agency, NIGP, contact, HUB/HSP,
value/quantity, conference, award, and addendum fields.

Document discovery preserves exact public URLs, including every exposed
`/core/media/media.nl` query/hash parameter. Relative links resolve against the
official page, unsafe schemes are rejected, and internal media is distinguished
from external links. Public response links and account-required documents remain
metadata only. No document downloading, extraction, OCR, fabricated URLs,
authentication, registration, CAPTCHA bypass, purchasing, or bid submission is
implemented.

HTTP 429/502/503/504 and connection failures receive bounded exponential
backoff, jitter, and numeric or HTTP-date `Retry-After` handling. Login, CAPTCHA,
forbidden, maintenance, generic-error, and incompatible HTTP 200 pages fail
closed. Health reports the cooldown circuit, failures, last status and times,
and access state. Injected clients remain caller-owned; created clients close.

On July 29, 2026, the environment's CONNECT proxy returned HTTP 403 before an
origin response for the requested official reference pages, ESBD landing page,
and robots.txt. Posted, agency 305 Posted/Awarded, NIGP, detail, and attachment
validation was therefore `blocked` rather than reported as successful. Fixture
coverage is `fixture_verified`; live parameters, ordering, limits, pagination,
wildcard semantics, sessions, redirects, CAPTCHA triggers, and delivery remain
`configured_unverified`. No statewide-completeness claim is made.

Official research entry points were:

- `https://comptroller.texas.gov/purchasing/contact/outreach.php`
- `https://comptroller.texas.gov/purchasing/vendor/information.php`
- `https://comptroller.texas.gov/purchasing/members/`
- `https://comptroller.texas.gov/purchasing/vendor/registration/`
- `https://www.glo.texas.gov/open-government/doing-business-glo`
- `https://www.txsmartbuy.gov/esbd`
- `https://www.txsmartbuy.gov/robots.txt`

### Periscope S2G/BuySpeed

Select the reusable connector with the `periscope/buyspeed` key. Presets provide
authoritative public entry points for Illinois BidBuy, Massachusetts COMMBUYS,
NevadaEPro, NJSTART, OregonBuys, and GVIBUY. Each preset independently controls
its URLs, response strategy, query and pagination names, field aliases, date
formats, optional anonymous-session initialization, detail URL construction,
headers, and document-session behavior; sharing a platform family is not treated
as proof that deployments behave identically.

Discovery is asynchronous and GET-only, bounded by page, page-size, query-limit,
and connector result caps, and stops on repeated pages. It supports configured
JSON, HTML, and hybrid list/detail parsing, preserves unfamiliar source fields,
deduplicates stable source IDs, and skips malformed records observably. Public
document metadata for likely solicitation materials is retained in `raw_payload`
with its authoritative URL, opportunity URL, and public, session-dependent, or
restricted access state. The connector does not download or extract documents.

Authentication redirects, login/session-expired pages, CAPTCHA challenges, and
403 responses fail as restricted rather than becoming false empty results. The
connector never logs in, registers, submits, stores credentials, circumvents a
control, or retrieves restricted files. Transient 429, 502, 503, and 504 status
codes and connection failures use bounded exponential backoff, jitter,
`Retry-After`, cooldown circuit breaking, and portal-specific health reporting.

Only the six public bid-board entry URLs and expected platform family are
recorded as production facts. Anonymous list/detail endpoint behavior and field
mappings were not live-verified for this change; presets explicitly mark that
limitation and remain configurable. All parser, pagination, access-boundary,
document-link, transport-ownership, and resilience behavior is fixture-tested
with injected transports, so the unit suite makes no production portal calls.

## Project layout

```text
src/sled_aggregator/
  api/             HTTP routes and dependencies
  connectors/      Platform-family connector contracts and registry
  domain/          Canonical models and enums
  services/        Normalization and document-selection rules
tests/             Standard-library unit tests
docs/              Architecture and operating constraints
```

## Roadmap

1. Add connector execution jobs, change detection, and observability.
2. Add more reusable public portal-family connectors.
3. Implement document retrieval, extraction, targeted OCR, and safe archives.
4. Add profile/capability matching and explainable fit scoring.
5. Feed teaming, compliance, risk, alert, and export workflows.

## Database migrations

Apply the current schema:

```bash
alembic upgrade head
```

Create a migration after changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe change"
```

### Infotech Bid Express / BidX

Use `infotech/bid-express` (aliases: `infotech/bidx`, `bid-express`, and
`bidx`) for this configurable family connector. BidX is transportation-focused:
state DOT highway, bridge, construction letting, proposal, and bid-result data.
Bid Express and Infotech Express also serve local agencies and support both
construction and general procurement. Their routes, identifiers, formats,
sessions, and access rules are configured independently rather than assumed to
be interchangeable. Supported variants are `bidx_legacy`, `bidx_modern`,
`bidexpress_general`, `infotech_express`, and
`unknown_configurable_variant`.

Configured-only presets record the public BidX directory coverage for 39 states,
plus MBTA, the New Jersey Turnpike Authority, New York State Thruway Authority,
and North Carolina DOT divisions. They intentionally contain no guessed agency
IDs or listing endpoints and fall back to the authoritative directory. A portal
becomes live-verified only after its agency identifier, anonymous listing route,
detail behavior, and document behavior are confirmed. Directory presence is not
a claim that every agency is currently reachable or fixture-tested behavior is
production-verified.

Configured public endpoints support asynchronous GET-only bounded discovery,
keyword and jurisdiction filtering, agency parameters, JSON, HTML, XML, CSV, and
hybrid detail strategies. Page size, page count, result count, duplicate IDs,
and repeated pages are bounded. Complete platform fields—including letting,
route, county, project, estimate, participation-goal, work-type, contact, award,
and bid-result data without a current canonical field—remain in `raw_payload`.
Stable identities add a verified agency identifier when one is configured.

Document discovery records public proposal packages, plans, specifications,
addenda, notices, forms, item lists, RFP/RFQ/IFB and SOW/PWS materials, bid tabs,
and award links without downloading them. Metadata includes apparent type,
opportunity link, anonymous-session need, and registration, login, subscription,
or payment state. Restricted resources remain link-only. HTTP 200 login,
registration, subscription, payment, Digital ID, CAPTCHA, maintenance, and error
pages are explicit access boundaries, as are redirects and 403 responses; the
connector never registers, logs in, pays, creates a Digital ID, bypasses a
challenge, or submits a bid.

Retries, exponential backoff with jitter, numeric and HTTP-date `Retry-After`,
connection handling, transient 429/502/503/504 responses, cooldown circuit
breaking, success reset, health snapshots, and transport ownership follow the
existing connector conventions. CI uses only synthetic fixtures and injected
transports. Live behavior remains limited by independently changing public
routes, public-session rules, and agency policies; respectful live verification
and document content retrieval are deferred.

### Oracle PeopleSoft Strategic Sourcing

Use `oracle/peoplesoft-sourcing` (aliases `peoplesoft`,
`peoplesoft/supplier-portal`, and `california/cal-eprocure`) for configurable
public Supplier Portal and Strategic Sourcing discovery. The initial Cal
eProcure preset identifies California, FI$Cal, and the California State
Contracts Register and preserves its authoritative event-search fallback. It
does not promote temporary PeopleSoft component, action, cache, bidder, round,
version, or session values to stable configuration.

Discovery establishes a bounded anonymous session using public GET navigation,
keeps hidden form state only in connector memory, and supports configurable
HTML, partial-page HTML, JSON, XML, and CSV parsing. Query metadata covers event
ID/name, Business Unit, status and date ranges, UNSPSC, service area/county,
and current or historical events. Pagination, results, retries, and circuit
recovery are bounded; repeated pages and stable event identities are
deduplicated. California identities use `CA:Business Unit:Event ID`; event
round/version stays as amendment provenance unless a future verified deployment
requires it to distinguish materially separate records.

Likely packages, solicitations, specifications, work statements, pricing,
forms, addenda, Q&A, exhibits, insurance, and certifications are discovered as
metadata only. Current entries retain title, apparent type, source and parent
URLs, attachment ID, version, modified value, anonymous-session need, and access
state; explicitly superseded entries are omitted while their source metadata
remains in `raw_payload`. No document text, OCR, submission, registration,
Digital ID, private message, login, or authenticated download is performed.

HTTP 200 login, registration, CAPTCHA, maintenance, permission, and expired
session pages fail closed, as do forbidden and unexpected responses. Fixture
tests verify public-session state, parsing, fallback links, documents, access
boundaries, retries, circuit recovery, and client ownership without contacting
production. The public Cal eProcure entry points are configured; detailed
component behavior, event-package downloads, attachments, and pagination were
not live-validated in this change and remain configured/fixture-only.

To add a deployment, create a `PeopleSoftSourcingPortal` preset with verified
public entry/search URLs, response strategy, query/field aliases, date formats,
and its independently observed session and document behavior. Never copy a
California session token or infer that another PeopleSoft component is public.
