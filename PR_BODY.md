## Motivation

Connect Georgia GPR, Maryland eMMA, and Virginia eVA's existing document-link
contracts to the shared document orchestration path without introducing retrieval in
connector discovery.

## Prerequisite verification

The Codex Cloud workspace started at merge commit `fc262b6`, “Merge pull request #32
from eyeteamikey/codex/prepare-codex-cloud-pr-for-document-pipeline”. Master content
includes `DocumentOrchestrationService`, canonical `DocumentCandidate`, connector
capability reporting, opportunity-first handoff, manifest reconciliation, and queueing.

## Evidence gate and description

All three connectors pass the independent gate using sanitized detail fixtures and
injected transports. Each emits canonical candidates with parent provenance, stable
attachment identity, explicit access state, and deduplication. Public documents are
eligible for the existing manifest/queue. Gated documents remain metadata-only.

### Georgia GPR

Enables the fixture-backed adapter for public solicitation files and addenda. It uses
the profile's explicit official/approved host allowlists and preserves login-required
GA@WORK attachment metadata without queueing it.

### Maryland eMMA

Enables the fixture-backed adapter for multiple attachments, addenda, Q&A, bid tabs,
and awards. Supplier-profile/login rows remain restricted and duplicate URLs are
suppressed.

### Virginia eVA

Adds a canonical adapter over `document_links`. Explicit attachment IDs are preferred;
the fallback combines lot, round, and attachment path. Transient query material is not
included in identity or raw metadata. Free-account and login transitions are never
automated.

## Pipeline integration and versions

The three families are added to the orchestration compatibility set. Numeric source
versions and eVA rounds feed shared manifest reconciliation; addendum/amendment numbers
remain distinct and queryable. No connector-specific queue, downloader, parser, OCR, or
extraction code is introduced.

## Security controls

Adapters require HTTPS and explicit connector host approval, reject unsafe/malformed
links, do not forward credentials, and never perform login, registration, CAPTCHA, or
bid submission. Retrieval redirects remain subject to the existing safe downloader.

## Testing

Fixture tests cover normalization, capability reporting, public/restricted states,
deduplication, version/addendum metadata, and eVA canonical adaptation. The full unit,
lint, compile, coverage validation/recommendation, and repository checks are run before
publication.

## Live validation

Not performed. This change relies on sanitized fixture evidence and does not interpret
network availability as an access classification.

## Coverage changes

The derived `public_document_pipeline_count` increases from 4 to 7. Generated JSON and
Markdown coverage reports are refreshed; the count is computed from registry
capabilities rather than hardcoded.

## Known limitations and exclusions

No requested connector is excluded. Verification remains fixture-only. eVA temporary
public links may require reacquisition through its public detail workflow. Future host
or markup changes fail closed until allowlists and fixtures are updated. Rows without a
safe source URL are skipped because the canonical model requires one.
