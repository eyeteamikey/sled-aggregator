# TrustEST SLED Aggregator

Connector collection can hand canonical document candidates to the durable
manifest immediately after opportunity persistence. Oracle Fusion REST,
Pennsylvania eMarketplace, and Tyler Munis/VSS are the first fixture-verified
families on this shared path. Ingestion is metadata-only and non-networked;
only confirmed public, policy-eligible documents are queued for the separate
safe downloader. Restricted links remain visible as metadata and are never
retrieved.

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
- Configurable, bounded, anonymous Euna OpenBids (formerly DemandStar) discovery,
  detail enrichment, and access-aware document metadata. Its canonical family is
  `euna/openbids-demandstar`; aliases include `demandstar`, `openbids`, and
  `euna/openbids`. It is separate from Euna Bonfire and IonWave.

### Euna OpenBids / DemandStar

DemandStar is now named **Euna OpenBids**, although legacy DemandStar URLs,
agency references, branding, and workflows remain. Profiles validate an explicit
platform/document host allowlist, bound page size/pages/results, and qualify every
upstream identifier with the agency profile key. Migrated and legacy profiles retain
provenance but are not collected as current DemandStar agencies.

The connector uses anonymous GET requests only. Public metadata is retained when a
document requires registration, login, subscription, or payment; such candidates are
marked incomplete and are not queued for anonymous retrieval. Public candidates feed
the existing manifest, safe downloader, parsing, targeted OCR, structured extraction,
and version-reconciliation pipeline.

It does **not** register supplier accounts, log in, purchase subscriptions, pay package
fees, submit bids, acknowledge addenda, join planholder lists, bypass CAPTCHA or other
controls, or retrieve private supplier responses. To add an agency, create a
`DemandStarProfile`, choose conservative bounds, allow only verified platform and
official document hosts, start as `configured_unverified`, and promote verification
only after sanitized fixture or bounded public verification.

Fixture-verified behavior demonstrates parser and connector behavior against captured
test inputs. It does not prove that every live Euna OpenBids/DemandStar agency or
endpoint is currently anonymously accessible. Markup and anonymous access vary by
agency, and gated documents leave downstream evaluation explicitly incomplete.

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

Connecticut and Rhode Island use explicit `connecticut/ctsource` and
`rhode-island/ocean-state-procures` statewide profile keys. Jurisdiction routing
accepts the full name or postal code, and result backlinks fail closed to the
configured bid board unless they are HTTPS URLs on the fixed WebProcure public
host. Their fixture-verified capability is discovery only: public detail,
attachments, document retrieval, and live production operation remain
unestablished.

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
separate for every tenant. Maine is an enabled public-guest preset and Michigan
SIGMA is an enabled Advantage4 preset, both with fixture-verified parsing;
current anonymous production operation remains unvalidated. ColoradoVSS is
configured-unverified and disabled until its tenant-specific search, detail,
attachment, award, and contract behavior is independently evidenced.
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
(historically ProcureNow) portal family. Ocean County, New Jersey and Alameda
County, California were live-validated on 2026-08-24. Explicit aliases include `opengov`,
`opengov-procurement`, `procurenow`, `procurenow/opengov`, and
`opengov-procurenow`; aliases for unrelated OpenGov product families are
intentionally excluded. Validated presets are `ocean-county-nj` and
`alameda-county-ca`; older configured presets remain explicitly unverified. A
new tenant is configuration, not a new connector class.

Discovery uses the observed anonymous `POST
/api/v1/government/{tenant}/project/public` JSON contract and is bounded by
one-based page, page-size, and result limits. The HTTP body is the query object
itself, without an outer `data` wrapper. Only observed title, financial ID,
status, department ID, category ID, and sorting fields are sent. Date bounds are
applied locally because the public portal did not expose date filters. Detail and
Q&A enrichment use the observed public GET routes. Empty results, malformed
schemas, login walls, CAPTCHA/bot verification, restrictions, and transient
failures remain distinct outcomes.

