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
- Content-sniffed parsing and normalized, provenance-bearing text/table storage
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
- Public JAGGAER/SciQuest event discovery and detail/document-metadata enrichment
  for Utah U3P, UW System ShopUW+, Georgia Sourcing Director, and Iowa IMPACS

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
- `GET /api/v1/documents/{id}/extraction`
- `GET /api/v1/documents/{id}/extraction/blocks?page=&sheet=&limit=&offset=`
- `GET /api/v1/documents/{id}/extraction/tables`
- `GET /api/v1/documents/{id}/extraction/text?maximum_characters=`
- `GET /api/v1/documents/extraction/health`

## Document extraction

The public-document flow is connector discovery → opportunity ingestion → document
manifest → safe downloader → validated artifact → content-sniffed parser → native
extraction → page-specific OCR decision → normalized blocks/tables → future structured
RFP extraction. Parsing is not semantic RFP analysis and does not use an LLM.

Supported formats are PDF (native text and page-level OCR classification), DOCX,
XLSX, CSV, TSV, text, HTML, XML, RTF, and bounded ZIP. DOC, XLS, PPT, PPTX,
macro-enabled OOXML, encrypted PDF, and nested archives are deferred and reported as
unsupported or conversion-required; no office converter is launched. The optional
`documents` extra uses pypdf (BSD-3-Clause), openpyxl (MIT), python-docx (MIT), and
defusedxml (Python Software Foundation license). Runtime OCR uses the optional system
Tesseract executable (Apache-2.0); service startup does not depend on it.

PDF native text is usable when a page has at least 40 alphanumeric characters and five
words with no more than a 5% replacement-character ratio. A below-threshold page is
OCR-eligible only when it contains a raster image. Blank pages are skipped, native-text
pages are never OCR'd, and mixed PDFs classify only deficient image pages for OCR.
Tesseract is disabled by default and current PDF extraction reports `unavailable` when
rendering/OCR is required; it never silently pretends OCR ran.

DOCX relationships are not followed. HTML scripts, styles, forms, navigation, and frames
are ignored. XML DTD/entity declarations are quarantined. XLSX opens read-only with
formula expressions preserved as inert text (`data_only=False`, `keep_links=False`), so
no formula, macro, data connection, or external relationship is executed. ZIP entries
are inspected in memory without extract-all: absolute, traversal, drive-letter, symlink,
encrypted, nested, oversized, excessive-count, total-size, and compression-ratio cases
are rejected or skipped.

Extraction identity is artifact SHA-256 plus parser name/version. Successful identical
results are reused; a changed hash or parser version produces another auditable result,
and older results are retained while only the newest is marked current. Blocks preserve
page, sheet, paragraph, archive-entry, table and cell-range coordinates with stable
normalized offsets. Tables retain rows separately from flattened search text.

Run a bounded batch with:

```bash
python -m sled_aggregator.documents.extraction_worker --once
python -m sled_aggregator.documents.extraction_worker --batch-size 10
python -m sled_aggregator.documents.extraction_worker --ocr-health
```

All parsing is local to artifacts previously approved by the downloader. It fetches no
links, executes no document content, authenticates to no portal, and bypasses no CAPTCHA
or access control.

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

### JAGGAER/SciQuest public events

The `jaggaer/sciquest` connector is a configurable platform-family adapter for
the public `Router/PublicEvent` surface. Fixture-verified presets cover Utah U3P
(`StateOfUtah`), University of Wisconsin System ShopUW+ (`UWisconsin`), Georgia
Sourcing Director (`Georgia`), and Iowa IMPACS (`DASIowa`). Utah includes many
participating public entities, so the source issuer is preserved. Wisconsin is
limited to UW System events. Georgia is a secondary source to the Georgia
Procurement Registry rather than complete statewide registry coverage. Iowa's
public state bid interface can likewise remain the authoritative upstream link.

Discovery is bounded by tenant-configurable pages, page size, and result count;
supports exact event number, status, issuer and date filters; deduplicates stable
tenant-qualified identities; and performs local keyword filtering unless a
preset explicitly verifies remote GET filtering (currently Georgia). Public
detail enrichment retains original fields, issuing organization, source dates,
codes, contacts, award/upstream data, and access provenance in `raw_payload`.

