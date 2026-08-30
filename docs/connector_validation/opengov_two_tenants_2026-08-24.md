# OpenGov Procurement two-tenant validation

Validation date: 2026-08-24

This point-in-time validation establishes a shared anonymous public contract for
two independently operated OpenGov Procurement tenants. It does not claim
continuous production availability.

## Tenants and genuine browser evidence

| Tenant / capture | Starting URL | Tenant code | Source HAR SHA-256 | Sanitized SHA-256 | Capture ID |
| --- | --- | --- | --- | --- | --- |
| Ocean County, New Jersey | `https://procurement.opengov.com/portal/oceancounty` | `oceancounty` | `bc3b9a7240e010dd97acc22793ee0ab5c017cf32dbc4365758bf012174d9a2e9` | `1d96fc202faa478c883a57f315560bb83ebcf8ffbe9bca6ad37c28b9f816cd15` | `nj-ocean-county-opengov-20260825015534` |
| Alameda County, California | `https://procurement.opengov.com/portal/acgov` | `acgov` | `306b790c5af442e4c492252a60df878ab50c49aefe0c7c3ec5643c56f45588e5` | `71aeba1b8d035ff40107ec3ffc907263678dae95dae5df360bd08e51f1bbb300` | `ca-alameda-county-opengov-20260825025702` |
| Alameda category supplement | same Alameda portal | `acgov` | `e8e2108e861f0961e85efcd1d425cb65ac60e0741a4ad0a688d176567c337e1b` | `f166411c71b5f8bfe7446ad5ece5f168ba82e04dbf05204fbf4e281332c66459` | `ca-alameda-county-opengov-20260825030321` |

These are genuine Chrome DevTools Network exports with response content from a
visible Incognito walkthrough. Untouched sources remain under ignored
`sled-har-evidence/`; imported raw copies, sanitized copies, audit files,
findings, analyses, and evidence reports remain under ignored
`.sled-validation/`. They must not be deleted until the pull request is merged
and confirmed on `master`. No complete HAR or production document is committed.

The raw inventories found no authorization headers or ViewState values. They did
find browser cookies, tracking identifiers, and public procurement email/phone
data. Sanitization removed cookie/session material while deliberately retaining
public procurement contacts and vendor data. The conservative scanner reported
high-entropy/static-asset and public-contact candidates, so none of the captures
was automatically approved; the findings files remain local for review.

## Evidence classes

- **Genuine browser-observed evidence:** the three source/sanitized HAR pairs in
  the table, plus the visible walkthrough findings below.
- **Live API replay:** same-day anonymous requests used before browser capture to
  check the listing envelope and selected public responses. Replay corroborates
  a contract but is not labeled browser evidence.
- **Deterministic fixtures:** small fictional JSON structures under
  `tests/fixtures/` that test parsers and request construction. They do not prove
  live availability.
- **Derived replay artifacts:** earlier HAR-shaped files assembled from retained
  API responses, with source/sanitized hashes
  `6bc258ce...51f7d`/`7c34fcb5...154ad` (Ocean) and
  `6f4048bb...866af`/`664db6a1...475db` (Alameda). They remain local and are not
  substitutes for the genuine browser exports above.

## Shared observed request contract

Both tenants used `https://api.procurement.opengov.com/api/v1` and the same core
route/schema family:

- `POST /government/{tenantCode}/project/public` for listing, title search,
  observed filters, sorting, and one-based pagination.
- `GET /project/{projectId}` for authoritative detail, flattened public contacts,
  attachment metadata, addenda/notices embedded in the detail, and award flags.
- `GET /project/{projectId}/addendums` when the Addenda & Notices tab opens.
- `GET /project/{projectId}/question` when public Q&A opens.
- `GET /government/{tenantCode}/calendar/public` for the portal calendar.
- `POST /categories/search` for category lookup only.

The listing body is the query object itself, not an outer `{data: query}`
envelope. It contains `filters`, `quickSearchQuery`, `limit`, `page`, and, after
the initial load, `sortField` and `sortDirection`. The response is an object with
an integer `count` and a `rows` array. The observed page size was 10, and both
tenants exposed a second page. Authoritative project IDs are stable across list
and detail and are used for deduplication.

Genuine browser requests established these exact filter objects:

- title: `{"type":"title","value":"..."}`
- status: `{"type":"status","value":"open|closed"}`
- department: `{"type":"department_id","value":589}` for Ocean and
  `{"type":"department_id","value":11400}` for Alameda

Observed sorting was default `proposalDeadline DESC` and user-selected
`releaseProjectDate ASC`. The connector fails closed for other sort fields,
unobserved status values, Project ID/financial-ID search, and category listing
filters.

Both portals exposed category lookup and selection. In the genuine captures,
selecting a category and pressing Search emitted `POST /categories/search` but
did not emit a category-filtered listing POST or alter the rows. The connector
therefore does not manufacture a `categories` listing filter. The portal exposed
a calendar rather than list-page date filters; optional date bounds remain local
post-retrieval checks and are never sent as invented POST vocabulary.

## Detail, contacts, Q&A, addenda, and attachments