Project documents, attachments, addenda, notices, public Q&A, contacts, public
bid-result vendors, and award state are retained as metadata with source
provenance.
`document_candidates()` converts that metadata to the established manifest and
routing input. The connector never retains signed attachment URLs, retrieves attachment bodies, parses,
runs OCR, performs semantic extraction, registers, follows projects, accepts
terms, acknowledges addenda, or submits responses. OpenGov's public UI required
login before document download, so every attachment candidate is marked
`login_required`. Network operations are limited to the exact listing POST and
public GET contracts, with retries, timeout, per-tenant circuit state, and
fixture-backed tests; CI does not depend on live OpenGov access.

## Solicitation document manifest and retrieval queue

Georgia GPR, Maryland eMMA, Virginia eVA, California Cal eProcure, Texas ESBD,
and Rhode Island RIVIP now use narrow, fixture-backed
`DocumentCandidate` adapters. Their public attachments enter the same orchestration,
manifest, and bounded retrieval queue used by the existing Oracle, Pennsylvania, and
Tyler integrations; login- or supplier-registration-required rows remain metadata-only.
Stable identity uses a source attachment identifier where present. Virginia's fallback
uses lot, round, and attachment path while excluding transient query parameters. These
integrations are fixture verified rather than live verified and never perform login,
registration, or bid-response actions.

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

### Euna Procurement / Bonfire connector

The `euna/bonfire` connector is a reusable, anonymous, GET-only connector for agency-specific
`https://{tenant}.bonfirehub.com` portals. Registry aliases are `bonfire`, `bonfirehub`,
`euna-bonfire`, `euna-procurement-bonfire`, and `bonfire-interactive`;
the deliberately omitted bare `euna` name prevents collision with IonWave, DemandStar,
EqualLevel, and other distinct Euna product families.

Production presets cover Anacortes (city, WA), Bend (city, OR), Fairfax County Government
(county, VA), Fairfax County Public Schools (school district, VA), Corona-Norco USD (school
district, CA), Florence 1 Schools (school district, SC), Region 10 ESC (cooperative purchasing
organization, TX), and the registration-required Charlotte pilot (city, NC). A non-production
fixture-only tenant demonstrates configuration-driven parsing. Presets are fixture verified,
not proof of live production availability; Charlotte is explicitly `registration_required`.
One tenant is not statewide coverage.

Bonfire is transitioning into Euna Supplier Network branding while agency portals may remain
on `bonfirehub.com`. Supported variants are `bonfire_legacy`, `bonfire_current`,
`euna_branded_bonfire`, `euna_supplier_network_redirect`, `public_upstream_fallback`,
`registration_required_portal`, and `configured_unknown`. Verification/access classification
covers fixture/live public verification, metadata-only, registration/login/CAPTCHA boundaries,
changed markup, migration, blocking, and unavailability. Euna ownership does not make Bonfire,
IonWave, and DemandStar one parser family.

Discovery uses bounded public HTML or explicitly observed fixture-backed JSON, bounded pages and
results, duplicate suppression, exact IDs/numbers, and local keyword/status/department/date
filtering. Semantic listing/detail parsing retains tenant-qualified source identity, raw payload,
field provenance, authoritative portal and configured agency fallback URLs. It recognizes public
document, addendum, Q&A, award and bid-tabulation metadata. Public metadata does not prove public
document access: registration/login/CAPTCHA-gated files remain manifest metadata and are never
queued. Public candidates flow through the shared manifest, safe downloader, parser/targeted OCR,
and structured extraction/reconciliation services; the connector never downloads or parses files.

Each connector instance owns an isolated anonymous client unless one is injected. Requests have
bounded retries (including both Retry-After forms), jitter/backoff, a per-instance tenant circuit
breaker, safe redirect validation, exact approved-host checks, and private/loopback/link-local URL
rejection. No account is created; no login, CAPTCHA, registration, question, addendum
acknowledgement, or response submission is attempted. To add a tenant, create a typed
`BonfirePortal` with its exact `{tenant}.bonfirehub.com` hostname and explicitly enumerate any
agency fallback, CDN, or Euna migration hosts. Pipeline stages remain separated.

Follow-up: SLED Connector PR #18 will add Euna Procurement/IonWave as a separate parser family.
Later work includes DemandStar, PlanetBids, BidNet Direct, Public Purchase, SAP Ariba, Workday
Strategic Sourcing, remaining state systems, a live validation harness, markup-change detection,
preset expansion, scheduled runs, and capability-profile matching.

