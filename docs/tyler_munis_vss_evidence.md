# Tyler Munis/VSS evidence record

**Implementation review date:** 2026-07-31
**Evidence gate:** passed for Summit County, Ohio and the City of Opelika, Alabama

Sanitized manual evidence supplied for this task confirmed the same anonymous public
contract on both tenants: GET the VBids selector/search page; POST current ASP.NET form
state and public criteria; GET/POST `SearchResults.aspx`; select a result through its
advertised postback; follow a same-host redirect to `Detail.aspx`; and retrieve eligible
files with GET from `DocumentViewer.ashx`. Captures showed public PDF files on both
sites and public Microsoft Word files on Summit. No authorization header was required.
Raw HAR files and all live cookies, Web Forms values, antiforgery material, document
tokens, hashes, and signed URLs were excluded from the repository.

Synthetic fixtures verify only the parser and transport contract. They use obvious test
values and do not establish current live availability. Minimal anonymous GET validation
from the task environment was attempted for both selector URLs, but the environment's
outbound proxy rejected each CONNECT tunnel with HTTP 403 before destination TLS; this
is an environment limitation rather than portal access evidence.

Mobile, Alabama remains researched but unsupported. The observed
`mobileselfservice.tylertech.com` endpoint was citizen self service, and no anonymous
public `Vendors/VBids` workflow was captured. No Mobile preset or coverage claim exists.

The supported workflow never logs in, registers, enters a response, submits a bid,
modifies a vendor record, solves CAPTCHA, or follows an identity-provider transition.
See `docs/tyler_munis_vss.md` for security boundaries and tenant-onboarding procedure.

## Summit County request-contract validation (2026-08-12)

A second successful anonymous Summit County capture contained 1,493 requests, including
ten successful search POSTs, ASP.NET GridView pagination and sorting postbacks, two bid-detail
transitions, and twenty successful `DocumentViewer.ashx` responses. The capture proved the
live controls `BidTypeDropBox`, `BidNumber`, `BidDescription`, and `OpenBidsOnly`; result columns
for type, number, description, due date, opening date, and status; row-specific `ViewLink`
postbacks; and `page:*` postback arguments used by the grid.

The connector and fictional fixtures now cover those observed contracts. The full capture is
not repository evidence: cookies, ASP.NET state, document tokens and hashes, and binary bodies
were removed during local review, and the HAR is deleted from the intake directory only after
the implementation PR is merged. Third-party reCAPTCHA resources appeared in browser traffic,
but no first-party response presented a CAPTCHA and the public search, detail, and document
flows completed anonymously. Awards and amendments were not separately established.
