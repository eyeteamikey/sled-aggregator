# PlanetBids two-tenant validation — 2026-08-30

## Scope and evidence

This is a point-in-time, anonymous, public, read-only validation. It does not
claim continuous production availability. No account was created, no login was
attempted, no bidder action was taken, and no CAPTCHA was solved. Cloud browser
inspection and public search indexing were used; no source HAR was available.

| Buyer | Buyer class | Official source | Portal | Portal ID |
|---|---|---|---|---:|
| County of Stanislaus | County | `https://www.stancounty.com/purchasing/county-bids.shtm` | `https://vendors.planetbids.com/portal/14599/bo/bo-search` | 14599 |
| Los Angeles County Office of Education (LACOE) | Education / county office of education | `https://www.lacoe.edu/services/business/vendors` | `https://vendors.planetbids.com/portal/61954/bo/bo-search` | 61954 |

LACOE is not Los Angeles County government and is not the City of Los Angeles.
Both official agency pages link to PlanetBids. No fallback tenant was required.

## Shared observed contract

Both tenants use direct HTTPS navigation on `vendors.planetbids.com` with
`/portal/{numeric_portal_id}/bo/bo-search` and public details at
`/portal/{numeric_portal_id}/bo/bo-detail/{numeric_opportunity_id}`. The rendered
listing rows expose the stable opportunity ID as `rowattribute`. Visible search
controls include keyword, bid type, categories, stage, department, due-date
range, and Search/Clear. Posted, title, due date, remaining time, and stage are
sortable in the shared table UI. Dates are displayed in PDT during this capture;
profiles normalize them with `America/Los_Angeles`.

The browser loaded both direct portals without login, CAPTCHA, WAF challenge, or
rate-limit response. The UI is Ember/JavaScript-based. The exact background
listing/detail request routes, payloads, headers, cookies, CSRF behavior,
pagination parameters, and error schemas were not observable without a HAR.
Therefore the connector does not invent or authorize an anonymous POST contract.
The new live profiles are bounded to one rendered page until that contract is
captured.

## Tenant findings

Stanislaus exposed 498 records during validation, with Bidding, Closed, Award
Pending, and Awarded examples. Departments included Public Works and Purchasing;
types included Bid, RFI, RFP, RFQ, RFQual, and IPWB. Opportunity `139452` exposed
title, invitation number, posting/due dates, stage, response format/type,
categories, preferences/restrictions, department/address, bonds, pre-bid and Q&A
flags, government contacts, scope, notes, and special notices. Its tabs exposed
Documents, Addenda/Emails, Prospective Bidders, Submissions, and Awards as
separate optional surfaces.

LACOE exposed the same listing controls and public detail pattern. Public indexed
examples included `139237`, `138238`, and awarded `112302`. The entity is retained
as Los Angeles County Office of Education with buyer class `education`; it is not
collapsed into a county-government profile. Its solicitation numbering and
education/service subject matter differ, while the portal route and rendered
listing structure are shared.

## Capability matrix

| Capability | Stanislaus | LACOE | Evidence level |
|---|---|---|---|
| Official linkage | Public | Public | Live official page |
| Direct listing | Public | Public | Live browser |
| Keyword/type/category/stage/department/date controls | Visible | Visible | Live browser; request payload not captured |
| Sorting | Visible | Visible | Live browser |
| Stable numeric detail ID | Public | Public | Live URL/rendered row |
| Detail metadata and contacts | Public | Public | Live browser/search indexing |
| Closed/awarded discovery | Public | Public | Live listing/indexing |
| Documents/addenda/Q&A/bidders/awards tabs | Visible where configured | Visible where configured | Metadata surface only |
| Representative document download | Not proven | Not proven | Desktop capture required |
| Pagination/continuation request | Not proven | Not proven | Desktop HAR required |

Attachment metadata, download URLs, anonymous download eligibility, Q&A records,
addendum records, bidder lists, award records, and their background routes are
not production-proven by this capture. Existing synthetic fixtures continue to
exercise canonical normalization and mixed access classifications, but fixture
success is not live evidence.

## Implementation and limitations

Profiles `stanislaus-county-ca` and `lacoe-ca` authorize only the shared platform
host and preserve portal IDs, legal entity identity, official landing URLs, and
authoritative detail templates. The parser accepts the observed Ember rendered
row structure, preserves portal-plus-opportunity deduplication, parses Pacific
dates, and fails closed on unrecognized markup. Existing retry, timeout,
circuit-breaker, URL safety, and HTTP-client ownership rules remain unchanged.

Remaining desktop work: capture one bounded HAR per tenant; record SHA-256 and
keep the complete HAR ignored/local; sanitize only the exact anonymous routes;
exercise searches, every filter, sort, and continuation; inspect at least two
details each; inspect tabs; and download at most one clearly public solicitation
document per tenant. Record login/registration transitions without bypassing
them. Until then, do not mark attachment retrieval, pagination, or the background
API request contract as production-proven.

No complete HAR, browser profile, cookie, token, CSRF value, session identifier,
production document, or CAPTCHA material is committed.
