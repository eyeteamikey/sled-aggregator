# Backend architecture

## Purpose

The service collects public SLED and Tribal solicitation metadata and selected
documents, normalizes them, and exposes structured intelligence to downstream
matching and teaming workflows.

## Boundaries

The service is read-only with respect to procurement portals. It does not:

- submit bids or accept terms on behalf of a user;
- bypass CAPTCHA or automate authenticated vendor sessions;
- evade robots.txt, rate limits, or explicit access restrictions;
- treat broad nationwide scraping as the default integration strategy.

## Processing flow

1. A platform-family connector discovers source opportunities.
2. The connector emits `RawOpportunity` records with source provenance.
3. The normalizer produces a canonical opportunity and deterministic key.
4. Attachment metadata is classified as include, exclude, review, or restricted.
5. Eligible public documents enter a bounded retrieval and extraction pipeline.
6. Text and structured facts retain page, sheet, section, or block provenance.
7. The active record exposes the newest valid document representation.
8. Downstream services consume the same record for matching, teaming,
   bid/no-bid, compliance, alerts, search, and exports.

## Connector strategy

Connectors represent platform families—such as WebProcure/Proactis, OpenGov,
Bonfire, DemandStar, PlanetBids, or jurisdiction-specific legacy systems.
Jurisdiction configuration supplies tenant identifiers, public entry points,
rate limits, and field mappings without duplicating transport code.

### WebProcure/PROACTIS connector

One configurable, asynchronous, GET-only connector covers Connecticut
(CTsource, customer 51), Missouri (legacy bid board, customer 38), and Rhode
Island (Ocean State Procures, customer 46 and owner OID 120002). Search is
bounded by page size, maximum pages, and query result limit. Records are
deduplicated by source opportunity ID before canonical `RawOpportunity`
mapping, and the complete source record is retained as provenance.

The connector uses an authoritative record URL when public search supplies one.
When it does not, it preserves discoverability through the jurisdiction's
public bid-board URL. It never follows that fallback into login walls or
restricted-document retrieval and does not support submission, registration,
CAPTCHA bypass, credential storage, or any other portal mutation.

The public full-text endpoint is known to experience production 502 and 503
outages. Connection failures and transient 429, 502, 503, and 504 responses use
bounded retries, exponential backoff, jitter, and numeric or HTTP-date
`Retry-After` values. Consecutive failed collection runs feed a configurable
circuit breaker and health snapshot; a successful JSON response resets failure
state. Non-JSON, malformed JSON, and unexpected response shapes fail closed.

### Periscope S2G/BuySpeed connector

The `periscope/buyspeed` connector is a platform-family adapter with separate
portal presets for BidBuy (Illinois), COMMBUYS (Massachusetts), NevadaEPro,
NJSTART (New Jersey), OregonBuys, and GVIBUY (U.S. Virgin Islands). Configuration
owns public entry/search and detail URLs, variant, response strategy, request
parameters, pagination origin, aliases, date formats, headers, optional public
session initialization, and document-session requirements. This prevents an
assumption observed on one BuySpeed deployment from silently becoming behavior
for all deployments.

The connector performs only public GET requests. JSON, HTML, and hybrid
list/detail strategies normalize valid records into `RawOpportunity`; complete
source fields and discovered document-link metadata stay in `raw_payload` for
provenance. Pagination and results have independent hard caps, stable source IDs
are deduplicated, repeated pages terminate discovery, and invalid required fields
increment an observable skip count. When safe anonymous discovery is not
configured, a preset can provide only its authoritative bid-board fallback and
report `unsupported` rather than inventing results.

Login and expired-session content returned with HTTP 200, authentication
redirects, CAPTCHA/bot challenges, and 403 responses are explicit restricted
states. Document links are metadata only and identify public,
anonymous-session-dependent, or restricted access; no document extraction, OCR,
login, challenge bypass, or bid workflow belongs to this connector.

