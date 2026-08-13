# Batch 1 HAR evidence review — 2026-08-13

Eight anonymous browser captures were reviewed locally. Complete HARs, cookies, session values,
browser telemetry, signed document URLs, and binary response bodies are excluded from Git.
Public procurement contacts, solicitation metadata, attachment metadata, and provenance were
treated as domain data during review. The records below prove only the observed request and
access contracts, not continuous production availability.

## Successful public contract captures

- **Opelika Tyler Munis/VSS:** anonymous search POSTs, GridView pagination, bid details, and public
  PDF/XLSX document retrieval succeeded. Third-party reCAPTCHA resources loaded, but no
  first-party challenge interrupted these read-only flows. Together with Summit County, this
  supplies the second independently operated tenant for the reusable Tyler Munis/VSS family.
- **Massachusetts COMMBUYS / Periscope BuySpeed:** anonymous JSF search/filter/pagination, ten
  details, exports, and public document responses succeeded. One detail returned HTTP 401, so
  document/detail access remains mixed and the connector must fail closed on restricted records.
- **Iowa IMPACS and Utah U3P / JAGGAER SciQuest:** anonymous public-event search/filter traffic and
  public PDF downloads succeeded on two tenants. Opening the sourcing-event application redirected
  to `SupplierLogin`; this establishes a login boundary for that detail/participation route and is
  not evidence for login automation.

## Access-boundary and failure captures

- **Connecticut CTsource and Rhode Island Ocean State Procures / WebProcure:** public JSON search,
  solicitation-detail, Q&A, and PDF traffic was observed, but the operator encountered reCAPTCHA.
  Both are recorded as `captcha_present`; they do not establish unattended anonymous discovery
  and no CAPTCHA bypass is implemented or proposed.
- **Michigan SIGMA CGI Advantage:** the attempted `Advantage4/SolicitationSearch` surface returned
  only HTTP 404 responses. The capture is recorded as unavailable/changed-route evidence, not a
  successful validation.
- **Maine VSS CGI Advantage:** the attempted `AltSelfService/SolicitationSearch` surface produced
  404, 403, and failed requests without a usable solicitation workflow. It is recorded as blocked
  evidence, not a successful validation.

## Reviewed capture hashes

| Source | Intake filename | SHA-256 |
|---|---|---|
| Opelika | `opelika-al.har` | `ca4fdef8ec6c615c11e79854e01e8471408000b89c0c0d8610d6b49d6d1cc0cf` |
| COMMBUYS | `commbuys-periscope.har` | `9c44ad152cdbf5851b0fc1f8ee4fa1a983bd703b2835dba4c3f0a68810648ea8` |
| Maine VSS | `hostams-cgi-advantage-vss.har` | `71bd9300162461008ff57f8dd050fbba89ea9bc418965a4c74ab81afff0b952e` |
| Michigan SIGMA | `michigan-cgi-advantage-vss.har` | `776d78b4e70883670024ca8765a4fa998e5aa8db5d616f68e8971523ec4318c5` |
| Iowa IMPACS | `Iowa-sciquest-jagger.har` | `a63a3aba7169c15a55026a06b48d0132316c1a7bffb14d80e03182575e3bfe39` |
| Utah U3P | `utah-sciqueest-jagger.har` | `bce5e966211d907c4617dd2f03973fb2bd36ecf46623281ae4c320ef8bde9e39` |
| CTsource | `Connecticut-CTsource-webprocure.har` | `e0fb4490e695a31ded7b296bb96a0aab03471b1b0a03b85674ab1d9418a83f0d` |
| Ocean State Procures | `RhodeIsland-webprocure.har` | `ee5a5def3878b0f5ab42a5112e8916bfb68b0ae88a518301b9831e7199ecbd95` |

The processed intake files remain local until the evidence and registry PR is merged. After merge
verification, delete only those files and retain `sled-har-evidence/README.md` and the directory.