## Euna Procurement / IonWave connector

Use canonical family `euna/ionwave` (aliases `ionwave`, `ion-wave`,
`ionwave-technologies`, `euna-ionwave`, `euna-procurement-ionwave`, and `iwt`) for
IonWave tenant applications. IonWave is part of Euna Procurement, but it remains a distinct
parser and route family from Bonfire and the future DemandStar connector. The connector uses
anonymous GET requests only: it never creates an account, logs in, registers, submits an ASP.NET
form/view state, acknowledges an addendum, asks a question, or submits a response.

Configured public routes include `/SourcingEvents.aspx?SourceType=1`, the alternate
`/CurrentSourcingEvents.aspx`, and `/PublicDetail.aspx?bidID={BID_ID}&SourceType=1`.
Presentation parameters such as sort, page, row index, and transient ASP.NET state are removed
from canonical detail URLs. If filtering or pagination requires an ASP.NET POST, the connector
uses a bounded initial GET list and local filters rather than submitting the form. Direct public
detail access does not prove that any particular document is public: every attachment is
classified independently, and registration/login-required metadata is retained but not queued.

Production presets are Plano ISD (`pisd.ionwave.net`), Town of Prosper
(`prospertx.ionwave.net`), Clemson University (`clemson.ionwave.net`), University of Missouri
System (`umsystembids.ionwave.net`), Carrollton-Farmers Branch ISD
(`cfbpurchasing.ionwave.net`), MTSU (`mtsource.ionwave.net`), and the Iowa DOT legacy portal
(`iowadotebid.ionwave.net`). A non-production `fixture-public.ionwave.net` preset proves that
routes and parsing are configuration-driven. Variants distinguish classic/modern IonWave,
Euna branding, list/detail capabilities, registration-required access, agency upstream
fallbacks, OpenGov/Bonfire migrations, legacy archives, and unknown configurations.

Discovery supports bounded current, closed, awarded, and canceled metadata where configured,
local keyword/identifier/department/status/date filters, duplicate suppression, direct details,
and explicitly configured authoritative agency fallback pages. Detail fixtures cover labeled
metadata, documents, addenda, Q&A, and awards. Public candidates flow through the shared
manifest and retrieval queue, safe downloader, parsing/targeted OCR, structured extraction,
reconciliation, and effective snapshot services. The connector itself never downloads or parses
files. Redirects and links are restricted to the exact configured IonWave/agency/document hosts;
HTTPS, credential, port, loopback/private/link-local/metadata, and deceptive-host checks apply.
Retries, Retry-After, timeouts, bounded exponential backoff, and per-tenant circuit breakers are
supported without persisting or logging anonymous ASP.NET cookies.

Migration metadata preserves historical IonWave provenance and hands active coverage to
`opengov/procurement` or `euna/bonfire`; retired portals are not represented as active coverage.
Agency fallbacks are explicit and bounded, never arbitrary crawls or third-party aggregators.
Fixture verification is not live proof, and one tenant is not comprehensive statewide coverage.
Registration may be required for access or only for responses, and public details do not prove
public documents. IonWave portals vary by tenant; changed branding and markup are reported
rather than bypassed.

To add a tenant, define an `IonWavePortal` with the exact `{tenant}.ionwave.net` host, route
shapes, capabilities, limits, timezone, verification/access status, and explicitly approved
upstream/document hosts, then add sanitized fixtures. Do not invent attachment routes or enable
POST. Follow-up **SLED Connector PR #19** will add Euna Procurement/DemandStar as another
separate family. Later candidates include PlanetBids, BidNet Direct, Public Purchase, SAP Ariba,
Workday Strategic Sourcing, state-specific portals, scheduled execution, live validation,
markup-change detection, preset expansion, and capability-profile matching.

### PlanetBids agency portals

`planetbids` is the public-read-only connector family for configured, agency-specific
PlanetBids vendor portals. Supported explicit aliases are `planet-bids`,
`planetbids-portal`, `planetbids-vendor-portal`, `pb-system`, and `pbsystem`.
VendorLine is a separate aggregation/subscription product and is neither an alias nor
a data source.