Retries are bounded and cover connection failures plus 429, 502, 503, and 504,
with exponential backoff, jitter, and numeric or HTTP-date `Retry-After` support.
Repeated failed discovery runs open a cooldown circuit. Health includes portal,
jurisdiction, availability, access state, circuit state, failure count, last
status, failure/success timestamps, and skipped records. Caller-injected
transports remain caller-owned; connector-created clients are closed by the
connector.

Production verification is intentionally separated from parser assumptions:
the six authoritative public portal entry points and platform identification are
documented, while anonymous endpoints and response mappings are currently marked
unverified. Tests use synthetic, non-sensitive fixtures and injected transports
only and never depend on live portal availability. Live verification, richer
variant adapters, and document retrieval are deferred follow-up work.

## Document pipeline

The later document service will support PDF, Office files, HTML, text, CSV,
images, and ZIP packages. OCR runs only on pages that do not contain usable
embedded text. ZIP expansion is temporary and enforces configurable limits for
bytes, file count, depth, encryption, paths, compression ratio, and type.

Restricted documents produce metadata and a source link. User-authorized or
user-uploaded retrieval is a separate future channel and must not weaken public
connector controls.

### Extraction implementation

`DocumentExtractionService` loads immutable artifacts only through `DocumentStorage`,
then delegates content selection to `DocumentParserRegistry`; persistence, parsers, OCR
policy/provider, normalization, and the bounded worker remain separate. Magic bytes and
safe OOXML container members outrank detected/declared media types and extensions.
Mismatches become warnings, while malformed, unsupported, or hostile inputs receive an
explicit terminal classification.

The extraction tables are `document_extractions`, `document_text_blocks`, and
`document_tables`. They link opportunity → manifest document → downloaded artifact,
retain source URL metadata and artifact hash, and preserve page/sheet/table/paragraph/
archive coordinates. Full text is reconstructed from ordered bounded blocks rather than
stored as an unbounded opaque diagnostic object.

Defaults cap artifacts at 100 MiB, extracted text at 5,000,000 characters, blocks at
10,000, tables at 1,000, PDFs at 500 pages, and OCR at 25 pages/25 million pixels.
Spreadsheets cap 50 sheets, 100,000 rows, 1,000 columns, and 1,000,000 cells. ZIP caps
100 entries, 25 MiB per entry, 100 MiB total, a 100:1 ratio, and zero nested depth.

OCR thresholds are deterministic and page-specific: 40 alphanumeric characters, five
words, and at most 5% Unicode replacement characters constitute usable native text.
Only deficient pages with raster images require OCR. Blank pages do not. The optional
Tesseract provider uses a fixed argv vector, no shell, a timeout, configurable English
language default, and an availability/version health check. A production renderer is
deferred, so image-only PDFs clearly report unavailable instead of rendering all pages.

Extraction states include completed, completed-with-warnings, unsupported, malformed,
failed, and quarantined; OCR reports not-needed, partially/fully-used, unavailable, or
failed. Follow-up PR #15 will add structured RFP/SOW/PWS extraction and version
reconciliation. PR #16+ resumes OpenGov Procurement/ProcureNow connector-family work.
Later work includes isolated legacy Office conversion, production OCR images/languages,
malware scanning, object storage, exports, full-text/hybrid search, live validation,
evaluation integration, and authorized reprocessing controls.

### JAGGAER/SciQuest public event connector

`jaggaer/sciquest` separates tenant configuration from shared request,
classification, list/detail parsing, normalization, and document-link
classification. Presets model Utah U3P, UW System ShopUW+, Georgia Sourcing
Director, and Iowa IMPACS without assuming identical markup or claiming broader
statewide coverage. CustomerOrg, entry/discovery URLs, tab and event-number
parameters, headers, remote-versus-local keyword behavior, parser strategy,
detail/document capabilities, request/page/result bounds, retries, and circuit
settings are tenant facts. Additional tenants require configuration, not another
connector class.

