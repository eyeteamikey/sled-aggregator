# Tyler Munis Vendor Self Service connector

The `tyler/munis-vss` connector supports the fixture-verified anonymous public bid
boards for **Summit County, Ohio** and the **City of Opelika, Alabama**. These are local
presets only; they do not imply statewide Ohio or Alabama coverage.

## Evidence and public boundary

Sanitized manual captures established the shared `Vendors/VBids` Web Forms contract:
a public entry/search GET, state-bearing POST search, `SearchResults.aspx` grid
postbacks, row-selection postback and same-host redirect to `Detail.aspx`, and public
`DocumentViewer.ashx` GET retrieval. Synthetic fixtures verify the implementation;
they contain conspicuous test state only and are not raw HAR extracts. Minimal live
GETs during development are documented separately from fixture-backed claims.

The connector owns an anonymous cookie session unless a client is injected. It obtains
fresh `__VIEWSTATE` and optional Web Forms fields from each current page. Search,
pagination, and row selection require POST because those are public Web Forms
navigation transitions, not bid submissions. Missing required state fails closed.
Documents remain GET-only and pass to the existing document candidate/downloader
boundary; the connector does not implement another downloader.

Temporary document `token` and `hash` parameters may expire. They are redacted from
metadata and excluded from stable identity. A fresh retrieval URL can be reacquired by
replaying public search/detail navigation. Login, Portico/identity, VendorCheck,
registration, response entry, password forms, cross-host redirects, CAPTCHA, or any
account operation stop as restricted access. Anonymous cookie names alone do not imply
an authenticated identity.

Mobile, Alabama is intentionally unsupported: the observed
`mobileselfservice.tylertech.com` hostname exposed citizen self service and no public
VBids contract was captured.

## Adding a tenant safely

1. Capture two or more sanitized anonymous public pages proving the common route and
   markup; never retain cookies, real Web Forms state, tokens, hashes, or signed URLs.
2. Add a profile with an HTTPS base, exact hostname allowlist, local jurisdiction, and
   conservative page/result/resilience bounds.
3. Add synthetic fixtures for search, pagination, details, documents, empty/malformed
   pages, and access boundaries. Verify every redirect and runtime link.
4. Mark coverage fixture-only until bounded live validation independently confirms the
   tenant. Never automate login, registration, vendor response, or CAPTCHA.

Known limitations: markup is parser-contract sensitive; detail URLs are session
navigation rather than permanent record URLs; expiring document URLs require replay;
and availability can vary by tenant. Sorting is not requested because discovery needs
only the exact pager event advertised by the current page.