A `PlanetBidsProfile` supplies the agency identity, jurisdiction, official procurement
page, portal/list/detail URLs, approved portal and document hosts, strict collection
bounds, parser variant, access expectation, verification status, and migration or
replacement metadata. Add a profile only after checking an authoritative agency page,
a public PlanetBids page, or a sanitized fixture; record verification notes rather than
assuming all opportunities and files are public. Profiles may be `active`,
`configured_unverified`, `legacy`, `migrated`, or `unavailable`.

Discovery uses bounded anonymous GET requests and fixture-supported embedded JSON or
semantic HTML. It deduplicates tenant-qualified records, detects repeated pages and
changed markup, applies query filters, then retrieves public detail pages. Stable IDs
have the form `planetbids:{profile_key}:{upstream_id}` so identical solicitation
numbers at different agencies never collide. Detail payloads preserve field
provenance, canonical and official URLs, public Q&A, addenda, results, award data, and
per-resource access state when supplied upstream.

Document candidates flow into the existing manifest, safe downloader, parser, targeted
OCR, structured extraction, and version-reconciliation pipeline. Access is classified
per opportunity and file: a public page may mix public attachments with
`login_required`, `registration_required`, `prospective_bidder_required`, restricted,
or invitation-only resources. Only direct public candidates are retrieval-eligible;
gated links remain visible as incomplete-document provenance and are never treated as
failed public downloads.

The connector never registers or authenticates vendors, joins bidder lists, RSVPs,
submits questions, acknowledges addenda, submits bids, accesses sealed responses or
invitation-only solicitations, uses VendorLine paid aggregation, bypasses CAPTCHA, or
circumvents portal controls. It uses no POST navigation. Migrated and inactive profiles
fail closed and retain replacement metadata without relabeling the replacement system.

Fixture-verified behavior demonstrates connector behavior against captured test inputs.
It does not prove that every PlanetBids agency portal, opportunity, or document remains
anonymously accessible. Portal generations and agency configuration differ; unsupported
markup is reported as `changed_markup`. No live profile is enabled by this change.

## Maryland eMMA public connector

Use canonical connector `maryland/emma`; supported aliases are `maryland-emma`,
`emma-maryland`, `emaryland-marketplace`, `emaryland-marketplace-advantage`, and
`md-emma`. Broad names such as `emma`, `maryland`, `marketplace`, `aspnet`, and
`page-aspx` are intentionally not registered. eMMA publishes notices from Maryland
state agencies and participating counties, municipalities, schools, universities,
authorities, and commissions, but this does not imply universal statewide coverage.

The primary surface is Public Solicitations. Bounded anonymous GET discovery and detail
parsing preserve project/solicitation/notice identity, issuing organization, upstream
type (including PORFP and public notice), dates, public UNSPSC codes, explicit SBR/MBE/
WBE/VSBE designations, provenance, results/awards, and independently classified document
links. Notices may identify BidX/Bid Express, Bonfire, Bid Locker, an agency page, or
another response process. Those hints support downstream reconciliation; eMMA never
invokes the other connector or follows a link into submission.

Public files, addenda, Q&A, tabulations, and awards enter the shared manifest, retrieval
queue, SSRF-safe downloader, parsing/targeted-OCR, structured extraction, and version
reconciliation pipeline. Only anonymous direct files are eligible. The downloader still
owns DNS/redirect validation, size/MIME limits, HTML-wall detection, sanitized filenames,
checksums, and archive bounds. An addendum retains its relationship and history; it is not
assumed to replace every earlier document.

CAPTCHA, login, Maryland/MDOT SSO, registration, vendor-profile actions, restrictions,
and external response systems are detected as access boundaries, never empty results.
Public Contracts may independently be `captcha_required` without disabling a public
solicitation surface. The connector never registers, logs in, uses SSO, adds or
acknowledges a solicitation, submits or uploads a response, solves CAPTCHA, accesses an
unpublished sourcing project, or operates BidX, Bonfire, Bid Locker, or any other linked
submission system.

