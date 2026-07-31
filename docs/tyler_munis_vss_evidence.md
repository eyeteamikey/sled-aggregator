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
