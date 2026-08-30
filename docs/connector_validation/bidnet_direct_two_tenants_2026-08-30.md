# BidNet Direct two-tenant validation

Validation date: 2026-08-30. This is point-in-time anonymous browser evidence, not a claim of continuous production availability or scheduled live success.

## Sources and identity

| Tenant | Official starting page | Canonical BidNet surface | Purchasing group / ID | Buyer ID |
| --- | --- | --- | --- | --- |
| Maricopa County Procurement Services | `https://www.maricopa.gov/2190/Solicitations` | `https://www.bidnetdirect.com/arizona/maricopacounty` | Arizona Purchasing Group / `700132901` | `3165696805` |
| City and County of Denver General Services Purchasing | `https://www.denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/General-Services/Purchasing/Bidding-Opportunities` | `https://www.bidnetdirect.com/colorado/city-and-county-of-denver-general-services-purchasing` | Rocky Mountain E-Purchasing System / `8409951` | `15320617` |

Both official pages linked to the named BidNet surfaces. Denver's official link corrects the initially proposed `cityandcountyofdenver` slug. Maricopa's official link used `maricopacounty` with `srchoid_override=217285`, `posting=1`, and `curronly=1`; the page resolved as Maricopa County Procurement Services. The proposed `maricopacounty2` surface was not used. Denver DOTI remains a distinct agency surface and was not collapsed into General Services.

No HAR was captured. The cloud browser supplied visible DOM evidence but did not expose a source HAR export, so there are no HAR hashes or local source HARs for this validation. No production documents were downloaded or committed.

## Shared live-observed contract

Both tenant pages expose anonymous GET-only discovery with the same METS table markup and routes:

- Agency listing: `/{state}/{agency-slug}` and `/{state}/{agency-slug}/solicitations/open-bids?selectedContent=BUYER`.
- Keyword search: GET `keywords` on the agency open-bids route.
- Status: separate `open-bids`, `closed-bids`, and `awarded-bids` routes. Maricopa also exposed Published Contracts.
- Pagination: one-based `pageNumber`; a live Maricopa closed listing exposed a page-two link.
- Sorting: GET `sortBy` plus `sortDirection`. Observed fields were `solicitationNumber`, `noticeTitle`, `region`, `publicationDate`, and `closingDate`, each ascending or descending.
- Listing rows: solicitation number, title, state, publication date, closing date, and a detail URL.
- Stable upstream ID: the seven-or-more-digit numeric final detail-path segment (for example, fictional fixtures retain the shape but not production content).
- Detail URL: state-scoped detail paths include `purchasingGroupId` and `origin=2`. Tenant identity, purchasing-group identity, and buyer identity remain separate.

Tenant pages did not expose agency, purchasing-group, commodity/category, or date filter controls beyond the fixed tenant context. The connector therefore does not invent those remote parameters; canonical query fields remain bounded local post-retrieval filters where applicable.

## Details and access boundary

Two Denver opportunities and multiple Maricopa listing records were inspected, including open, closed, and awarded surfaces. An anonymous Denver detail exposed location, publication date, solicitation number, and an exact closing value with `MDT`. Issuing organization, description, bid documents, and buyer contact displayed `Registered members only`. Maricopa states that free Limited Access registration is available, but registration remains outside this connector's anonymous contract.

| Capability | Maricopa | Denver General Services |
| --- | --- | --- |
| Listing and keyword search | Public | Public |
| Open/closed/awarded metadata | Public | Public tabs observed |
| Detail metadata | Public metadata only | Public metadata only |
| Description and buyer contact | Registration required | Registration required |
| Attachment metadata/download | Registration required; not attempted | Registration required; not attempted |
| Addenda and Q&A | Registration-gated notification/detail functions; not anonymously evidenced | Registration-gated detail functions; not anonymously evidenced |
| Award/vendor detail | Award listing metadata public; vendor data not evidenced | Award tab present; vendor data not evidenced |

Dates from listings have day precision and are interpreted in `America/Phoenix` for Maricopa and `America/Denver` for Denver. Exact deadline time and abbreviation are retained only when supplied by a detail payload; the fixtures do not manufacture a time from a date-only listing.

## WAF, CAPTCHA, subscription, and network findings

Visible anonymous browser loads succeeded without a CAPTCHA, cookie login, or manual challenge. Direct non-browser HTTP GETs to all tested BidNet tenant slugs returned a bare 403 response. A bare 403 does not establish CAPTCHA or bot detection; it is recorded as a restricted client/network boundary. No retries, alternate fingerprints, challenge bypass, login, registration, subscription, payment, notification enrollment, questions, uploads, or bid actions were attempted.

The tenant pages advertise registration and BidNet package choices. Those commercial/vendor-account functions are not part of public discovery. Maricopa's official wording distinguishes its free Limited Access arrangement from broader paid geographic packages.

## Fixture-tested behavior and implementation

Small fictional fixtures reproduce the shared METS listing row and registration-gated detail markers. Tests cover profile resolution, separate purchasing-group/buyer IDs, cross-tenant parsing, GET search/sort request construction, stable-ID namespacing, timezone parsing, authoritative listing detail URLs, registration-wall recording, malformed markup, bounded results, retries/circuit state, and injected versus owned client lifecycle. Existing JSON fixtures continue to cover attachment, addendum, Q&A, award/vendor, access-state, redirect, and document-parent behavior; those tests are not relabeled as live evidence.

The connector now parses the observed METS table variant, follows the authoritative row URL rather than manufacturing a detail route, uses observed GET parameter names, supports the observed status routes, treats HTTP 403 as restricted rather than assuming login, and preserves purchasing-group ID, buyer ID, tenant key, source URL, and timezone. Unexpected markup still fails closed.

## Remaining desktop validation

- Capture and sanitize source HARs to establish response headers, public cookies, redirects, CSRF/session behavior, and any XHR contract. Preserve raw hashes locally until merge.
- Exercise the complete keyword and sort combinations and page two in a desktop capture.
- Inspect two details per tenant and verify whether any attachment metadata, addenda, Q&A, contacts, awards, or vendor fields become anonymous in a different opportunity configuration.
- Validate Denver DOTI and the Maricopa alternate slug separately before adding either as a profile.
- Do not promote the family to production-proven until scheduled live-success criteria pass.