`MarylandEMMAProfile` configures jurisdiction/agency identity, exact portal and document
hosts, public URLs, collection limits, status, markup variant, expected access model, and
verification notes. To add a verified organization or variant, use authoritative URLs,
exact allowlists and bounded limits, then add sanitized fixtures covering its markup and
record the verification timestamp/status. Shared `page.aspx` helpers only parse allow-listed
hidden state and stable links; they do not POST forms, automate ASP.NET, add a browser, or
claim compatibility with unrelated sites.

The included profile and behavior are `fixture_verified`; migrations and unavailable
profiles are modeled explicitly, while untested configurations remain
`configured_unverified`. Fixture-verified behavior proves connector behavior against
captured test inputs. It does not prove that every live eMMA page, agency, solicitation,
contract, or attachment is currently anonymously accessible. No live verification was
performed for this change.

### Georgia Procurement Registry (GPR)

The `georgia/gpr` connector models GPR as Georgia's free public-notification and
bid-advertising layer for state agencies and participating local governments,
universities, authorities, and commissions. Explicit aliases are `georgia-gpr`,
`ga-gpr`, `georgia-procurement-registry`, `ga-procurement-registry`, and
`gpr-georgia`; broad names such as `gpr`, `georgia`, `gawork`, and `marketplace`
are deliberately not registered.

Discovery is anonymous, GET-only, bounded by configured page/result limits, and
supports fixture-verified keyword, title, description, event number, status,
response type, government type/entity, posted/closing/award date, and NIGP
filters. Open, under-evaluation, closed, awarded, and cancelled records retain
structured upstream status and type. Stable identities qualify the raw GPR ID by
profile, with entity and record-type qualifiers when a notice ID indicates a
collision risk. Every extracted source value is retained in the raw payload with
provenance.

Georgia launched **GA@WORK on July 1, 2026**. GPR remains the modeled discovery
and public-notification source, while linked GA@WORK Marketplace, Team Georgia
Marketplace/PeopleSoft, eSource, JAGGAER Sourcing Director, Bid Express,
agency-hosted, offline, and unknown response systems are classified as separate
relationships. Legacy URLs, transition state, external event IDs, and response
URLs are preserved; a link is not assumed public merely because its GPR notice is
public. State migration and local-government notices can therefore coexist
without conflation.

Public GPR attachments, addenda, amendments, Q&A, tabulations, and awards become
access-aware document candidates for manifest reconciliation, the durable queue,
safe download, parsing, targeted OCR, structured extraction, and version
reconciliation. Only anonymously retrievable candidates are queue-eligible.
Login, registration, restricted, migrated, unavailable, external-system, and
unknown resources preserve metadata but are not downloaded. The existing safe
downloader remains responsible for redirect/DNS/SSRF validation, bounds, MIME
checking, HTML-wall detection, checksums, archive safety, and provenance.

The connector does not register, authenticate, use published guest credentials,
submit bids, upload responses, access supplier accounts, invoices, payments or
buyer portals, invoke linked submission systems, or bypass access controls. To
add a verified source variant, create a `GeorgiaGPRProfile` with conservative
bounds, exact HTTPS host allowlists, transition and replacement metadata, and
`configured_unverified` status; add sanitized fixtures before promoting its
verification label.

Fixture-verified behavior demonstrates connector behavior against captured test
inputs. It does not prove that every live GPR, GA@WORK, legacy Team Georgia
Marketplace, JAGGAER, or agency endpoint remains anonymously accessible. Live
markup, redirects, document availability, and response-system access may change;
use `fixture_verified`, `live_public_verified`, `configured_unverified`,
`public_metadata_only`, `registration_required`, `login_required`,
`external_response_system`, `legacy`, `migrated`, `changed_markup`, `blocked`, or
`unavailable` explicitly rather than treating an access boundary as empty data.

### BidNet Direct

The `bidnet-direct` connector supports bounded anonymous metadata discovery for configured
member agencies and regional purchasing groups. BidNet document registration is not
automated, paid geographic aggregation is not used, and robots/CAPTCHA/bot restrictions
are respected. Registration-gated references are preserved without queueing; approved
public agency copies are preferred for retrieval. See `docs/architecture.md` for the
profile, provenance, access-state, and safety model.

