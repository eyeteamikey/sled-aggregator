# OpenGov Procurement two-tenant validation

Validation date: 2026-08-24

This validation establishes a reusable anonymous public request contract for two
independently operated OpenGov Procurement tenants. It is a point-in-time
observation, not a claim of continuous production availability.

## Tenants and evidence

| Tenant | Starting URL | Tenant code | Organization timezone | Raw source HAR SHA-256 | Sanitized HAR SHA-256 |
| --- | --- | --- | --- | --- | --- |
| Ocean County, New Jersey | `https://procurement.opengov.com/portal/oceancounty` | `oceancounty` | `America/New_York` | `6bc258cece119647da5a73f7c225acb373be93071799ecb334b89e60afb51f7d` | `7c34fcb55cc1882bcaf8b120b0d3515fe2c359aaf2e032a37ee7fd3adb0154ad` |
| Alameda County, California | `https://procurement.opengov.com/portal/acgov` | `acgov` | `America/Los_Angeles` | `6f4048bb552f6056d9de550c7caaeb285307e77d3fcd94894f9ce69736e866af` | `664db6a10d2f07de9ad2fa153f6389a9d2f2bee7529bdd8f4d98f803f7e475db` |

The raw and sanitized HARs remain under ignored `.sled-validation/` storage and
must not be deleted until the evidence-derived pull request is merged and the
functionality is confirmed on `master`. Neither HAR is committed. The repository
scanner reported zero findings on the minimized sanitized contract artifacts.
Response bodies were removed from those sanitized artifacts; reviewed minimal
fixtures retain only the structural fields needed by tests.

## Shared request contract

Both tenants used `https://api.procurement.opengov.com/api/v1` and the same
route/schema family:

- `GET /government/{tenantCode}` for public organization configuration.
- `POST /government/{tenantCode}/project/public` for public listing, search,
  filtering, sorting, and pagination. The body is exactly `{"data": query}`.
- `GET /project/{projectId}` for opportunity detail, contacts, addenda/notices,
  attachment metadata, configuration-dependent bid results, and award state.
- `GET /project/{projectId}/question` for released public Q&A.

The observed listing query contains `filters`, `quickSearchQuery`, `limit`,
`page`, `sortField`, and `sortDirection`. Page numbers are one-based. The public
UI offered page sizes 5, 10, 20, and 50. The response shape is an object with an
integer `count` and a `rows` array. Duplicate authoritative project IDs are
discarded across pages.

Observed public filter objects were:

- title/keyword: `{"type":"title","value":"..."}`
- solicitation number (labeled Project ID in the UI):
  `{"type":"financialId","value":"..."}`
- status: `{"type":"status","value":"open|closed|pending"}`
- department: `{"type":"department_id","value": numericId}`
- categories: `{"type":"categories","value":[numericCategoryIds]}`

Observed sorting used `title`, `status`, `releaseProjectDate`, or
`proposalDeadline` with `ASC` or `DESC`. The public portal did not expose date
filter controls, so the connector does not send invented date filter objects;
optional date bounds are applied locally after retrieval.

## Walkthrough observations

For each tenant the walkthrough covered the initial portal, active listing,
keyword/title search, status and department filters, category search/selection,
sorting, the second page, two open detail records, a closed/awarded record,
public Q&A, addenda/notices, document selection, and the download boundary.

Ocean County exposed 13 active opportunities over two pages during the review.
An Engineering department filter used ID `589`; selection of civil engineering
demonstrated numeric parent/child category IDs. Ocean detail data exposed agency
contacts, contracting/addendum authors, amendments, official notices, public
Q&A, public bid-result vendor names on an awarded record, and related contract
cards in the browser. A direct anonymous contracts-list POST returned HTTP 401,
so the connector does not call it and does not claim a reusable anonymous
contracts API.

Alameda County exposed active opportunities over two pages. Its General
Services Agency-Procurement department used ID `11400`. Reviewed records
included invitation-for-bid and request-for-quotation types, Pacific-time
deadlines, agency contacts, addenda, notices, and public Q&A. A reviewed closed
record exposed `Awarded` status, but no vendor Results tab; Alameda award coverage
therefore remains metadata-only.

## Details, contacts, vendors, and awards

The shared detail schema supplies authoritative project ID, optional
`financialId`, title, HTML summary/background, status and closed substatus,
department, dates, type, organization/timezone, categories, and flattened
contact/procurement fields. The connector converts summary HTML to text and
retains public contact name, title, government email, and telephone fields.
Contact roles hidden by the tenant's `hideContact` or `hideProcurementContact`
flags are not normalized as public contacts. Released addendum/notice authors
are retained when exposed.

Ocean's reviewed awarded record exposed public bid-result vendor names and
locations. Vendor email fields present only in the raw API, but not visibly
published in the reviewed Results UI, are deliberately not normalized. Closed
substatus `awarded` maps to canonical `awarded`; cancellation and ordinary
closed states remain distinct.

## Attachments and authentication boundary

Both detail schemas exposed a compiled project document, regular attachments,
and addendum/notice attachments with IDs, filenames, extensions, timestamps,
and parent project linkage. The connector preserves this metadata and creates a
candidate for each unique attachment ID linked to the parent opportunity.

Detail responses also contained short-lived signed object-storage URLs. They
are authentication material, not durable public source links: the connector
does not retain or follow them. In both tenants, selecting a document and
pressing Download produced a login/create-account dialog before the UI would
invoke its download POST. No login, registration, credential, download POST, or
document retrieval was attempted. Candidates use the authoritative public
detail page as their metadata URL and are marked `login_required` and not
publicly retrievable.

Ocean's first portal load briefly displayed Cloudflare “Performing security
verification” and then cleared without human action. No CAPTCHA was solved or
bypassed. Alameda displayed no challenge during the reviewed walkthrough. The
connector classifies CAPTCHA/Cloudflare challenge markup and login walls and
fails closed.

## Fixture-tested versus live-observed

Live-observed behavior established route hosts, tenant-code placement, request
methods, listing body/filter vocabulary, sorting, pagination, response shape,
detail/Q&A fields, status/timezone differences, attachment metadata, public
contacts, Ocean vendor results, and the login/session boundaries.

Small deterministic JSON fixtures use fictional people and `example.invalid`
addresses while preserving those response structures. Automated tests cover
tenant resolution, shared request construction, filtering, pagination,
deduplication, detail/contact/vendor/award normalization, amendments, Q&A,
attachment parent linkage and filename handling, login/CAPTCHA/malformed
responses, retries/timeouts/circuit state, and injected versus owned clients.

## Remaining limitations

- Public document bodies were not downloaded because both tenants required
  login at the download action. No RFP/SOW/specification content was retrieved.
- The public UI did not expose date filtering; only local date bounds are tested.
- Related contracts are not collected because the observed direct POST was not
  anonymously reusable outside browser session state.
- Vendor/award visibility varies by record and tenant configuration.
- The fixtures demonstrate the observed schema but do not imply current portal
  uptime or protect against future OpenGov contract changes.