The connector identifies metadata and safe links for solicitation packages,
specifications, scope/pricing files, addenda, amendments, Q&A, and award notices.
Attachment discovery does **not** download or parse files; text extraction and
OCR are separate future stages. “Respond Now” can require registration while
event details remain public. The connector never logs in, registers, submits a
response, uses POST, enters supplier areas, or bypasses CAPTCHA/access controls.
Login, registration, CAPTCHA, maintenance, malformed responses, JavaScript-only
shells, and transient failures are explicit access states.

Retries cover connection failures and HTTP 408/409/425/429/500/502/503/504 with
bounded exponential backoff, jitter, both `Retry-After` forms, and a per-tenant
cooldown circuit. HTTPS/host validation rejects credentials, local/private
destinations, unsafe schemes, foreign attachment hosts, and transient canonical
URL parameters. Tests use only sanitized fixtures and fake transports; no live
JAGGAER dependency exists in CI. Add a tenant by constructing `JaggaerPortal`
with a reviewed `CustomerOrg`, public URLs, capabilities, limits, parser strategy,
and allowed document hosts—no new connector class is needed. POST-backed searches,
authenticated documents, browser automation, downloading, extraction, and OCR
remain unsupported.

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

### Pennsylvania eMarketplace

Use `pennsylvania/emarketplace` (aliases `pa-emarketplace`,
`pennsylvania-emarketplace`, and `pa/emarketplace`) for bounded public discovery
at `https://www.emarketplace.state.pa.us/Search.aspx`. It supports explicitly
selected current and archived solicitation lanes and, when requested, the
separate `Procurement.aspx` upcoming-procurement lane. Upcoming records remain
forecasts, are not advertised opportunities available for response, and receive
no deadline unless one is displayed.

The query exposes exact solicitation number, keyword, agency, county, statewide,
multiple-county, solicitation type, advertisement type, Small Business,
SDB/VBE-goal, bid-open-date, posted-since, records-per-page, and bounded page and
result controls. Public WebForms POSTs carry fresh `__VIEWSTATE`,
`__VIEWSTATEGENERATOR`, and `__EVENTVALIDATION` values in memory only. One
session refresh is allowed after an expired-state or invalid-postback response;
cookies and hidden values never enter logs, fixtures, or provenance.

Identity prefers the public SID (or upcoming procurement ID), then agency plus
the string solicitation number. Current/archive copies deduplicate by that
identity while amendments update the record; rebids with distinct SIDs remain
distinct. Source status and dates are retained, Eastern dates use
`America/New_York`, and due and opening times remain separate. Advertisement
dates are not replaced: Pennsylvania says the solicitation and attachments
control conflicts, which is recorded for later extraction.

Detail enrichment preserves original files, flyers/addenda, tabulations, awards,
contracts, contacts, delivery, duration, advertisement/type labels, and explicit
Small Business/SDB/VBE data. Documents are metadata only—no bulk download, text
extraction, archive expansion, or OCR occurs. Supplier Portal links are
`supplier_portal_required`, JAGGAER response links are
`external_account_required`, and PennDOT ECMS links are `external_system`; none
is authenticated or submitted. COSTARS, supplier/vendor registration and
directories, contract catalog/spend ingestion, JAGGAER qualification, and ECMS
ingestion are outside this connector.

The connector detects login, registration, MFA, CAPTCHA, restriction,
maintenance, generic errors, forbidden responses, and expired WebForms state.
It retries only connections and 429/502/503/504 with bounded exponential
backoff, jitter, both Retry-After forms, concurrency, circuit health, and correct
client ownership. Coverage is the public eMarketplace used by most general
Commonwealth agencies—not every Pennsylvania SLED entity, notably not PennDOT
highway and bridge construction in ECMS. No login, registration, MFA, CAPTCHA
bypass, purchasing, qualification, bid submission, or access-control
circumvention is performed.

## CGI Advantage Vendor Self-Service

