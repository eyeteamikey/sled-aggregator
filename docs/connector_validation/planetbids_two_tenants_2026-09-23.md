# PlanetBids two-tenant validation — 2026-09-23

## Scope

Two independently operated California education/county tenants were reviewed from locally
retained, Git-ignored browser HARs. No login, registration, bid response, question submission,
addendum acknowledgement, prospective-bidder enrollment, CAPTCHA bypass, or portal mutation was
performed. Complete HARs and downloaded production documents are not committed.

| Tenant | PlanetBids agency ID | Sanitized HAR SHA-256 |
| --- | ---: | --- |
| Stanislaus County | `14599` | `095f83c234b46e7a384e326fc575f7694a79e8dcc1eaa25a46fec883cbf2db8c` |
| Los Angeles County Office of Education | `61954` | `024950371f3b9bdcc67b43185a22b0a295b72879b044354f0503b5bfe820873a` |

## Shared anonymous contract

Both tenants used the same `https://api-external.prod.planetbids.com/papi` JSON:API family.
Observed read-only GETs covered:

- bounded `/bids` discovery with `cid`, page, page size, stage, department, bid type and sort;
- `/bid-details/{id}` details, contacts, restrictions, dates, categories and award/result flags;
- `/bid-downloadable-files` attachment metadata;
- `/bid-addenda` and included addendum-attachment metadata;
- `/bid-q-and-a-items`, `/bid-email-history-items`, `/pre-bid-meetings`, and prospective bidders;
- LACOE line items; and
- agency, department, category, bid-type, configuration and server-time lookup data.

The listing response supplied `totalBids` and `totalPages`. Tenant identity appeared as the
`cid` query value and `company-id` request header. Anonymous `user-context` and pin calls returned
400, while an OAuth refresh attempt returned 401; these are treated as user-feature boundaries,
not prerequisites for the successful public GET contract. The connector does not replay them.

A minimal cookie-free direct GET from the validation environment on 2026-09-27 returned HTTP 403.
No browser-identification, visit identifier, OAuth refresh, CAPTCHA solution, or session material
was added to force access. The connector therefore retains the HAR-verified contract while
classifying a current 403 as `restricted` or `captcha_required` when the response identifies a
human-verification challenge. This is not represented as unattended live availability.

## Documents and boundaries

Both tenants exposed downloadable-file metadata anonymously, including stable IDs, titles,
filenames, sizes, upload timestamps and a PlanetBids file host/path. Stanislaus additionally
recorded one representative PDF response from `files-prod01.planetbids.com` with HTTP 200.
That single download does not establish universal public retrieval. Derived fixtures therefore
classify ordinary listed files as `public_metadata_only` and prevent automatic retrieval unless
a file is separately proven public.

Opportunity-level restrictions such as invitation-only configuration, prospective-bidder
participation and response actions remain explicit boundaries. Public metadata must not be used
to infer permission to join a bidder list, acknowledge an addendum, submit a response, or access
restricted vendor content.

## Derived implementation

The shared connector now contains production presets for both agency IDs, parses the observed
JSON:API resource envelope, follows `totalPages`, retains tenant-qualified identity and source
provenance, enriches details from the observed public supplement routes, and creates conservative
attachment candidates. Tests use minimal fictional JSON fixtures containing only the observed
field and envelope shapes.