Only anonymous public GET requests are allowed. Per-instance clients isolate
tenant cookies; connector-owned clients close while injected clients remain
caller-owned. Stable JAGGAER IDs take precedence over tenant-qualified event
numbers and deterministic stable-attribute hashes. Detail data and document
metadata remain in raw provenance, including upstream registry links. Supplier
response registration does not make otherwise public event metadata restricted,
while individual login-gated files retain their own access state.

URL validation permits reviewed HTTPS hosts only and rejects credentials,
loopback/private/link-local/metadata destinations, foreign document hosts, and
unsafe schemes. Pagination, redirects, response size through the HTTP client,
retries, and results remain bounded. CAPTCHA, login/registration pages,
JavaScript-only shells, malformed shapes, and non-HTML/non-JSON responses fail
closed. Per-tenant retry and circuit state prevents one CustomerOrg outage from
disabling another. Fixture/fake-transport tests never contact JAGGAER. This stage
discovers links only: file download, structured extraction, OCR, authenticated
supplier workflows, POST searches, and CAPTCHA handling are deliberately absent.

### Infotech Bid Express / BidX connector

The `infotech/bid-express` family adapter separates five configurable product
variants: legacy and modern BidX, general Bid Express, Infotech Express, and an
unknown variant for safely modeled deployments. BidX primarily describes DOT
lettings, proposals, construction documents, and bid results; Bid Express also
covers local-agency construction and general procurement. Variant membership
does not imply common endpoints, schemas, sessions, agency identifiers, or
access policy.

Agency configuration records agency, jurisdiction, variant, public base and
listing/fallback URLs, verified identifier (when known), detail/document
behavior, verification state, and access notes. The configured-only catalog
mirrors the 39-state public directory coverage and named authority/division
entries requested for this integration, but deliberately supplies no inferred
IDs. Directory discovery can configure multiple agencies without separate
connector classes. An authoritative directory fallback is retained where an
anonymous opportunity route has not been verified.

The adapter uses only bounded public GET navigation. Independently capped
pagination/results, repeated-page fingerprints, stable-ID deduplication,
keyword/jurisdiction/agency parameters, and optional public session and detail
requests work with configured HTML, JSON, XML, CSV, or hybrid parsing. Canonical
fields are populated where the compact domain model supports them; all remaining
letting, proposal, location, route, project, contract, code, work type,
participation goal, contact, estimate, award, and bid-result provenance remains
in each raw payload.

Discovered solicitation and result documents are metadata only. Links retain
title, URL, parent opportunity, apparent extension, session need, link-only
status, and public, registration, login, subscription, payment, or Digital ID
classification. HTTP 200 access, CAPTCHA, maintenance, and generic-error pages,
redirect targets, and forbidden responses fail closed and never become empty
successful discovery. No authenticated, paid, submission, or challenge-bypass
workflow exists.

The resilience lifecycle includes request timeouts, bounded connection and
429/502/503/504 retries, exponential backoff and jitter, both `Retry-After`
forms, cooldown circuits, reset on success, and variant/agency/access-aware
health. Injected clients remain caller-owned; connector-created clients close
with the connector. Synthetic fixtures cover formats, pagination, documents,
access boundaries, resilience, and ownership without contacting production.
The directory catalog is configured-only, not a live-support guarantee. Endpoint
verification, richer canonical fields, public directory parsing into persisted
configuration, production monitoring, document retrieval/extraction, and OCR
remain deferred.

### Oracle PeopleSoft public sourcing connector

`oracle/peoplesoft-sourcing` is the reusable, asynchronous adapter for public
PeopleSoft Supplier Portal and Strategic Sourcing components. Deployment
configuration owns authoritative entry and fallback URLs, response formats,
field and query aliases, date formats, component/page hints, public guest
context, department identifiers, and package, attachment, UNSPSC, and service
area behavior. Cal eProcure / FI$Cal is the first preset, not a claim that all
PeopleSoft installations share California's behavior.