Use `cgi/advantage-vss` for the configurable, public-read-only CGI Advantage
Vendor Self-Service family. Explicit aliases are `cgi/vss`, `cgi-advantage`,
`cgi-advantage-vss`, and `advantage-vss`; tenant aliases are `maine/vss`,
`michigan/sigma-vss`, and `colorado/vss`. The intentionally ambiguous `vss`,
`sigma`, `advantage`, `vendor-portal`, and `supplier-portal` names are not
registered.

The portal model keeps Advantage4 and legacy AltSelfService routes, timezone,
guest bootstrap, anonymous-session requirements, verified capabilities,
validation level/date, restrictions, attachment hosts, and availability schedule
separate for every tenant. Maine is an enabled public-guest preset with
fixture-verified parsing; because live access was blocked by the execution
network, public collection remains capability-gated. Michigan SIGMA and
ColoradoVSS are configured-unverified and disabled until search, detail,
attachment, award, and contract behavior are independently live-validated.
Branding alone never enables another CGI tenant.

Discovery is bounded by page, page-size, and record limits. It supports
configuration for exact solicitation number, keyword, type, status, department,
agency, buyer, commodity text/code, published/closing dates, and open/closed or
award scopes only after a tenant route has been verified. Identifiers remain
strings and are namespaced by tenant; stable public internal IDs take precedence
and full solicitation numbers (including leading zeroes and suffixes) are the
fallback. Unknown status and solicitation types remain unknown rather than being
invented. Dates are parsed in the tenant's IANA timezone and date-only values are
preserved in provenance rather than silently converted to midnight.

Public detail enrichment retains commodity lines under one parent opportunity,
public instructions, explicitly displayed awards, and related contract
references. Attachment discovery records the displayed metadata and exact safe
URL, parent identity, access state, session requirement, and retrieval
eligibility. It rejects unsafe schemes, credentials, private/local address
literals, metadata hosts, and unapproved cross-host downloads. Discovery does
not download all files, extract document text, run OCR, open archives, or execute
active content. A later retrieval stage must revalidate redirects, content type,
size, and archive bounds and must treat HTML login responses as restricted.

Guest initialization uses only the published public/guest control, keeps session
state in the tenant-owned in-memory client, and refreshes an expired guest
session at most once per collection. It never logs or persists cookies or hidden
session material. Per-tenant health, retries for 429/502/503/504, numeric and
HTTP-date `Retry-After`, bounded concurrency, exponential backoff, and circuit
cooldown prevent one deployment's failure from opening another tenant's circuit.
Login, registration, verification, CAPTCHA, invitation-only, stable forbidden,
and scheduled-unavailable responses are classified and are not bypassed.

The connector never logs in, registers a vendor, automates verification,
accesses account purchasing/payment data, enters a response workspace, accepts
terms, submits bids, or bypasses CAPTCHA. Maine guidance places current and
historical RFPs published on or after **October 1, 2025** in VSS; older archive
coverage must not be assumed. Colorado says most state agencies and many higher
education institutions use ColoradoVSS, not every Colorado entity. Its published
availability/maintenance schedule must be validated and configured before an
enabled collector suppresses retries outside the operating window.

Authoritative starting points:

- CGI VSS overview: <https://www.cgi.com/us/en-us/brochures/cgi-advantage/cgi-advantage-vendor-self-service>
- Maine VSS guidance: <https://www.maine.gov/dafs/bbm/procurementservices/vendors/vendor-self-service-system>
- Maine RFP archives: <https://www.maine.gov/dafs/bbm/procurementservices/vendors/rfps/rfp-archives>
- Michigan SIGMA: <https://www.michigan.gov/budget/budget-offices/sigma>
- Michigan Contract Connect: <https://www.michigan.gov/dtmb/procurement/contractconnect>
- ColoradoVSS information: <https://vss.state.co.us/>

## OpenGov Procurement / ProcureNow

