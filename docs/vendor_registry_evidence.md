# Vendor Registry evidence record

**Review date:** 2026-08-01  
**Evidence gate:** failed; anonymous discovery was not reproduced

## Result

Vendor Registry remains unsupported. No connector, alias, tenant profile, fixture, source
record, or jurisdiction coverage is added. In particular, an indexed or supplied
`https://vrapp.vendorregistry.com/Bids/View/Bid/{solicitation-guid}` detail route is only a
research lead: a detail URL does not establish a current agency-scoped listing contract.

The review considered the distinct public agency notice, vendor registration, vendor account,
electronic response, and paid Lead Center products. Only the first is in product scope. The task
environment did not provide manual captures and its outbound proxy rejected HTTPS CONNECT for
both government and Vendor Registry destinations with HTTP 403 before destination TLS. The web
research integration also returned HTTP 401. These are environment limitations, not evidence of
a login wall, CAPTCHA, or publisher response.

## Candidates checked

The task-provided leads were checked conservatively on 2026-08-01:

| Candidate | Government evidence sought | Vendor Registry evidence sought | Observation |
|---|---|---|---|
| Rockdale County, Georgia | A current official purchasing page linking directly to the agency's Vendor Registry listing | One agency listing and one advertised detail | HTTPS CONNECT rejected before destination TLS; no contract observed |
| City of Forest Hills, Tennessee | A current official bids/procurement page linking directly to Vendor Registry | One agency listing and one advertised detail | HTTPS CONNECT rejected before destination TLS; no contract observed |
| City of Germantown, Tennessee | A current official purchasing page linking directly to Vendor Registry | One agency listing and one advertised detail | HTTPS CONNECT rejected before destination TLS; no contract observed |
| Generic `vrapp.vendorregistry.com` listing lead | An agency identifier anchored by an official-government link | Listing route, method, parameters, paging, and empty-state semantics | HTTPS CONNECT rejected before destination TLS; no endpoint or identifier inferred |

Search results and guessed government paths were not promoted to evidence. No HTTP status from a
publisher, final destination hostname, authentication state, CAPTCHA state, pagination behavior,
document state, addition/addendum/Q&A/award visibility, or markup contract was observed. No public
document was requested.

## Missing contract

Implementation requires sanitized evidence from at least two independently operated agencies
showing the same structural contract. For each agency it must establish:

1. the official government page and its direct Vendor Registry link;
2. the initial anonymous listing request, redirects, request method, safe parameters, stable
   agency identifier, response type, open/current semantics, and empty state;
3. any background request, filtering, pagination origin, termination signal, repeated-page
   behavior, and maximum practical page size;
4. the advertised detail request and stable solicitation GUID;
5. visible fields and the representation of additions, addenda, questions, amendments, and awards;
6. each document's advertised URL and whether it is public, registration-required,
   login-required, unavailable, metadata-only, or unknown; and
7. login, registration, subscription/Lead Center, CAPTCHA, migration, and unexpected-markup states.

Do not infer request bodies, antiforgery fields, tenant identifiers, pagination, or file URLs from
route names or search indexing. A public detail page without an anonymous agency listing remains
detail-only evidence and cannot support independent discovery.

## Bounded HAR capture procedure

1. Start a fresh private browser session with no Vendor Registry cookies, extensions, saved
   credentials, proxy rewriting, or vendor account. Open developer tools, enable Preserve Log,
   disable cache, and record only Fetch/XHR and Document requests.
2. Navigate first to the official government purchasing page and follow its current solicitation
   link. Record the official URL, retrieval time in UTC, redirect chain, final hostname, status,
   content type, and whether any challenge or authentication prompt appears.
3. Load the default open/current listing once. If the UI advertises filters, perform at most one
   keyword, one solicitation-number, and one status filter. Advance exactly one page and return.
   Record the initiating request for each action and the response shape; do not explore Lead Center.
4. Open one solicitation advertised by that listing. Record only the public detail request and
   whether the displayed agency and stable GUID agree with the listing.
5. Inspect document metadata. If a clearly public, small file is advertised, make at most one GET
   without accepting terms. Otherwise record the visible gate label and do not click login,
   registration, questions, response, or submission controls.
6. Repeat for a second independently operated government agency, then stop.
7. Export the HAR locally for review, but do **not** commit it. Create minimal synthetic fixtures
   retaining only structural field names and invented values. Remove cookies, authorization,
   antiforgery values, query tokens, signed URLs, analytics, personal data, and response bodies not
   needed to reproduce parsing. Record hashes of the reviewed local captures outside the repo.

Only after that comparison confirms a reusable, anonymous, agency-scoped listing and detail
contract should `vendor-registry` be implemented. Profiles must use exact HTTPS allowlists and
must never store cookies, tokens, temporary file URLs, or authenticated state.

## Public-only boundary and known limitations

The future connector, if supported, may read deliberately public agency solicitations only. It
must not register or log in, use the paid Lead Center, search commercial cross-agency data, submit
bids, begin responses, ask questions, enumerate plan holders, construct hidden file URLs, reuse
signed URLs, solve CAPTCHA, or carry authenticated cookies. Current authentication, CAPTCHA,
listing, detail, and document behavior are all **unknown**, not public or gated. Because the gate
failed, coverage impact is zero and no Georgia- or Tennessee-wide claim is made.