Anonymous landing cookies remain inside the HTTP client and hidden form fields
remain ephemeral connector state; neither is persisted in an opportunity.
Only GET navigation is implemented. Login, registration, bid response, Digital
ID, account management, payment, private communication, CAPTCHA bypass, and
restricted attachment retrieval are outside the connector boundary.

Search and parsing support configured HTML, PeopleSoft partial pages, JSON,
XML, and CSV. Independent page and result caps, repeated-page detection, stable
ID deduplication, detail enrichment, and malformed-record skips prevent
unbounded or misleading collection. Stable California identity combines
jurisdiction, Business Unit, and Event ID. Rounds and versions describe the
same underlying event by default and are retained in provenance rather than
creating duplicates.

Document discovery is link metadata only. It classifies likely solicitation
packages and attachments, omits entries explicitly marked superseded, and
retains access and anonymous-session requirements. HTTP 200 login,
registration, expired-session, CAPTCHA, maintenance, and authorization pages
fail closed. Retries, both `Retry-After` forms, jitter, cooldown circuits,
health state, and caller/connector transport ownership follow existing connector
conventions.

CI is entirely sanitized and fixture-driven. The Cal eProcure public entry and
fallback are configured, while component search, guest detail, package,
attachment, and pagination behavior is fixture-verified but not live-verified.
Adding a portal requires independently verifying its public route and boundary,
then supplying a new `PeopleSoftSourcingPortal`; temporary state must never be
copied between deployments.

### Virginia eVA connector

`virginia/eva` is intentionally jurisdiction-specific rather than advertised as
a generic CGI Advantage/VSS adapter. `EVAPortal` owns the authoritative public
search and Virginia Business Opportunities board routes plus both observed
detail variants. Transport/session/search mechanics, tolerant HTML parsing, and
normalization remain separate. Query, page, result, and detail caps prevent an
unbounded historical crawl; empty results, repeated pages, access changes, and
open circuits terminate collection.

The eVA lot identifier is the persistence-facing source ID. Rounds are revisions
of that identity: records are grouped by lot and the highest current round wins,
while all observed rounds remain in provenance. Current detail URLs retain the
variant, lot, and round; `PageTitle` is never identity. Earlier documents remain
when useful (especially addenda), while every discovered link records its own
round and access classification.

Access detection examines successful HTTP bodies and redirect destinations for
supplier/buyer login, registration, session expiry, authorization, maintenance,
CAPTCHA, and unusable JavaScript shells. HTTP 403 is a terminal forbidden state,
not an empty board or a transient retry target. The adapter does not log in,
register, submit responses, accept terms, evade robots directives, solve
challenges, or retrieve account-only files. Anonymous cookies stay within the
connector-owned HTTP client and are never copied into raw payloads.

Sanitized fixtures verify both detail strategies, round consolidation, changed
deadlines, document/addendum/account-link classification, malformed records,
access pages, transient retries, circuit recovery, health, and ownership. Live
checks on July 29, 2026 were blocked by the cloud CONNECT proxy for robots.txt,
PublicSearch, the board, open filtering, and the County of Roanoke filter; thus
the origin's anonymous-session, redirect, document, and markup behavior remains
unverified here. Diagnose changes with one respectful robots request, then one
search/board request and a detail link already present on that board; compare
sanitized markup with parser fixtures, stop on blocking, and never enumerate lot
or round IDs. Document retrieval/extraction, OCR, authenticated workflows,
generic CGI inheritance, and production availability monitoring are deferred.


### Texas ESBD connector

`texas/esbd` is separate from Texas SmartBuy contract/catalog data and from
CMBL/vendor records. `ESBDPortal` contains the official SmartBuy origin, ESBD
entry, and configurable detail template; `ESBDQuery` contains anonymous search
filters. Transport, parsing, access classification, and normalization remain in
the connector layer.