### Public Purchase

The `public-purchase` connector is a reusable, profile-driven, public-read-only connector for
configured Public Purchase agency portals, including fixture-verified `/gems/{agency_slug}/...`
routes. Explicit aliases are `publicpurchase`, `public-purchase-portal`,
`public-purchase-gems`, and `the-public-group-public-purchase`; broad terms such as `public`,
`purchase`, `bid-board`, `gems`, and `procurement` are intentionally not aliases. The `/gems/`
route family is a Public Purchase route and is not an unrelated GEMS product. Public Purchase is
distinct from BidNet Direct, PlanetBids, DemandStar/Euna OpenBids, Bid Express/BidX, Public
Surplus, Vendor Registry, OpenGov, and Periscope BuySpeed.

Public Purchase has separate access layers: an agency portal, free vendor account registration,
separate agency enrollment, registered solicitation/document/notification access, electronic bid
participation, and paid Bid Syndication for broader non-member-agency aggregation. Free
registration is still an access boundary, not anonymous public access. The connector collects only
anonymous public metadata, public details, and approved official-agency alternatives. It retains
gated document metadata and links without queueing them; an approved public agency copy is
preferred and may be queued through the existing manifest, safe downloader, parsing, targeted OCR,
extraction, and version-reconciliation pipeline.

Records use the stable identity `public-purchase:{profile_key}:{opportunity_id}` and preserve raw
opportunity and agency identifiers, canonical and discovered URLs, official agency URLs, field
provenance, and one of `public_purchase_member_agency`, `official_agency_mirror`,
`syndicated_external_notice`, or `unknown`. Paid syndicated notices are not collected and Public
Purchase is not represented as their authority.

Profiles specify the jurisdiction and government level, agency name/slug/identifier, explicit
Public Purchase and official procurement URLs, a fixture-supported listing and detail route,
approved platform and agency document hosts, access expectations, bounds, statuses, parser
variant, lifecycle status, verification information, and migration replacement. To add a profile,
capture sanitized anonymous fixtures, use only observed routes, explicitly allow every host, set
small page/result bounds, validate access-wall behavior, add registry/parser tests, and record a
verification label and timestamp. Supported lifecycle states include active, legacy, migrated,
configured-unverified, and unavailable. Verification labels include `fixture_verified`,
`live_public_verified`, `configured_unverified`, metadata/gating states, policy blocks,
`changed_markup`, `blocked`, migrated, and unavailable.

The connector respects robots.txt, login and registration walls, agency enrollment, CAPTCHA, and
technical blocks, and fails closed as changed markup rather than reporting a false empty result. It
does not register, enroll with agencies, authenticate, subscribe, use Bid Syndication, automate
notifications, submit questions, acknowledge addenda, submit responses, upload files, bypass
CAPTCHA, or evade robots or technical restrictions. Fixture verification demonstrates behavior
against captured test inputs. It does not prove that every live Public Purchase agency,
opportunity, or attachment remains anonymously accessible.

### Rhode Island RIVIP External Solicitations

`rhode-island/rivip-external` collects bounded anonymous notices for Rhode Island external
entities: municipalities, schools, higher education, quasi-public agencies, authorities,
commissions, grants, delegated authorities, and other explicitly listed entities. Supported
aliases are `ri-rivip-external`, `rhode-island-rivip`, `rivip-external`,
`ri-external-solicitations`, and `rhode-island-external-solicitations`; broad aliases are rejected.

This source is separate from OSP/WebProcure, RIFANS, BidNet Direct, RhodyBuy, legacy RIVIP, and
the public-copy response repository. Allowlisted Web Forms POSTs perform only anonymous search or
pagination, refresh hidden state, and are bounded. No business record is modified. The connector
never authenticates, registers, uses agency posting, posts or bids, accesses RIFANS or financial
data, solves CAPTCHA, invokes response systems, or broadly ingests vendor responses.

IDs use `rhode-island/rivip-external:{entity_key}:{external_bid_id}`. Historical and migrated
records preserve RIVIP authority and replacement hints. Anonymous solicitation, addendum, result,
and award files use the shared document pipeline; responses and gated links cannot. Fixture
verification demonstrates behavior against captured inputs, not universal live accessibility.

