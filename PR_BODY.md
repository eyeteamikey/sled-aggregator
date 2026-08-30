## Tenants validated

- Will County, Illinois — official county Current Bids page and DemandStar legacy member `122067`; modern UUID `34dea608-18ea-4dae-ab75-e117314d8f28`.
- Ramsey County, Minnesota — official county contracting page and DemandStar legacy member `686378`; modern UUID `98cdb2f5-ed67-485d-8b2e-291e644403e5`.

## Official evidence and shared request contract

Both official county pages link DemandStar. Anonymous browser validation and bounded HTTP replay established the existing `https://api.demandstar.com/contents/agency` family contract:

- `GET /search?id={agency_uuid}`
- `POST /summary` with `bidId`
- `POST /documents` with `bidId`
- `POST /commodityByType` with `bidId` and `type: Bid`
- `POST /planholders` with `bidId`
- `POST /legal` with `bidId`

No authorization header, CSRF value, or pre-established cookie was required. Only those exact anonymous read-only routes/bodies remain implemented; there is no unrestricted POST support.

## Modern / legacy behavior

The legacy numeric member ID locates the agency, while the modern route uses an agency UUID. API search rows repeat the legacy `mi`, and public details use numeric `/app/limited/bids/{bidId}/details`. Numeric `bidId`, namespaced by tenant profile, is the stable authoritative opportunity identity.

## Code, profiles, fixtures, and tests

- Adds live-observed Will and Ramsey profiles with UUID and legacy member IDs.
- Fixes status normalization to use `bidExternalStatus`; `bidStatusText` is retained as narrative.
- Interprets naive timestamps in the tenant's evidenced `America/Chicago` timezone.
- Preserves bid type, buyer, public contact, planholder, legal, attachment, and raw provenance fields.
- Adds two compact, synthetic fixtures derived from observed response shapes.
- Adds regression coverage for tenant resolution, modern/legacy IDs, exact method/route construction, bounds/local filters, stable identity, timezone/status/contact normalization, registration-gated documents, malformed responses, and shared behavior. Existing retry, timeout, circuit, SSRF, and client-ownership tests remain green.

## Attachments, authentication, CAPTCHA, and awards

Document metadata is anonymous on both tenants, but reviewed records returned empty document paths. The public “Download Bid Package” action opened login, so connector candidates remain `registration_required` and are not sent to the downloader. Will County independently serves public files from its county-hosted Current Bids page; one representative PDF returned HTTP 200 and its bytes were discarded.

Ramsey's official page states registration/subscription is free and provides documents/results. No registration or subscription was performed. No CAPTCHA, WAF denial, or 429 was encountered. Planholder/vendor data was public. No distinct anonymous award/vendor-result or Q&A route was observed, so none was added.

## Coverage changes

Adds live-public local coverage records for both counties, marks DemandStar detail metadata public and document download registration-required, records award/Q&A as unknown, and regenerates authoritative coverage reports. Fixture success is not presented as production proof; the records cite the dated live browser/API evidence.

## Validation

- `PYTHONPATH=src python -m unittest discover -s tests -v` — 341 tests passed.
- `ruff check .` — passed.
- `PYTHONPATH=src python -m compileall src tests` — passed.
- `PYTHONPATH=src python -m sled_aggregator.coverage validate` — 56 jurisdictions, 0 warnings, 0 errors.
- `PYTHONPATH=src python -m sled_aggregator.coverage recommend` — passed; 23 recommendations.
- `git diff --check` — passed.

The repository virtual environment was used because the system interpreter lacks project dependencies; SOCKS proxy variables were excluded during tests because the environment does not include optional `socksio`.

## Limitations and remaining browser work

- No source HAR was captured in this cloud session; no HAR hash is claimed.
- A desktop HAR is still needed to determine whether UI-only keyword/category/department/date filters, alternate sorting, pagination/load-more, Q&A, amendments, and award requests exist.
- The observed API returned a single fixed agency set (100 for each tenant) newest-first; the connector performs bounded keyword/status/date filtering locally and does not invent server parameters.
- No claim of continuous production availability is made.

## Evidence safety

No complete HAR, production document, cookie, token, credential, session material, CSRF value, archive, or browser profile is committed. There were no newly captured source HARs to preserve; the ignored evidence directories remain ignored.
