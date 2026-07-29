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
