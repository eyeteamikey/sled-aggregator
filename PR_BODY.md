## Motivation

Add reusable public procurement intelligence for BidNet Direct member agencies and regional purchasing groups without crossing registration, subscription, or bid-participation boundaries.

## Description

Adds the canonical `bidnet-direct` connector, explicit aliases, configurable profiles, bounded anonymous listing/detail collection, normalized tenant-qualified identities, provenance, policy-boundary detection, document discovery, health reporting, deterministic fixtures, and tests.

## Platform architecture

Transport is separate from parsing and normalization. Profiles provide group and agency identity, URLs, exact host allowlists, lifecycle and verification metadata, discovery bounds, retry policy, and circuit-breaker settings. Transport is read-only and does not accept credentials.

## Public metadata behavior

Public metadata is collected only when anonymously exposed. Discovery is bounded by configured pages/results, suppresses duplicate records and repeated pages, uses stable ordering, supports fixture-verified filters, and fails closed on malformed or changed markup instead of treating an access page as empty.

## Registration and subscription boundaries

BidNet documents may require registration. Registration is not automated. Login, free registered accounts, notification features, saved searches, paid aggregation, subscriptions, bid intent, questions, addendum acknowledgements, uploads, pricing, and submissions are never used. Paid aggregation is not used.

## Member-agency versus aggregated provenance

Member-agency originals, regional-group originals, external aggregation, agency mirrors, and unknown records remain distinct. External upstream authority and reconciliation metadata are preserved; paid aggregated content is not ingested. Records from different tenants do not merge merely because titles or solicitation numbers match.

## Document pipeline integration

Document candidates preserve opportunity linkage, labels, filenames, categories, versions, access state, and raw provenance. Registration-gated candidates remain visible but are not retrieval eligible. Public candidates feed the existing manifest, safe downloader, parsing, targeted OCR, structured extraction, and version-reconciliation pipeline; no BidNet-specific downloader or OCR path is introduced.

## Official agency alternatives

Explicitly approved official agency document hosts are supported. Official agency copies are preferred when publicly available. A gated BidNet reference and public agency reference are both retained, but only the public agency copy is eligible for queueing. Arbitrary third-party aggregator substitution and unrestricted agency crawling are not supported.

## Robots and automated-access policy

Robots restrictions and technical blocks are respected. Robots-policy pages, automated-access blocks, CAPTCHA, unsafe URLs, and unapproved redirects fail closed. The connector does not rotate proxies or user agents, automate browsers, solve CAPTCHA, replay cookies, or evade controls.

## Resilience and safety

Requests have bounded timeouts and retries with exponential backoff, jitter, and Retry-After handling for transient failures. Stable access boundaries are not retried. Profiles have isolated circuit breakers, cooldown/recovery, failure/success timestamps, status codes, and health snapshots. HTTPS host allowlists and IP/credential checks reject private, reserved, loopback, link-local, credential-bearing, and unapproved locations.

## Verification status

The included profile and sanitized fixtures are `fixture_verified`. No live requests were made because this change ships no verified production tenant profile. Fixture verification is not universal live verification. Fixture verification demonstrates behavior against captured test inputs; it does not prove every live BidNet Direct opportunity or document remains anonymously accessible. Any future live checks must be bounded anonymous requests.

## Testing

- `PYTHONPATH=src python -m unittest discover -s tests -v` (219 tests)
- `PYTHONPATH=src python -m compileall src tests`
- `ruff check .`
- `ruff format --check` for all changed Python files
- `git diff --check`
- credential-pattern scan of the implementation and fixtures

The repository-wide `ruff format --check .` also reports nine pre-existing files outside this change that require formatting; those unrelated files were preserved.

## Known limitations

Anonymous availability varies by tenant and may change. Registered-only documents remain metadata references. The connector neither discovers every BidNet tenant nor performs nationwide aggregation, registered-vendor searches, bid actions, or unrestricted agency crawling. Production profiles require explicit host and fixture/live verification before activation.

## Codex Cloud publication notes

The implementation is committed locally on `agent/bidnet-direct-connector`. No fetch, pull, push, GitHub authentication, shell PR creation, or remote modification was attempted. The PR is ready for publication through Create PR after inspecting the Codex Cloud Diff.
