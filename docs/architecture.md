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

## Document pipeline

The later document service will support PDF, Office files, HTML, text, CSV,
images, and ZIP packages. OCR runs only on pages that do not contain usable
embedded text. ZIP expansion is temporary and enforces configurable limits for
bytes, file count, depth, encryption, paths, compression ratio, and type.

Restricted documents produce metadata and a source link. User-authorized or
user-uploaded retrieval is a separate future channel and must not weaken public
connector controls.

