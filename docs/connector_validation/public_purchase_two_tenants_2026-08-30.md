# Public Purchase two-tenant validation

Validation date: 2026-08-30

This point-in-time, anonymous, read-only validation covers two independently operated
California county buyers using the same legacy Public Purchase GEMS family. It establishes
the observed public metadata contract and its access boundaries; it does not claim continuous
availability or anonymous document access.

## Authoritative tenant linkage

| Tenant | Official procurement page | Public Purchase tenant | Result |
| --- | --- | --- | --- |
| Fresno County | `https://www.fresnocountyca.gov/Departments/General-Services-Department/Purchasing-Services/Bid-Opportunities` | `fresnoco,ca` | Official page identifies Public Purchase and links separate open and closed bid pages. |
| Kern County | `https://www.kerncounty.com/government/county-administrative-office/how-do-i/view/current-bid-opportunities` | `kern,ca` | Official page identifies Public Purchase and embeds the tenant's anonymous `publicInfo` page. |

No fallback tenant was needed. Riverside County was not used as evidence.

## Shared anonymous request and markup contract

Both tenants exposed these GET routes without a login:

- `/gems/{tenant}/buyer/public/publicInfo` — open-bid HTML table.
- `/gems/{tenant}/buyer/public/publicClosedBidsInfo` — closed/finalized-bid HTML table and
  search form.
- `/gems/{tenant}/bid/bidView?bidId={numeric_id}` — stable detail link, but the response is
  the shared login page for an anonymous user.

The open table has five columns: title, start date, end date, time left, and addendums. Its
first cell contains a numeric `bidId` detail link and a displayed heading such as
`E-RFQ #27-005 - Snow Removal Services`. The connector now parses this observed HTML variant,
separates the solicitation number from the title, normalizes Pacific timestamps, retains the
numeric upstream ID, marks the record `public_metadata_only`, and sets
`documents_complete=false`.

The closed table has three columns: title, status, and end date. Observed statuses included
`CLOSED` and `FINALIZED`; the latter is normalized as awarded/finalized rather than unknown.
The page uses an anonymous POST to the same closed-list URL with these fields:

- hidden: `page`, `sortBy`, `sortDesc`, `posting`
- filters: `bidTitle`, `bidNumber`, `endingTimeInterval`
- submit: `search=Search`

Pagination is zero-based in the POST contract: the visible page `2` invokes `srchPage('1')`.
The same field names, route shape, five-row page size, and pagination behavior were observed for
both tenants. The connector does not yet issue the POST because its production transport is
GET-only; the contract is documented and represented by a sanitized fixture, not invented as a
new collection path.

Fresno's title field retained the submitted value `Toxicology`, but the returned first-page rows
were unchanged during the validation. The presence of a filter control is therefore validated;
effective server-side title filtering is not claimed.

## Tenant-specific behavior

- Fresno's official page links directly to `publicInfo` and `publicClosedBidsInfo`. Eleven open
  rows were visible during validation, including records with and without addenda.
- Kern's supplied `/buyer/public/home` route displayed registration/login controls and said to
  log in to view open bids. Kern's official county page instead embeds the shared anonymous
  `/buyer/public/publicInfo` route, which exposed two open rows. The connector preset therefore
  keeps `/home` as the agency page but uses the evidence-backed `/publicInfo` discovery route.

## Detail, contacts, Q&A, addenda, and documents

Opening a representative detail link for each tenant returned the shared Public Purchase login
form (`/login/process`) with username and password fields. The connector now recognizes that
form as `login_required` rather than misclassifying it as changed markup.

Consequences of that boundary:

- Opportunity-specific description and buyer contacts were not anonymously exposed.
- Addendum dates/count signals were visible in the Fresno listing, but addendum metadata and
  contents were gated by the detail login.
- Public Q&A was not exposed anonymously.
- Attachment names, sizes, media types, and download URLs were not exposed anonymously.
- No representative solicitation document could be downloaded without login. No download was
  attempted after the boundary was established, and no production document is committed.

Fresno's official procurement page separately publishes the Purchasing Division phone number
and email. Those agency-level contacts corroborate authority but are not treated as
opportunity-specific Public Purchase fields.

## Closed and awarded records

Both closed-list routes returned anonymous records and pagination. Fresno exposed `CLOSED` and
`FINALIZED` rows; Kern did the same. A finalized status is evidence of lifecycle completion, but
no awardee, amount, tabulation, or contract record was anonymously visible, so the connector does
not manufacture award details.

## Access and operational boundaries

- Login and free registration were visible; neither was used.
- Kern's home page advertises free registration and login, while its official embed points to
  the separate anonymous listing route.
- No CAPTCHA appeared in either walkthrough.
- No `429`, retry notice, or other rate-limit signal was observed during the bounded walkthrough.
  Absence of an observed limit is not evidence that none exists.
- No registration, agency enrollment, subscription, notification, question, addendum
  acknowledgement, response, upload, or submission action was performed.

## Fixture-tested versus live-observed

Live browser observation establishes the authoritative county linkage, the two tenant slugs,
anonymous open and closed table shapes, numeric detail IDs, visible solicitation identifiers and
dates, addendum summary cells, the closed search/pagination form, and the detail login boundary.

Minimal sanitized fixtures reproduce the shared open table, closed table/search fields, and login
form without cookies, tokens, credentials, HAR content, production documents, or public contact
data. Regression tests cover both tenant presets, open/closed parsing, relative detail URLs,
Pacific timestamp parsing, finalized status normalization, incomplete-document semantics, and
login-boundary detection.

## Remaining limitations

- Detail, Q&A, attachment metadata, buyer contacts, and document downloads require login for the
  representative records tested.
- Anonymous addendum cells expose dates/count signals, not authoritative addendum documents.
- Search controls are observed, but Fresno's title submission did not filter the returned rows.
- Closed pagination/search POST collection is documented but not enabled in the GET-only
  connector.
- The validation is point-in-time and does not protect against future markup or access changes.