The shared detail schema exposed project ID, solicitation number (`financialId`),
title, agency/department, description, status/substatus, issue and due dates,
Pacific or Eastern organization timezone, categories, and flattened project and
procurement contacts. Public contact names, government email addresses, telephone
numbers, titles, and addendum authors are retained. Contacts hidden by the
tenant's `hideContact` or `hideProcurementContact` flags are excluded.

Ocean and Alameda both returned released addenda/notices and attachment metadata.
Alameda project `287567` exposed Addendum 1 and 37 public questions. Ocean also
exposed public Q&A. Attachment metadata retained IDs, displayed filenames,
extensions, timestamps, addendum/notice classification, the authoritative detail
URL, and parent project/opportunity linkage.

Detail responses contained temporary signed storage URLs. They are active
session material, not durable source URLs, and are not retained. On both tenants,
selecting a representative solicitation document and pressing Download opened a
login/create-account dialog before document retrieval. No credentials were
entered and no production document was downloaded. Document candidates are
therefore metadata-only, `login_required`, and not publicly retrievable.

## Tenant-specific public vendor and award behavior

Ocean displayed public Results/Contracts information on an awarded record. The
standalone contracts-list POST worked in the anonymous browser session but a
cookie-free replay returned 401, so the connector does not call it and records it
as browser-session-dependent. Existing fictional award fixtures exercise the
separately replayed public bid-result shape.

Alameda awarded project `259389` did not expose Ocean-style Results/Contracts
tabs. It did expose a public Followers list backed by
`GET /project/259389/planholders`: 90 organizations, public contact fields,
`Prime`/`Sub`/`Plan Room` designations, and 15 proposer markers. Alameda's tenant
profile enables this exact GET contract as an opt-in bounded query; Ocean's
profile fails closed because that route was not observed there. Fictional
`example.invalid` fixtures cover normalization without committing production
vendor payloads.

## Walkthrough and access boundaries

Ocean was completed first and Alameda second. Each visible walkthrough covered
initial load, active listing, title search, status and department filters,
category lookup/selection, sorting, pagination, calendar/month navigation, at
least two details, public contacts, addenda/notices, Q&A, attachment metadata,
closed/awarded records, and the document-download boundary.

Ocean presented a Cloudflare verification step. Automation stopped and the human
operator completed it; no challenge was solved or bypassed by code. Alameda did
not present a CAPTCHA or browser challenge. Neither walkthrough logged in,
registered, followed a project, drafted/submitted a response, uploaded a file,
asked a question, or performed another mutation. No rate limit was observed.

## Fixture-tested versus live-observed

Genuine browser evidence establishes the hosts, tenant placement, listing body,
title/status/department filters, sorting, pagination, detail/addenda/Q&A/calendar
routes, attachment/login boundary, public contacts, Ocean session-dependent
results/contracts behavior, and Alameda planholders. Live API replay separately
corroborated the listing envelope and selected response shapes.

Deterministic tests cover both tenant profiles, shared listing discovery,
observed filtering/sorting, pagination, deduplication, detail/contact/status/date
normalization, Q&A, amendments/notices, attachment discovery and parent linkage,
filename handling, award fixture normalization, opt-in Alameda planholders,
login/CAPTCHA/malformed responses, retry/timeout/circuit state, and injected
versus connector-owned clients. Tests explicitly reject the unobserved category,
financial-ID, pending-status, title-sort, and Ocean planholder contracts.

## Remaining limitations

- No production solicitation document was downloaded because the visible action
  required login.
- Category lookup/selection was visible, but no category-filtered listing request
  was emitted; category listing syntax remains unknown.
- Project ID/financial-ID filtering and non-calendar date filtering were not
  browser-observed and are unsupported.
- Ocean contracts/results require browser session state; no reusable standalone
  connector route is claimed.
- Alameda planholders are a tenant-specific opt-in surface, not a family-wide
  guarantee or an award determination.
- Vendor/award fields vary by record and tenant configuration.
- The evidence is dated and fixture-backed; it does not imply current uptime or
  protect against future OpenGov changes.

## Anonymous fallback revalidation on 2026-08-30

The two primary tenant URLs and the requested San Mateo fallback were revisited
in an anonymous browser session. Ocean County presented Cloudflare's security
verification boundary, which was neither solved nor bypassed. Alameda loaded its
public active-project grid anonymously with the same department/status/search
controls, 10-row default page size, and two visible pages.

San Mateo (`smcgov`) was used as the fallback and independently corroborated the
shared public UI contract. Its active grid exposed department and status filters,
search, 10-row pages, and three pages of current records. Page navigation changed
the visible rows without login. A representative detail exposed the stable
`/portal/smcgov/projects/{project_id}` route, project metadata, Pacific timezone,
project and procurement contacts, project-document sections, addenda, attachment
filenames, and answered public Q&A. The closed filter exposed 61 pages and visibly
distinguished `Awarded` and `Canceled` substatuses.

Selecting one representative addendum attachment
(`SBM_CrockerGate_Phase2_ProjectMap_georef.pdf`) opened a dialog stating that
login or account creation was required. No credentials were entered and no
production file was downloaded. The visible portal continued to expose `Sign Up`,
`Log In`, `Follow`, `Draft Response`, `No Bid`, and `Ask Question` as boundaries;
none was invoked. No rate-limit response was observed. This revalidation adds a
San Mateo tenant preset but does not change the family request vocabulary or
promote document downloads to public access.