Identity prefers the official ESBD record ID. The fallback is agency/member
number plus solicitation ID, never title or an attachment ID. It remains stable
across ordinary addenda and award reappearance. Collection emits no destructive
absence event: Texas guidance describes a post-deadline period when a record can
disappear until its award posts. Provenance records observation time, verbatim
status, and `retain_last_known; absence_is_not_deletion`.

The label-oriented parser tolerates missing optional fields but requires source
or solicitation identity plus title and agency. Deadlines use the IANA
`America/Chicago` zone, not a fixed offset; missing or malformed times are not
inferred. Raw records retain displayed NIGP, deadline, value, quantity, contact,
HUB/HSP, conference, award, and addendum information. Only outbound NIGP search
values have punctuation removed.

Documents retain title, filename/type, category, version, date, access, parent
identity/URL, exact source URL, and internal-media/external classification. Only
HTTP(S) is accepted. NetSuite-style media parameters and hashes are never
removed, reconstructed, shared, or enumerated. External response/account links
are preserved without automating authentication or submission.

Page, detail, result, concurrency, retry, and timeout bounds prevent unbounded
crawls. Duplicate records and repeated-page fingerprints stop predictably. Only
connections and HTTP 429/502/503/504 retry, with both Retry-After forms,
exponential delay, jitter, circuit health, and safe client ownership. HTTP 200
login, CAPTCHA, maintenance, empty-error, and incompatible pages fail closed.

Research began with the Comptroller outreach, vendor information, members, and
registration pages, the GLO doing-business page, ESBD landing route, and
robots.txt. On July 29, 2026 all were `blocked` by the execution environment's
CONNECT proxy with HTTP 403 before an origin response. Thus the public GET model,
filter names, ordering/caps, pagination, wildcard/ID behavior, session/cookies,
redirects, robots policy, structured traffic, detail template, and attachment
delivery are `configured_unverified`. Sanitized lifecycle, timezone, identity,
document, false-success, resilience, ownership, and registry behavior is
`fixture_verified`. Later validation should inspect the landing form/network
first, then only one Posted, agency 305 Posted, agency 305 Awarded, and NIGP
search, one linked detail, one exactly exposed attachment, and robots.txt. Stop
on login, CAPTCHA, restriction, or throttling.

### Pennsylvania eMarketplace connector

