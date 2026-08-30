# Euna Bonfire two-tenant validation — 2026-08-30

## Scope and access boundary

This validation used anonymous, public, read-only browsing and GET routes only. No account was
created, no login/session was supplied, no challenge was solved, and no bid, question,
notification enrollment, document acknowledgement, intent-to-bid action, or other mutation was
attempted. The evidence is point-in-time and is not a claim of continuous production availability.

No browser-export HAR was available. Therefore there are no source-HAR SHA-256 values. No complete
HAR, cookies, authorization/CSRF/session material, browser profile, CAPTCHA token, or production
solicitation document was retained or committed. `sled-har-evidence/` and `.sled-validation/`
remain ignored by Git.

## Official linkage and tenant identity

| Tenant | Official source | Canonical portal | Observed identity |
|---|---|---|---|
| County of Ventura, California | `https://venturacounty.gov/general-services-agency/procurement-home/` (redirect target of the supplied Ventura procurement URL) | `https://ventura.bonfirehub.com/portal/?tab=openOpportunities` | hostname slug `ventura`; portal organization `County of Ventura` |
| Hillsborough County, Florida | `https://hcfl.gov/departments/procurement` and its vendor page | `https://hillsboroughcounty.bonfirehub.com/portal/?tab=openOpportunities` | hostname slug `hillsboroughcounty`; portal organization `Hillsborough County` |

Ventura's official page labels the portal Vendor Information Portal (VIP) and links directly to
`ventura.bonfirehub.com`. Hillsborough's official page calls it Euna Procurement and links the same
Bonfire hostname for both vendor registration and viewing bid opportunities. This establishes
official government-to-portal linkage for both primary tenants; Cook County fallback was not used.

## Shared live-observed listing contract

Both tenants rendered the legacy Bonfire public portal at
`/portal/?tab=openOpportunities`, with Euna help/privacy branding and `bonfirehub.com` tenant hosts.
The page's own code initializes open and past opportunity sections with anonymous GET calls:

- `/PublicPortal/getOpenPublicOpportunitiesSectionData`
- `/PublicPortal/getPastPublicOpportunitiesSectionData`
- optional `/PublicPortal/getPublicContractsSectionData`

The open-section schema consumed by the portal is an object containing `projects`; project fields
used by the shared template include `ProjectID`, `ReferenceID`, `ProjectName`, `DepartmentID`, and
UTC `DateClose`. A `departments` collection/dictionary is tenant-configured. Details use stable
`/opportunities/{ProjectID}` routes. The page renders status, reference, title, optional department,
tenant-local close date, days remaining, and the detail link.

Listing search, column sorting, and visible paging are DataTables client-side operations over the
single section payload. They are not server page/continuation parameters. Department filtering is
also client-side and exists only when the tenant enables and configures it. No commodity/category
or independent date-range filter was exposed on either open-listing page. The connector therefore
performs bounded local keyword/status/department/date filtering and result limiting after one
anonymous section GET; it does not invent remote parameters.

## Tenant differences

| Capability/configuration | Ventura | Hillsborough |
|---|---|---|
| Open listings observed | 7 on validation date | 18 on validation date |
| Close-date rendering | PDT (`America/Los_Angeles`) | EDT (`America/New_York`) |
| Department filter | Enabled; GSA, HCA, HSA, PWA, VCP observed | Disabled; no departments in listing |
| Public Contracts tab | Not exposed | Exposed |
| Full-text-search preference | Disabled in page feature preferences | Enabled in page feature preferences |
| Public vendor fields preference | Disabled | Enabled |
| Public files preference | Enabled | Enabled |
| Unauthenticated public-file download preference | Disabled | Disabled |

Feature preferences are configuration evidence, not proof that a specific project exposes Q&A,
award/vendor data, or downloadable files.

## Detail, contacts, amendments, Q&A, awards, and documents

The first detail navigation on each tenant displayed Cloudflare's “Performing security
verification” / malicious-bot protection page. Per the validation boundary, no challenge was
solved and no alternate detail or download routes were probed after the block.

Consequently, the following are **not live-validated** in this run: two detail records per tenant,
descriptions/types, open/question dates, buyer/project-owner contacts, addenda/amendments, public
Q&A, awards, vendors/bidders/awardees, attachment metadata, document acknowledgement behavior, and
representative file download/linkage. No connector support for those capabilities is claimed for
these profiles. The profiles fail closed by disabling detail enrichment and document discovery
until bounded desktop evidence exists.

The portal visibly separates anonymous browsing from Log In/Register and submission functions.
Hillsborough's official copy likewise distinguishes viewing opportunities from logging in to
submit and track bids. Ventura's official VIP copy distinguishes public review from registered
responses. Registration is therefore an observed submission boundary, not an observed listing
requirement. Document access remains unknown; page preferences show
`PublicFilesUnauthenticatedDownloading = 0`, but the exact login/registration/acknowledgement flow
was not reached.

## Implementation and fixture evidence

The connector now has evidence-scoped Ventura and Hillsborough profiles and recognizes the shared
`projects` envelope and live Bonfire field names while retaining every raw source field. It maps
stable tenant + `ProjectID` identities, canonical detail URLs, references, titles, departments,
UTC database dates, and the source tenant timezone. Client-side pagination is represented as a
single bounded payload. Unexpected envelope shapes fail closed.

Fixtures are minimal synthetic reductions of the observed template/schema; names that do not need
to be real are fictionalized. Fixture tests establish deterministic parsing, filtering, bounded
results, deduplication, timezone handling, profile resolution, malformed-shape failure, and shared
cross-tenant behavior. They do not elevate unobserved details/documents to production-proven.

## Remaining desktop work

1. In a normal desktop browser, capture one bounded HAR per tenant after manually completing any
   explicitly presented challenge; do not log in.
2. Record and hash each source HAR locally, sanitize it, and retain the source until PR merge.
3. Inspect at least two details per tenant and one closed/awarded record.
4. Validate contacts, questions, addenda, awards/vendors, attachment metadata, and the precise
   document registration/acknowledgement boundary.
5. Download at most one representative public solicitation document per tenant if anonymous access
   is actually offered; never commit it.
6. Add only the newly observed routes/schemas and promote coverage only after the repository's
   scheduled live-success criteria are met.

## Known limitations

- Browser observation established the route and template contract, but the browser client blocked
  direct top-level navigation to the JSON route; no response body was exported as live evidence.
- No HAR hashes exist because no HAR was captured.
- Cloudflare detail challenges may be transient or client-specific; they are recorded as the
  observed boundary, not a claim that all users or all times are blocked.
- No fallback tenant was needed.
