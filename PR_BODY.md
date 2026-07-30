## Motivation

Add bounded public procurement intelligence for Maryland eMaryland Marketplace Advantage (eMMA) while preserving the product's anonymous, read-only boundary.

## Description

- Adds canonical `maryland/emma` connector and explicit non-ambiguous aliases.
- Adds configuration-driven statewide/issuing-organization identity, exact host allowlists, collection bounds, access expectations, lifecycle state, and verification metadata.
- Adds fixture-proven public listing/detail/notice, attachment, addendum, Q&A, tabulation, and award parsing with field provenance and stable identity.

## eMMA platform behavior

Public Solicitations are the supported primary collection surface. eMMA can carry Maryland agency, local-government, county, school, university, authority, and commission notices, but no universal coverage is asserted. Upstream types and UNSPSC/socioeconomic metadata are preserved only when explicit.

## Public access boundaries

Participation requires vendor actions this connector does not perform. It never registers, authenticates, uses Maryland or MDOT SSO, adds/acknowledges solicitations, submits responses, uploads files, accesses unpublished sourcing projects, or replays authenticated sessions.

## Discovery and detail behavior

Collection uses bounded GET requests, stable ordering and identity, duplicate/repeated-page suppression, strict page/result limits, local filters, changed-markup detection, and fail-closed normalization.

## Public notices and alternate systems

Notices may point to BidX/Bid Express, Bonfire, Bid Locker, an agency page, offline instructions, or another public portal. The relationship and platform hint are preserved for downstream reconciliation. External response systems remain separate connectors and are never invoked or operated from eMMA.

## Document pipeline integration

Anonymous direct files become provenance-rich `DocumentCandidate` records for the existing manifest, durable queue, safe downloader, parsing/targeted OCR, structured extraction, and version reconciliation pipeline. Addenda preserve version and relationship metadata; gated/submission links are ineligible.

## CAPTCHA policy

Public Contracts may present CAPTCHA. CAPTCHA is detected and reported as `captcha_required`, never solved or bypassed, and never treated as an empty result. A blocked contract resource does not disable a separately public solicitation surface.

## Resilience and safety

Exact HTTPS host checks, private-address rejection, bounded retries/backoff/jitter, Retry-After support, repeated-page detection, per-profile circuit state, and owned/injected client lifecycle rules apply. The existing downloader retains SSRF, redirect, DNS, MIME, size, streaming, filename, checksum, HTML-wall, and archive protections.

## Reusable page.aspx components

Narrow helpers parse allow-listed hidden fields and stable links for fixture-supported pages. They do not submit state, automate forms, add a browser dependency, register generic ASP.NET aliases, or claim compatibility with unrelated sites.

## Verification status

Behavior and sanitized inputs are `fixture_verified`; untested profiles remain `configured_unverified`, and migrated/unavailable states fail closed. Fixture verification is not proof that every live eMMA page, agency, solicitation, contract, or attachment is anonymously accessible. No live checks were performed.

## Testing

- `PYTHONPATH=src python -m unittest discover -s tests -v`
- `PYTHONPATH=src python -m compileall src tests`
- `ruff check .`
- `ruff format --check .`
- `git diff --check`

## Known limitations

No POST-only search navigation, login, SSO, vendor-profile interaction, CAPTCHA solving, external-system submission, broad project-ID enumeration, or universal ASP.NET compatibility is implemented. Live markup and access can vary by resource and issuing organization.

## Codex Cloud publication notes

Any future live checks must be at most two bounded anonymous GETs. This local branch and commit are ready for inspection and publication through the Codex Cloud **Create PR** button; no shell GitHub authentication or remote publication command is required.