`PennsylvaniaEMarketplaceConnector` is jurisdiction-specific because the public
eMarketplace WebForms schema and lifecycle are Commonwealth-owned. Its official
routes are `Search.aspx`, `Solicitations.aspx?SID=…`, `Procurement.aspx`,
`Procurement_Details.aspx?id=…`, and `bidtabs.aspx`; detail-page links may also
identify official awards and contracts. Search transport stays outside domain
models and performs anonymous GET initialization followed by public WebForms
POSTs. Naming-container prefixes are tolerated, but form field names are
explicit. `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, event
target/argument, cookies, and session state are ephemeral and excluded from raw
payloads and sanitized fixtures.

Each current, archived, and upcoming lane has independent page fingerprints and
strict page, page-size, result, detail, concurrency, retry, and refresh bounds.
Current and archive do not silently substitute for each other. SID is the
solicitation identity; upcoming ID is namespaced separately; agency plus exact
string solicitation number is the last source-derived fallback. Title never
drives identity or upcoming-to-solicitation reconciliation. Disappearance is
not deletion: archive reconciliation and retention of the most recent version
are persistence-layer policy.

Official type, advertisement, status, description, agency/department, county,
delivery, contact, Small Business, SDB/VBE, prepared/start/amended/due/opening,
duration, and related-link values remain in provenance. Canonical lifecycle maps
only supported meanings; Created and unfamiliar states remain unknown. Upcoming
procurements are canonical forecasts, never open solicitations. Eastern dates
use the IANA zone and a missing due time produces no inferred midnight. Opening
time never substitutes for due time. The document-control warning is recorded
so later retrieval can compare advertisement metadata with authoritative
solicitation content without this connector guessing.

Document metadata preserves exact safe HTTP(S) URLs, displayed name, apparent
type, section, category/version/date, parent, internal/external class, access,
and retrieval eligibility. Original files, addenda, bid tabs, awards, and
contract references remain distinguishable. A tabulation is not an award and
the lowest bidder is never inferred to be the winner; the portal's 90-day bid
tab archival is a lifecycle transition. ZIPs are not opened here, nor are
documents downloaded, parsed, or OCRed.

Supplier Portal, JAGGAER, ECMS, agency plan rooms, and public external hosts are
classified rather than traversed. Login, registration, MFA, CAPTCHA, stable 403,
restricted, maintenance, malformed shell, and external-account states are
terminal. Transient requests use bounded retry/circuit conventions. PennDOT
ECMS highway/bridge work, COSTARS, vendor registration/search, authenticated
response and qualification, catalog/purchase-order/spend data, and
non-eMarketplace local entities remain explicit coverage gaps.

Official research also includes Pennsylvania DGS Finding Opportunities,
Materials and Services Procurement, and Supplier Service Center guidance. Live
validation status and exact requests are recorded in the pull request; all CI
behavior is fixture-verified with injected transports and no live state.

Live validation on July 29, 2026 attempted exactly one GET each for `robots.txt`,
`Search.aspx`, `Procurement.aspx`, and `bidtabs.aspx`. Every request was `blocked`
by the execution environment's CONNECT proxy with HTTP 403 before reaching the
Commonwealth origin. No POST, detail, document, archive, exact-number, award, or
contract request was attempted after robots access failed. Consequently the
route and form configuration is `configured_unverified`; parser, WebForms-state,
filter, pagination, lifecycle, document, access, resilience, and registry
behavior is `fixture_verified`. A future respectful check must fetch robots
first, inspect actual field names and form action, then perform only one bounded
current search, one exact-number lookup from that result, its linked detail and
one exposed file/addendum, one bounded archive search, one upcoming page, and
one linked tabulation/award. Stop on restriction, login, CAPTCHA, or throttling.

## CGI Advantage VSS connector family

`CGIAdvantageVSSConnector` is a tenant-configured adapter rather than three
jurisdiction-specific implementations. `CGIAdvantageVSSPortal` holds the
Advantage4, AltSelfService, or link-only variant and all tenant facts: routes,
response strategy, IANA timezone, guest/session requirements, independently
verified search/detail/attachment/award/contract capabilities, validation state,
restrictions, allowed attachment hosts, availability policy, and enabled state.
The initial catalog contains Maine, Michigan SIGMA, and ColoradoVSS. Unverified
presets fail closed before transport; a future deployment can be added without a
new connector class, but CGI branding is not verification.

The collection pipeline is:

1. Reject disabled or unverified public search and an open tenant circuit.
2. If configured, load the official landing page and follow only its public guest
   action; keep cookies in that connector instance's in-memory client.
3. Build a bounded tenant search with conservative filters, terminate on a
   repeated page, and deduplicate by tenant plus stable internal ID or complete
   solicitation number.
4. Optionally enrich from a verified detail route. Nonempty detail fields
   supplement list fields; empty values do not erase list data.
5. Normalize the parent opportunity while retaining original fields, dates,
   status/type, commodity lines, instructions, explicit awards, contract links,
   attachment metadata, access state, validation level, and source route in raw
   provenance.

A guest session may be refreshed once after explicit expiry. Login,
registration, verification, invitation-only, CAPTCHA, forbidden, maintenance,
scheduled-unavailable, empty SPA, malformed, and SSO/login redirects are
classified as false-success/access outcomes instead of empty search results.
Transient 429/502/503/504 and connection failures use bounded backoff and
`Retry-After`; health and circuit state belong to the tenant connector instance.
Caller-injected transports remain caller-owned, while connector-created clients
are closed by the connector.

Solicitation IDs are never numeric. Tenant namespacing prevents the same number
on Maine and Michigan from colliding. A trailing component is retained as
round/version provenance but is not assigned semantics without source evidence.
Lifecycle mapping is deliberately narrow: closing is not an award, an empty
award area is not no-award, and only explicitly displayed awardees and amounts
are retained. Commodity lines remain children of one opportunity, preserve
unknown taxonomies, and are not summed or translated to NAICS.

Attachment URLs are resolved only from source-provided links. Unsafe schemes,
URL credentials, private/local address literals, metadata names, and unapproved
cross-tenant hosts are rejected. Metadata discovery never guesses attachment
IDs, downloads every file, extracts text, invokes OCR, opens a response
workspace, or executes archives/macros. The later document retrieval pipeline
must use the same tenant session when public access requires it, validate every
redirect and final host, cap bytes/archive entries, verify content rather than
extension, and classify HTML login content as restricted.

Validation on 2026-07-30 was blocked by the execution network's HTTP 403 proxy
policy for all official application and robots routes. Therefore Maine is
fixture-verified and capability-gated, while Michigan and Colorado remain
configured-unverified and disabled. No structured background endpoint is
claimed. Maine's documented October 1, 2025 RFP transition is a source boundary;
older Maine archive pages are outside this connector. Colorado's published
availability windows are modeled as tenant configuration but no exact hours are
hardcoded without successful current validation. Fixtures are sanitized HTML
representations of both branded landing variants and shared semantic detail
concepts, with no cookies, CSRF material, credentials, vendor-private data, or
bid responses.

The public-only boundary excludes login, registration, account activation,
MFA/verification, vendor maintenance, invoices, payments, private purchasing
history, invited events, response workspaces, questions, amendment
acknowledgement, pricing/upload, bid submission, CAPTCHA bypass, and access-control
circumvention.

## Document coordination layer

`solicitation_documents` preserves normalized classification, authoritative/original URLs,
provenance, access state, relationship/version metadata, and nullable future artifact fields without
storing bodies or extracted text. `document_retrieval_jobs` is the one-to-one durable work record.
The retrieval state machine is centralized: discovered becomes eligible/ineligible; eligible becomes
queued; queued becomes leased/canceled; leased becomes downloading (or queued after expiry);
downloading becomes downloaded, unchanged, an access boundary, not-found, or failed; failed may be
retried; downloaded may be superseded; safe nonterminal states may be quarantined.

Upsert and enqueue share a database transaction. Unique scoped identities and one job per document
resolve concurrent insert races at the database boundary. PostgreSQL claims use row locks with
`SKIP LOCKED`; lease tokens prevent stale acknowledgements. Unit tests structurally verify generated
PostgreSQL SQL; a live PostgreSQL concurrency environment is still needed to validate multi-worker
runtime behavior.

Structured logs should identify document/job IDs, connector, tenant and state plus sanitized
host/path only. Query strings, cookies, credentials, raw payloads, bodies and internal errors are not
logging material. Pipeline counts are available through the bounded queue-statistics API.

## Public document retrieval

`documents.policy`, `fetcher`, `validation`, `storage`, and `worker` separate URL policy, HTTP redirects/streaming, MIME/access-page classification, atomic storage, and lease-aware persistence. Append-oriented `document_artifacts` retains each distinct manifest hash; `document_download_attempts` holds bounded audits. Safe read metadata excludes storage keys and lease credentials.

Workers claim PR #12 jobs using `FOR UPDATE SKIP LOCKED`, commit before I/O, then recheck owner, token and expiration before persistence. Lease loss prevents acknowledgement. Transient failures reschedule with bounded backoff; permanent access/policy/validation outcomes are terminal. Since storage and PostgreSQL cannot be atomic together, deterministic keys, verification and artifact lookup enable idempotent reconciliation.

Production should add egress controls, tenant-approved portal/CDN hosts, durable private volumes and an external scheduler. Future work is PR #14 parsing/targeted OCR, PR #15 structured extraction/version reconciliation, object storage, malware scanning, retention, authorized operations, live validation, downloads and evaluation integration.
