## Motivation and root cause

Document infrastructure existed, and several connectors discovered attachments, but normal opportunity ingestion accepted only `RawOpportunity`. It discarded the separate canonical candidates returned by Oracle and Tyler detail hydration, while Pennsylvania retained normalized links only in `raw_payload`. No collection-to-manifest orchestration entry point existed. Coverage tiering also inferred pipeline support from public links rather than a verified connector capability.

## Description and end-to-end flow

This change adds one reusable, non-networked orchestration service and an optional collection handoff:

connector discovery/detail → opportunity persistence → candidate normalization → manifest upsert → version reconciliation → eligibility classification → bounded retrieval queue → existing safe downloader → parser → targeted OCR when needed → structured extraction.

The service checks the persisted parent and candidate provenance, applies category and run limits, preserves restricted metadata, suppresses duplicates, and returns a structured operational summary. The collection path remains compatible with connectors that return no documents.

## Connectors integrated

- Oracle Fusion REST (City of Detroit): existing detail attachment candidates.
- Pennsylvania eMarketplace: adapter for normalized `document_links`.
- Tyler Munis/VSS (Summit County and Opelika): existing detail candidates with redacted transient URL metadata and deterministic source IDs.

Other document-link families remain unclaimed pending adapter evidence.

## Manifest, queue, versions, and security

Stable identity includes connector, opportunity, stable source document ID (or sanitized fallback), and version evidence. Logical identity reconciles versions, prevents older rediscovery from replacing newer content, and retains lineage. Existing uniqueness constraints suppress duplicate manifests and jobs. Only confirmed public, current, eligible records can enqueue; restricted records remain metadata-only. Ingestion never downloads and URL validation/canonicalization continues to reject unsafe destinations and strip transient parameters.

## OCR and processing

The existing downloader/extraction workers remain stage boundaries. Successful downloads hand off to parsing; native-text PDFs bypass OCR while insufficient/image-only pages use the existing bounded OCR policy before structured solicitation extraction.

## Testing

Added fixture-shaped tests for collection handoff, documentless connectors, and Pennsylvania public/restricted normalization. Existing Oracle, Pennsylvania, Tyler, manifest, SSRF/downloader, parsing, OCR, structured extraction, and coverage suites provide regression coverage. No live portal download is claimed.

## Migration

No schema migration is required. Existing manifest and queue uniqueness constraints support this orchestration path.

## Coverage

Pipeline compatibility is now derived from an explicit connector implementation capability plus source access evidence, fixture references, and tests. The four evidence-backed source presets count; generic public document-link claims do not.

## Known limitations

Retrieval remains disabled by default at the downloader boundary. Tyler expired-link reacquisition still requires the connector detail workflow to be invoked by a future retry coordinator; no session state or raw token is persisted. The remaining audited connector families require separate canonical adapters and fixtures.
