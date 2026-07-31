# Tyler Munis/VSS anonymous-access evidence review

**Review date:** 2026-07-31  
**Outcome:** evidence gate not passed; no connector or source preset was added

## Scope and method

This review tested only anonymous, read-only retrieval. It did not register a
vendor, authenticate, provide credentials, solve a CAPTCHA, evade a control, or
access vendor-account data. Direct requests used `GET`, followed ordinary
redirects, and supplied no cookies, authorization headers, form data, or session
state.

The review environment's outbound proxy rejected a CONNECT tunnel to every
named agency and portal host with HTTP 403 before a TLS connection to the
destination could be established. Consequently, the response is an
environmental technical block, not evidence of a policy or access decision by
any agency or by Tyler.

## Candidate results

| Tenant | Authoritative agency source | Exact candidate portal | Anonymous result | Account boundary | CAPTCHA, robots, and technical result | Common markup |
| --- | --- | --- | --- | --- | --- | --- |
| Summit County, Ohio | <https://www.summitengineer.net/pages/For-Contractors-Vendors-Partners.html> | <https://summitcountyoh.munisselfservice.com/vss/default.aspx> | Not observed. Both direct requests were stopped by the outbound proxy. | Unknown; neither login nor registration UI was retrieved. | Proxy CONNECT returned 403. Destination CAPTCHA and robots policy were not observed. | Not observed. |
| Mobile, Alabama | No separate authoritative agency page was established in this review. | <https://mobilevendorselfservice.tylertech.com/default.aspx> | Not observed; the direct request was stopped by the outbound proxy. | Unknown; neither login nor registration UI was retrieved. | Proxy CONNECT returned 403. Destination CAPTCHA and robots policy were not observed. | Not observed. |
| Opelika, Alabama | No separate authoritative agency page was established in this review. | <https://ss.opelika-al.gov/vss/default.aspx> | Not observed; the direct request was stopped by the outbound proxy. | Unknown; neither login nor registration UI was retrieved. | Proxy CONNECT returned 403. Destination CAPTCHA and robots policy were not observed. | Not observed. |

The Summit County URL supplied for this review describes the intended agency
relationship, but its contents could not be independently retrieved in the
review environment. A portal's name or product branding alone is not treated as
proof of anonymous solicitation access.

## Gate assessment

The mandatory gate fails because no destination response was available to
demonstrate any of the following:

1. two independent government tenants with anonymous solicitation listings;
2. a reusable route and markup contract;
3. anonymous opportunity details;
4. per-document access classifications;
5. observed search and pagination behavior; or
6. destination HTTP methods beyond the attempted initial anonymous `GET`.

Login, registration, CAPTCHA, robots-policy, and automated-access boundaries
also remain unknown. No fixture can be derived faithfully from a destination
response, so fixtures, portal presets, registry entries, coverage claims, and
connector code would be speculative and were intentionally not created.

## Evidence needed to resume

Repeat the review from an environment that can reach the named hosts. Preserve
only sanitized public evidence:

- the authoritative government page linking each portal;
- anonymous listing/search responses for at least two independent tenants,
  including an empty result and a genuine next-page action;
- the exact request method, route, query/form keys, redirect chain, and stable
  markup used by search and pagination;
- an anonymous detail response for at least one tenant;
- document rows and the result of following each distinct document-link class,
  sufficient to distinguish public files, metadata-only links, registration,
  login, enrollment, restriction, unavailability, and unknown access;
- destination `robots.txt` and any CAPTCHA, login, registration, enrollment,
  rate-limit, or automated-access response encountered; and
- evidence of external or migrated solicitation systems where applicable.

If browser capture is necessary for a stateful anonymous search, provide a
sanitized HAR or equivalent request transcript with cookies, authorization,
antiforgery values, credentials, session identifiers, personal/vendor data,
signed URLs, and downloaded solicitation bodies removed. The capture must show
that any `POST` performs public search or navigation only and does not create or
modify a business record.