Use `opengov/procurement` for the configurable, anonymous OpenGov Procurement
(historically ProcureNow) portal family. Explicit aliases include `opengov`,
`opengov-procurement`, `procurenow`, `procurenow/opengov`, and
`opengov-procurenow`; aliases for unrelated OpenGov product families are
intentionally excluded. Production presets cover the City of Phoenix, Seattle,
Cleveland, Bridgeport, Gallup, and Mohave County. A new tenant is configuration,
not a new connector class.

Discovery prefers the public embed project list and is bounded by page, page
size, and result limits. Exact project/solicitation identifiers plus keyword,
status, department, release-date, and due-date filters run locally when the
tenant does not expose a stable anonymous GET search. Detail enrichment uses
only configured public project pages. Genuine zero results, malformed markup,
JavaScript-only shells, login/registration interstitials, CAPTCHA, restrictions,
and transient failures remain distinct outcomes.

Project documents, attachments, addenda, notices, public Q&A, and award links
are retained as metadata with source provenance and safe-host validation.
`document_candidates()` converts that metadata to the established manifest and
retrieval-queue input. The connector never retrieves attachment bodies, parses,
runs OCR, performs semantic extraction, registers, follows projects, accepts
terms, acknowledges addenda, or submits responses. All network operations are
anonymous GETs with bounded redirects, retries, per-tenant circuit state, and
fixture-backed tests; CI does not depend on live OpenGov access.

## Solicitation document manifest and retrieval queue

The document pipeline is a public, read-only coordination layer:

```text
Connector discovery -> opportunity ingestion -> document candidate classification
 -> document manifest -> eligibility and access checks -> durable retrieval queue
 -> future downloader -> future parser/targeted OCR -> future structured extraction
 -> opportunity evaluation and export
```

Connectors may supply optional `DocumentCandidate` metadata; connectors returning no documents remain
compatible. Deterministic filename, title, category, and link-text signals classify likely procurement
artifacts. Public HTTP(S) candidates alone are auto-queued. Metadata-only, login, registration,
CAPTCHA, restricted, malformed, and unsafe links remain auditable but are never retrieval work.

The PostgreSQL queue orders by priority (0–100), availability, discovery/creation time, and UUID. A
worker claims rows using `FOR UPDATE SKIP LOCKED`, receives an expiring owner/token lease, and must
present both to acknowledge work. Expired leases return to queued state; retries use bounded
exponential backoff and exhausted work is quarantined. The unique document job constraint makes
enqueue idempotent.

Manifest identity follows source document ID, canonical URL, logical key/version, then a scoped
fingerprint. Versions group by opportunity and conservative logical evidence. Explicit replacement of
a primary or pricing revision may supersede its predecessor; addenda, amendments, Q&A, awards, and
cancellations remain separately operative and auditable.

Read-only endpoints are `GET /api/v1/documents`, `GET /api/v1/documents/opportunity/{id}`,
`GET /api/v1/documents/{id}`, and `GET /api/v1/documents/queue/stats`. Operational endpoints are
intentionally deferred until an authorization boundary exists. Settings use the `DOCUMENT_*`
environment variables corresponding to fields in `Settings`.

This stage does **not** download files, parse PDF/Office files, extract text, run OCR, inspect ZIP
contents, perform LLM analysis, use authenticated portal sessions, bypass CAPTCHA/access controls,
or submit bids. PR #13 will add a safe public downloader; PR #14 parsing and targeted OCR; PR #15
structured RFP/SOW/PWS extraction and version reconciliation. Later work includes object storage,
authorized operations, workers, retention/export/reprocessing, malware scanning, bounded archive
handling, and evaluation integration.

## Safe public document downloader

The document pipeline is connector discovery → opportunity ingestion → canonical manifest → durable retrieval queue → safe downloader → bounded validation → streaming SHA-256 → artifact storage → future parser/OCR/structured extraction → evaluation and export. Run the disabled-by-default one-shot worker with `DOCUMENT_DOWNLOADER_ENABLED=true python -m sled_aggregator.documents.worker --once` (or `--batch-size 10`).

