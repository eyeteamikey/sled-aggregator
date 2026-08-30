# Euna OpenBids / DemandStar two-tenant validation — 2026-08-30

This point-in-time validation used anonymous browser pages and bounded public HTTP requests only. No account, credential, CAPTCHA bypass, notification enrollment, question, bid submission, complete HAR, cookie, token, browser profile, or production document was committed. No source HAR was captured in this cloud session.

## Authoritative linkage and identifiers

| Tenant | Official evidence | Modern agency UUID | Legacy member ID |
| --- | --- | --- | --- |
| Will County, Illinois | The county Current Bids page links “DemandStar Bids” to member `122067`; the legacy application route rendered the modern Will County page. | `34dea608-18ea-4dae-ab75-e117314d8f28` | `122067` |
| Ramsey County, Minnesota | The county says most opportunities are published on DemandStar and links member `686378`; its supplied UUID page rendered the same Ramsey County records. | `98cdb2f5-ed67-485d-8b2e-291e644403e5` | `686378` |

Direct portal pages:

- Will: `https://www.demandstar.com/app/agencies/illinois/will-county/procurement-opportunities/34dea608-18ea-4dae-ab75-e117314d8f28`
- Ramsey: `https://www.demandstar.com/app/agencies/minnesota/ramsey-county/procurement-opportunities/98cdb2f5-ed67-485d-8b2e-291e644403e5/`

## Shared anonymous contract

Both tenants exposed the previously observed agency-scoped contract on `https://api.demandstar.com/contents/agency`:

- `GET /search?id={agency_uuid}` returns a fixed agency result set (`total: 100` was observed for each tenant), ordered newest broadcast first. Each row includes numeric `bidId`, public bid identifier, agency, broadcast/due dates, status/status type, planholder count, and the matching legacy `mi`.
- `POST /summary` with only `bidId` returns details, scope, public type, buyer name, broadcast/due/open timestamps, Central timezone labels, and status. `bidExternalStatus` is the status; `bidStatusText` is tenant-authored narrative and must not be normalized as status.
- `POST /documents` with only `bidId` returns attachment IDs, names, types, MIME types, sizes, modified dates, and status. Observed `path` values were empty.
- `POST /commodityByType` with `bidId` and `type: "Bid"` returns public category codes/descriptions.
- `POST /planholders` with only `bidId` returns public supplier/planholder names and contact metadata.
- `POST /legal` with only `bidId` returns public buyer/contact and legal-notice metadata.

No authorization header, CSRF value, or pre-established browser cookie was required for these bounded calls. Cloudflare set a routine public cookie, but it was neither needed by the connector nor retained. No CAPTCHA, WAF denial, or rate-limit response was observed.

Only those exact routes and bodies are approved. There is no unrestricted POST facility.

## Tenant observations

| Capability | Will County | Ramsey County |
| --- | --- | --- |
| Agency page / listing | Public; active and under-evaluation records visible | Public; active and under-evaluation records visible |
| Two details | Numeric bids `547102`, `544920` | Numeric bids `547728`, `547732` |
| Search / filters | API has no observed query vocabulary beyond agency UUID; connector keyword, status, and date filtering is bounded locally | Same |
| Sorting | Public results observed newest broadcast first; no separate sort parameter evidenced | Same |
| Pagination | No cursor/page contract observed; agency response was a single bounded set of 100 | Same |
| Type / department | Bid type public; no department field observed on reviewed records | Same |
| Dates | Naive API timestamps are labeled Central by the detail payload/UI | Same |
| Contacts | Buyer name public; `legal` can expose public phone/title | Same |
| Attachments/addenda | Metadata public; empty paths classify files as registration-required | Same |
| Q&A | No distinct public route or structure observed | No distinct public route or structure observed |
| Awards/vendors | Planholders public; no distinct award/vendor response observed | Planholders public; no distinct award/vendor response observed |
| DemandStar document download | “Download Bid Package” opened a login dialog | Registration is required per official county guidance |
| Alternate public document | County Current Bids `FileId/130580` returned a 3,605,052-byte PDF anonymously; bytes were discarded | Not observed |

The Will county-hosted bid board provides public solicitation, addendum, tabulation, and award files independently of DemandStar. This does not make the empty-path DemandStar document records anonymously downloadable.

## Modern versus legacy behavior

Legacy numeric member links are agency locators, not opportunity IDs. Will member `122067` rendered the UUID-based modern agency route in the browser. Ramsey’s official member `686378` corresponds to the UUID page and the API search rows repeat `mi: 686378`. Both modern pages use `/app/limited/bids/{numeric-bid-id}/details`; numeric `bidId` is the authoritative opportunity identity used for deduplication.

The modern and legacy surfaces therefore share tenant identity and opportunity records, while using different agency locator forms. The reusable connector stores both identifiers explicitly.

## Live evidence versus fixture coverage

Live-observed: official linkage, initial pages, listing shape, two details per tenant, identifiers, statuses, types, descriptions, Central timestamps, buyer names, planholders, document metadata, categories, legal/contact data, login-gated DemandStar download, Will’s alternate public PDF response, and absence of encountered CAPTCHA/WAF/rate limiting.

Fixture-tested: tenant resolution, UUID/member pairing, exact route/body construction, bounded results, local keyword/status/date behavior, stable numeric identity, status and timezone normalization, public contact/planholder retention, gated attachment classification and parent linkage, malformed-response failure, retry/timeout/circuit behavior, and HTTP client ownership.

Not established: a server-side keyword/filter/sort vocabulary, pagination/load-more API, question deadline, public Q&A, award/vendor endpoint, anonymous DemandStar document bytes, or continuous production availability. A desktop browser HAR is still required to determine whether UI-only requests expose any of those contracts. Source HAR hash: not applicable (no HAR captured).
