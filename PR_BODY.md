## Motivation

Replace fixture-only PlanetBids assumptions with evidence-backed numeric portal profiles and rendered-listing support across a county buyer and a distinct education buyer.

## Tenants and official evidence

- County of Stanislaus, California — official active-bids page links to PlanetBids portal `14599`.
- Los Angeles County Office of Education (LACOE), California — official vendor page links to PlanetBids portal `61954`.

LACOE is preserved as an education entity, not Los Angeles County government or the City of Los Angeles. No fallback was required. See `docs/connector_validation/planetbids_two_tenants_2026-08-30.md`.

## Shared request contract and county/education findings

Both public portals use GET-navigable routes on `vendors.planetbids.com`: `/portal/{portal_id}/bo/bo-search` and `/portal/{portal_id}/bo/bo-detail/{opportunity_id}`. Rendered rows expose stable numeric IDs through `rowattribute`; the shared UI exposes keyword, type, category, stage, department, due-date, sorting, and detail navigation. Dates displayed in PDT are normalized with `America/Los_Angeles`.

Stanislaus exposes county departments, public-works solicitations, and County contacts. LACOE exposes education/service solicitations and remains buyer class `education`. Solicitation numbering and configured option vocabularies vary by tenant.

The exact background API/POST, pagination, tab, and document-download contracts were not captured in cloud mode, so none are invented or replay-authorized.

## Connector changes and public fields retained

- Adds profiles for portal `14599` and `61954`, official landing pages, legal names, buyer classes, authoritative detail templates, and numeric tenant IDs.
- Adds `vendors.planetbids.com` to the platform allowlist.
- Parses observed Ember rendered rows, stable IDs, solicitation numbers, titles, stage, posted/due dates, and Pacific timezone.
- Maps Bidding/Planning to canonical open status, retains source provenance, and deduplicates by profile plus authoritative opportunity ID.
- Preserves retry, timeout, circuit-breaker, unsafe-URL, malformed-markup, and injected/owned-client behavior.

## Attachments, authentication, CAPTCHA, and coverage

Document/addenda/Q&A/bidder/submission/award tabs were visible on configured opportunities, but their payload and representative download contract remain desktop work. The connector retains existing mixed public/login/registration/prospective-bidder document classifications only where fixture data supplies them. No login, registration, CAPTCHA, WAF challenge, or rate limit was encountered on the two direct public surfaces. Complete HARs, production documents, cookies, tokens, sessions, CSRF values, and browser material are not committed.

Coverage documentation now records two live-observed rendered portal surfaces. It does not claim scheduled production collection, attachment retrieval, pagination replay, or continuous availability.

## Validation

- `PYTHONPATH=src python -m unittest discover -s tests -v` — 347 tests, OK.
- `ruff check .` — all checks passed.
- `PYTHONPATH=src python -m compileall src tests` — passed.
- `PYTHONPATH=src python -m sled_aggregator.coverage validate` — 56 jurisdictions, 0 warnings, 0 errors.
- `PYTHONPATH=src python -m sled_aggregator.coverage recommend` — passed.
- `git diff --check` — passed.

## Limitations and remaining desktop work

Capture one bounded HAR per tenant, hash and retain each complete HAR locally, sanitize only exact anonymous request contracts, exercise filters/sorting/continuation, inspect at least two details per tenant, and download at most one clearly public solicitation document per tenant. Then add API-shaped fixtures and only the routes evidenced by those captures.

No complete HAR, production solicitation document, or secret is committed.