Only current, eligible, explicitly public manifest entries with valid leases are fetched. Every redirect is checked against HTTP(S), ports, host affinity/allowlist, and public-IP SSRF rules. Files stream through unpredictable temporary names, use a configurable 100 MiB default limit, and are incrementally SHA-256 hashed. Detection covers PDF, ZIP/OOXML containers (without inspection), legacy Office, RTF, text/CSV, XML, HTML, PNG and JPEG. Bounded HTML inspection rejects login, registration, CAPTCHA/bot challenge, denied, missing, expired-session and maintenance pages. ETag/Last-Modified conditional GET and hash equality detect unchanged bytes.

The `local` adapter atomically commits deterministic identifier/hash keys under `DOCUMENT_STORAGE_ROOT` (default `/tmp/sled-aggregator/documents`) without exposing paths. Artifact rows preserve versions and attempt rows preserve bounded audit provenance. Deterministic keys and checksum verification reconcile retries across the unavoidable storage/database boundary. Timeouts, network errors, 408/425/429 and 5xx are retryable; unsafe, restricted, login/registration/CAPTCHA, missing, oversized, unsupported and suspicious responses are terminal. Standard httpx cannot pin a prevalidated DNS answer to its socket, so production egress filtering remains necessary.

`DOCUMENT_DOWNLOAD_*` variables configure timeouts, chunk/file and redirect/attempt limits, batch/concurrency, User-Agent, allowed ports/hosts, probes, and temporary storage. This downloader does **not** parse files, extract text, run OCR, inspect ZIP contents, analyze requirements, use LLMs, authenticate to portals, bypass CAPTCHA/registration, or submit bids. PR #14 is parsing/targeted OCR; PR #15 is structured extraction/version reconciliation. Cloud adapters, malware scanning, scheduling, authorized controls, retention, live validation, user downloads and evaluation integration are later work.

## Structured solicitation intelligence

The document pipeline now continues from normalized text blocks and tables into deterministic,
evidence-backed schema version `1.0`:

```
connector discovery -> opportunity ingestion -> document manifest -> safe download
-> artifact validation -> parsing and targeted OCR -> normalized blocks and tables
-> deterministic structured extraction -> evidence-backed facts -> document reconciliation
-> effective opportunity snapshot -> change ledger -> JSON export
-> future capability matching and evaluation
```

Facts retain normalized and original values, typed value metadata, the source-status vocabulary
`explicit`, `derived`, `inferred`, `conflicting`, `superseded`, and `unknown`, heuristic confidence,
and bounded evidence references. Missing information remains unknown rather than being fabricated.
Requirements use `mandatory`, `prohibited`, `conditional`, `recommended`, `optional`,
`informational`, or `unclear` strength. OCR evidence and its confidence remain identified.

Authority is field-specific: cancellation controls cancellation status; explicitly controlling revised
primaries take precedence; formal amendments/addenda modify only fields they address; official Q&A
controls only when it explicitly modifies the solicitation; then primary solicitations, attachments,
and notices follow. Award material adds post-award facts and never rewrites pre-award history.
Same-authority incompatible values remain visible in explicit conflict groups until resolved.

Run one bounded batch with:

```bash
python -m sled_aggregator.documents.intelligence_worker --once
python -m sled_aggregator.documents.intelligence_worker --batch-size 10
```

Read-only routes under `/api/v1/opportunities/{id}/intelligence` provide the summary, snapshot,
facts, dates, contacts, requirements, deliverables, evaluation factors, codes, document authority,
change ledger, unresolved conflicts, evidence, sections, extraction status, and deterministic
`export.json`. Lists are bounded. Exports have stable ordering, bounded evidence, authoritative URLs,
and exclude storage and lease internals.

Configuration uses the `SOLICITATION_INTELLIGENCE_*` environment variables represented in
`Settings`. Extraction never fetches a URL, authenticates to a portal, executes document content,
or sends solicitation content to an external LLM. No external LLM is used in this implementation.
Future work includes capability/profile matching, qualification scoring, pursuit recommendations,
compliance matrices, optional semantic providers, authorized human conflict resolution, hybrid
search, amendment alerts, CSV/XLSX exports, user authorization, and a live connector harness.
Connector expansion includes the reusable OpenGov Procurement/ProcureNow connector.
