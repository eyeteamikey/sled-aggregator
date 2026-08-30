# CGI Advantage/VSS county validation — 2026-08-30

## Scope and evidence boundary

Validation was anonymous, public, read-only, and performed on August 30, 2026.
Official county pages and portal surfaces were loaded in a cloud browser. No login,
registration, CAPTCHA solving, response submission, notification enrollment, vendor
maintenance, invoice/payment endpoint, or other mutation was attempted. No HAR was
captured. Sanitized fixtures contain only stable labels and product indicators; they
contain no cookies, session IDs, CSRF tokens, ViewState/EventValidation values, or
downloaded production documents. Observations establish a point-in-time contract, not
continuous production availability.

## Official linkage

- Palm Beach County Procurement and Business Opportunities identify
  `https://pbcvssp.pbc.gov/vssprd/Advantage4` as the official and only solicitation
  advertisement surface.
- LA County's Doing Business portal links public solicitation discovery to LACoBids,
  Vendor Self Service to `lacovss.lacounty.gov`, and vendor registration to WebVen.

## Palm Beach County

The landing page is modern CGI Advantage4/Sofia. Stable evidence included an
`Advantage4` base path, Angular/Sofia assets, CGI Advantage branding, guest-session
configuration, `US/Eastern` server timezone, and a **View Published Solicitations**
action. The public grid returned 20 records on its first page and exposed keyword
search, quick scopes, additional fields, 20/50/100 page sizes, next/last paging, and
column sorting.

Two open records were inspected in the listing. One detail was opened:
`RFP-360-2026053-2`, **CEI Continuing Professional Services**. The detail exposed
department 360, buyer Holly Knight, a public government email and phone, issue and
closing dates, status, category/type, last-amended date, and 18 attachments. Closing
time was explicitly `EDT`. Anonymous **Respond** controls were disabled. The
attachments tab was anonymously visible, but a representative file was not downloaded
because no safe source HAR was available to preserve the exact session-bound request.

The page embeds per-session identifiers and a CSRF value in bootstrap state. Those
values were observed only to classify the contract and were not copied to fixtures or
committed. The exact anonymous Sofia action POSTs, error schema, attachment download
request, amendments, Q&A, awards, and closed-result behavior remain desktop-HAR work.

Result: Palm Beach is verified as CGI Advantage4, but the existing synthetic GET
`SolicitationSearch` contract does not match the observed stateful Sofia UI. Its profile
is therefore evidence-backed but fail-closed/disabled until a sanitized HAR establishes
the exact read-only actions.

## Los Angeles County surface resolution

| Surface | Classification | Observed relationship |
| --- | --- | --- |
| `lacovss.lacounty.gov` | CGI Advantage legacy AltSelfService; public guest plus authenticated VSS | Redirected to `/webapp/VSSPSRV11/AltSelfService`; **Public Access** opened a session-bound frameset. Public solicitations were visible. Login/activation gates responses and account maintenance. |
| `camisvr.co.la.ca.us/LACoBids/` | Separate custom LA County public discovery application; not classified as CGI | Primary anonymous open and closed/awarded listing, search, sorting, paging, CSV listing, and detail routing. It links to VSS for online responses. |
| `camisvr.co.la.ca.us/Webven/` | Vendor registration/maintenance | LACoBids and VSS describe WebVen as registration/profile maintenance, not the anonymous discovery contract. |

The legacy CGI public frameset exposed detailed search fields for commodity,
solicitation number, department, description, type, and status, plus quick views for
open, closing soon, recently published/amended, intents, and awards. It showed open
records with stable solicitation numbers, departments, types, publish/amend/close dates,
status, and `PDT` timezone. Its session ID is URL-bound; no value was retained.

LACoBids independently returned 223 open records, 10 per page, with page/size/sort
parameters in ordinary links. The listing provided solicitation number, title,
commodity, type, department, and close date. A public HTML form posts only the internal
`bidrefnbr` to `/LACoBids/BidLookUp/BidDetail`; search/sort uses a separate form. The
site also exposes a public CSV listing and a closed/awarded route. A complete detail,
attachment download, and award record were not exercised in this run, so those
contracts are not implemented or claimed.

Result: LA County is not one reusable Palm Beach-style contract. It has a legacy CGI
AltSelfService VSS for public browsing plus authenticated response/account functions,
and a separate custom LACoBids application that is the primary anonymous discovery
surface. WebVen is registration/maintenance. The legacy CGI profile is disabled until
its stateful POST/frameset contract is captured; LACoBids requires a separate connector
once detail and download requests are fully evidenced.

## Access matrix

| Capability | Palm Beach Advantage4 | LA legacy CGI VSS | LA custom LACoBids |
| --- | --- | --- | --- |
| Anonymous listing | Observed | Observed through Public Access | Observed |
| Anonymous detail | Observed (one detail) | Listing detail fields observed; full detail not exercised | Detail route/form observed; response not exercised |
| Search/filter/sort/page | Observed UI contract | Observed UI fields/quick views | Observed GET/form contract |
| Public attachment metadata | Observed (18 on one detail) | Not established | Not established |
| Anonymous document download | Not exercised | Not established | Not established |
| Amendments | Status/date observed | Quick view observed | Not established |
| Awards | Separate county page; not established in VSS | Recent Awards quick view observed | Closed/awarded route observed |
| Bid submission | Anonymous control disabled | Login required | Routed to VSS/login |
| CAPTCHA/WAF | None presented | None presented | None presented |

## Remaining desktop capture

1. Capture and sanitize Palm Beach listing/search/paging/detail/attachment action POSTs,
   including safe token placeholders and source HAR SHA-256.
2. Capture LA legacy Public Access bootstrap, frameset search/detail/paging and one
   attachment request; do not retain URL-bound session values in fixtures.
3. Exercise two LACoBids details, closed/award detail, representative attachment,
   keyword/number search, sorting and page-size POSTs, then implement that separate
   custom connector.
4. Preserve source HARs under an ignored evidence directory until merge and record all
   SHA-256 hashes here.

Coverage registry values were not promoted: browser observation is not scheduled live
success, and neither county is a primary statewide source in the current 56-jurisdiction
coverage model.
