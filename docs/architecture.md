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