## Nationwide coverage audit

The offline coverage control plane audits **56 primary jurisdictions**: 50 states, the District of
Columbia, and five inhabited territories. Tribal procurement is a separate future coverage layer.
As of 2026-07-30 it inventories 20 implemented connector families and 8 conservatively evidenced
source profiles; 49 jurisdictions have no configured source in this initial registry. All 8 seeded
profiles are fixture-verified, so none is represented as live or production-verified and none
currently qualifies as complete public document-pipeline coverage.

See the [full generated audit](docs/sled_coverage_audit.md), its
[JSON](reports/sled_coverage_audit.json), and [CSV](reports/sled_coverage_audit.csv). Regenerate them
without network access:

```bash
PYTHONPATH=src python -m sled_aggregator.coverage validate
PYTHONPATH=src python -m sled_aggregator.coverage report --format json --as-of 2026-07-30 --output reports/sled_coverage_audit.json
PYTHONPATH=src python -m sled_aggregator.coverage report --format csv --as-of 2026-07-30 --output reports/sled_coverage_audit.csv
PYTHONPATH=src python -m sled_aggregator.coverage report --format markdown --as-of 2026-07-30 --output docs/sled_coverage_audit.md
```

A configured profile is not production verification. Fixture verification is not live
verification, metadata access is not document access, and statewide sources do not imply complete
local, education, transportation, authority, or quasi-public coverage.

### Oracle Fusion public REST

`oracle/fusion-rest` is a reusable anonymous, GET-only connector for versioned Oracle Fusion
Procurement REST resources. Its sole production preset is City of Detroit (`mi-detroit-oracle-fusion`,
BU `300000007775375`). Discovery uses bounded `limit`/`offset` pages and allowlisted filters and
sorting; attachment metadata, stable REST enclosure downloads, and amendment metadata are supported.
Temporary Oracle signed `FileUrl` values are redacted and never become durable document URLs.

The connector never logs in, accepts supplier credentials, imports browser cookies, submits bids or
responses, automates CAPTCHA, or falls back to stateful ADF POST traffic. Lucas County (OH),
Jacksonville (FL), Virginia Beach (VA), and DC Water are researched legacy ADF tenants and are
intentionally unsupported. Sanitized fixture evidence is not a guarantee of permanent live access.

### Tyler Munis Vendor Self Service

The reusable `tyler/munis-vss` connector provides bounded, anonymous public discovery
for Summit County, Ohio and the City of Opelika, Alabama. Public Web Forms search,
pagination, and detail selection use fresh ASP.NET state via POST; document retrieval
remains GET-only through the existing safe downloader. Temporary document tokens are
redacted and excluded from identity, login/restricted transitions fail closed, and
Mobile, Alabama remains unsupported because only citizen self service was evidenced.
See [the connector support guide](docs/tyler_munis_vss.md).

### Official public procurement feed evidence gate

The proposed `official/public-feed` family is **not implemented**. A 2026-07-31
review could not reproduce a qualifying authoritative feed contract because the
task environment's outbound proxy rejected destination connections. Candidate
official properties are not presets or jurisdiction coverage, and no response
schema or fixture was invented. See the
[evidence record](docs/official_public_feed_evidence.md) for candidates,
limitations, and the exact evidence required to resume. Coverage recommendations
now label this family `unsupported_candidate` rather than implementation-ready.

### Vendor Registry evidence gate

Vendor Registry is **not implemented**. The 2026-08-01 review could not reproduce an
anonymous, agency-scoped listing contract for two independently operated agencies: outbound
HTTPS was rejected before destination TLS and no manual capture was available. Search-indexed
detail routes do not prove discovery, and no tenant identifier, request, pagination, document
behavior, fixture, preset, or jurisdiction coverage was inferred. Public agency solicitations
also remain distinct from vendor registration, accounts, electronic responses, and the paid Lead
Center. See the [Vendor Registry evidence record](docs/vendor_registry_evidence.md) for candidates,
unknown authentication/CAPTCHA/document findings, and the bounded HAR procedure needed to resume.
