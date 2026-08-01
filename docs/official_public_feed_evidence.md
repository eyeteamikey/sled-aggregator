# Official public procurement feed evidence gate

**Review date:** 2026-07-31  
**Gate result:** not passed; no connector or production profile was created

## Decision

The coverage-audit phrase “public CSV, RSS, XML, and JSON feeds” was a planning
hypothesis, not evidence of a feed contract. This review did not establish two
independently operated qualifying feeds, or one qualifying statewide or
territory-wide feed. Adding `official/public-feed`, aliases, fixtures, or source
coverage in that state would invent response contracts and access claims.

The task environment's outbound proxy rejected each attempted HTTPS CONNECT
tunnel with HTTP 403 before destination TLS. That result says nothing about the
publisher's access policy. It prevented observation of status, final host,
content type, records, IDs, titles, links, pagination, conditional-request
support, authentication, CAPTCHA, rate limits, and robots policy.

## Candidates evaluated

| Candidate | Official candidate location | Why evaluated | Result and missing evidence |
|---|---|---|---|
| New York City City Record Online / NYC Open Data | `https://www.nyc.gov/site/cityrecord/index.page`; `https://data.cityofnewyork.us/` | The official City Record publishes procurement notices and the official open-data portal is a plausible machine-readable publisher. | **Unsupported candidate.** The environment could not retrieve either the catalog metadata or a resource response. No exact official dataset identifier, active-opportunity semantics, stable fields, license/terms, MIME type, pagination, or anonymous response contract was reproduced. |
| Massachusetts COMMBUYS | `https://www.commbuys.com/bso/` and `https://data.mass.gov/` | COMMBUYS is the Commonwealth's official procurement system, and the official data catalog was checked for a current-opportunity export. | **Unsupported candidate.** No official catalog record directly linking a current-solicitation feed to COMMBUYS was retrievable. A browser search/export is not assumed to be a stable public feed. |
| District of Columbia open data and procurement | `https://opendata.dc.gov/`; `https://ocp.dc.gov/` | Both are official District properties and could plausibly publish current solicitations as open data. | **Unsupported candidate.** No authoritative dataset-to-current-opportunity relationship or machine response was reproduced. Contract, purchase-order, and spending datasets would not qualify merely because they are procurement-related. |
| Guam General Services Agency bids | `https://gsa.doa.guam.gov/bids/` | An official territory procurement page could satisfy the single-feed exception if it exposed substantial territory-wide machine-readable opportunities. | **Unsupported candidate.** No official CSV, RSS, XML, or JSON endpoint, stable record contract, or territory-wide scope was established. An HTML bids page alone does not pass the feed gate. |
| U.S. Virgin Islands Department of Property and Procurement | `https://dpp.vi.gov/` | An official territory procurement authority could satisfy the single-feed exception if it exposed a territory-wide public feed. | **Unsupported candidate.** No machine-readable active-opportunity endpoint, response contract, or anonymous live behavior was reproduced. |

These are candidates, not coverage sources. They are intentionally absent from
`data/coverage/sources.json` and no jurisdiction is credited.

## Minimal live-validation record

One anonymous GET attempt was made per candidate property, with the user agent
`sled-aggregator-evidence/1.0`, a 15-second timeout, and redirects enabled. No
credentials, cookies, form submissions, browser automation, CAPTCHA handling,
or document downloads were used.

| Date | Candidate hosts | Task result | Destination result |
|---|---|---|---|
| 2026-07-31 | `www.nyc.gov`, `data.cityofnewyork.us` | Proxy HTTP 403 during CONNECT | Not observed |
| 2026-07-31 | `www.commbuys.com`, `data.mass.gov` | Proxy HTTP 403 during CONNECT | Not observed |
| 2026-07-31 | `opendata.dc.gov`, `ocp.dc.gov` | Proxy HTTP 403 during CONNECT | Not observed |
| 2026-07-31 | `gsa.doa.guam.gov` | Proxy HTTP 403 during CONNECT | Not observed |
| 2026-07-31 | `dpp.vi.gov` | Proxy HTTP 403 during CONNECT | Not observed |

There are therefore no live-validation claims about response status, format,
records, identity fields, links, authentication, CAPTCHA, rate limits, or
robots policy. There are also no sanitized feed fixtures: a synthetic schema
without an observed authoritative contract would not satisfy the gate.

## Evidence required to resume

For at least two independently operated authorities—or one source with
substantial statewide or territory-wide coverage—retain all of the following:

1. An official page or official catalog record directly linking the exact feed.
2. A single bounded anonymous response captured with retrieval date, final host,
   status, MIME type, encoding, and applicable public-use terms.
3. Proof that records are active or recent solicitations rather than awards,
   payments, registrations, spending summaries, meetings, or archives.
4. Observable stable identity and meaningful title fields, plus documented
   date, link, attachment, filtering, and pagination semantics where present.
5. Conditional-request observations (`ETag` or `Last-Modified`) if offered.
6. A small sanitized fixture derived from—not invented for—the observed
   contract, with personal data, tokens, cookies, and signed URLs removed.
7. A host/redirect review and confirmation that anonymous read-only collection
   is not prohibited by applicable terms or access controls.

Only then should a profile-driven connector implement the evidenced formats.
Unsupported formats and guessed pagination must remain absent.
