# Connector-Family HAR Validation Roadmap

Operational planning for portals that require human assistance is documented in the
[Human-Assisted HAR Capture Game Plan](../human_assisted_har_capture_gameplan.md).

## CODEX CLOUD PUBLICATION WORKFLOW

For every evidence-ingestion or connector-correction task:

1. Confirm the repository is `eyeteamikey/sled-aggregator` and the base branch is current `master`.
2. Create a dedicated `agent/<description>` feature branch from `origin/master`.
3. Never commit a complete HAR, HAR archive, downloaded production attachment, browser profile, cookie, CSRF/XSRF token, ViewState, session identifier, authorization header, or credential.
4. Place local captures in `sled-har-evidence/`; everything except that directory's tracked README is ignored by Git.
5. Record the capture filename, SHA-256, portal, tenant, date, anonymous actions exercised, and access limitations.
6. Review the HAR before deriving fixtures. Preserve useful public procurement data—buyer and agency contacts, public email addresses and telephone numbers, public vendor/award fields, solicitation metadata, amendments, attachment metadata, and provenance—while removing authentication/session secrets.
7. Derive only minimal deterministic fictional fixtures. Use reserved domains such as `example.invalid` and fictional `555` telephone data.
8. Implement only request contracts observed in the reviewed evidence. Do not invent routes, automate login or registration, bypass CAPTCHA, submit bids, or cross a portal access boundary.
9. Run the full unit, lint, compilation, coverage, diff, and sensitive-content checks.
10. Commit and publish the feature branch, inspect the Diff in Codex Cloud, and create a draft PR targeting `master`.
11. Merge only after checks and review pass.
12. Confirm the evidence-derived behavior exists on `master`, then delete the processed local HAR. Keep the ignored intake directory.

## Goal

Validate every implemented connector family against live, anonymous browser evidence.

A reusable multi-tenant family requires two independent public-entity tenants. A jurisdiction-specific family receives one comprehensive validation because a second independent tenant does not exist. Two agencies within one statewide portal can improve field coverage, but they do not count as two platform tenants.

The repository currently contains 21 canonical connector families:

- 15 reusable or potentially reusable multi-tenant families
- 6 jurisdiction-specific families
- 36 ideal live validation captures: 30 multi-tenant captures plus 6 single-source captures
- Illinois BidBuy and Summit County Tyler Munis/VSS are already HAR-validated, leaving 34 ideal captures

A failed anonymous attempt is still valuable evidence when it conclusively records a login wall, registration boundary, CAPTCHA, HTTP failure, changed markup, or unavailable public surface. It does not count as a successful reusable-tenant validation.

## Definition of family-validated

A reusable family is family-validated only when:

- two independently operated tenants have reviewed captures;
- shared behavior and tenant-specific differences are identified;
- one configurable connector supports both without copied tenant-specific connector code;
- discovery, filtering, pagination, details, contacts, amendments, awards, and attachments are tested wherever exposed;
- public procurement data is retained with provenance;
- authentication, registration, CAPTCHA, payment, and document restrictions are explicit;
- minimal fixtures and evidence-backed connector changes are merged; and
- neither complete HAR data nor active session material is tracked.

A jurisdiction-specific family is validated after one comprehensive reviewed capture, implementation reconciliation, fixture coverage, and merge.

## Standard capture checklist

Remain anonymous. Do not log in, register, solve or bypass CAPTCHA, join a bidder list, acknowledge an addendum, submit a question, upload a response, or submit a bid.

Exercise every public read-only action the portal exposes:

- landing page and anonymous bid board;
- open, closed, awarded, cancelled, and amended searches;
- keyword, solicitation number, agency, status, type, commodity/category, and date filters;
- clearing/resetting filters;
- sorting and every available page-size control;
- multiple pagination transitions, including next, previous, and a numbered page;
- at least two solicitation details;
- buyer, contracting officer, agency, and public contact information;
- public vendor, apparent-awardee, tabulation, or bidder information when exposed;
- amendments, addenda, Q&A, conferences, results, and awards;
- attachment lists, document viewers, redirect handlers, and at least one lawful anonymous download;
- navigation back to results;
- any visible login, registration, payment, CAPTCHA, or restricted-document boundary.

Capture all browser traffic needed to reproduce those read-only contracts. Sanitize only after capture so useful evidence is not lost.

## Batch 1 — Current priority

### Tyler Munis/VSS

- [x] Summit County, Ohio — `https://summitcountyoh.munisselfservice.com/vss/`
- [x] City of Opelika, Alabama — `https://ss.opelika-al.gov/vss/`

Suggested filename:

`al-opelika-tyler-munis-vss-anonymous-public-sanitized.har`

### Periscope BuySpeed

- [x] Illinois BidBuy — `https://www.bidbuy.illinois.gov/bso/view/search/external/advancedSearchBid.xhtml`
- [x] Massachusetts COMMBUYS — `https://www.commbuys.com/bso/view/search/external/advancedSearchBid.xhtml`

Suggested filename:

`ma-commbuys-periscope-buyspeed-anonymous-public-sanitized.har`

### CGI Advantage VSS

- [ ] Michigan SIGMA — `https://sigma.michigan.gov/PRDVSS1X1/Advantage4/SolicitationSearch`
- [ ] Maine VSS — `https://mevss.hostams.com/PRDVSS1X1/AltSelfService/SolicitationSearch`

The 2026-08-13 attempts did not validate this family: Michigan returned HTTP 404, while Maine
produced HTTP 404/403 and failed requests. See `batch1_har_evidence_2026-08-13.md`.

Suggested filenames:

- `mi-sigma-cgi-advantage-vss-anonymous-public-sanitized.har`
- `me-vss-cgi-advantage-anonymous-public-sanitized.har`

These deliberately cover the `Advantage4` and `AltSelfService` variants.

### JAGGAER/SciQuest

- [x] Iowa IMPACS — `https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=DASIowa`
- [x] Utah U3P — `https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=StateOfUtah`

Suggested filenames:

- `ia-impacs-jaggaer-sciquest-anonymous-public-sanitized.har`
- `ut-u3p-jaggaer-sciquest-anonymous-public-sanitized.har`

### WebProcure/PROACTIS

- [ ] Connecticut CTsource — `https://webprocure.proactiscloud.com/wp-web-public/#/bidboard/search?customerid=51&oid=-1`
- [ ] Rhode Island Ocean State Procures — `https://webprocure.proactiscloud.com/wp-web-public/#/bidboard/search?customerid=46&oid=120002`

Suggested filenames:

- `ct-ctsource-webprocure-proactis-anonymous-public-sanitized.har`
- `ri-ocean-state-procures-webprocure-proactis-anonymous-public-sanitized.har`

Preserve 502/503 responses, redirects, login walls, registration requirements, and failed background calls as access-boundary evidence. Do not authenticate.

Both 2026-08-13 WebProcure captures encountered reCAPTCHA. They remain unchecked because
CAPTCHA-boundary evidence does not establish unattended anonymous family validation.

## Batch 2 — High-value county and municipal families

These families are likely to produce the greatest reuse during county, municipal, education, and authority expansion.

### OpenGov Procurement/ProcureNow

- [x] Ocean County, New Jersey — anonymous listing/detail/Q&A and metadata; login-gated downloads
- [x] Alameda County, California — same shared contract with independently configured tenant data

Evidence: [OpenGov two-tenant validation](opengov_two_tenants_2026-08-24.md).

### Euna Bonfire

- [ ] Fairfax County configured profile
- [ ] Second independently operated Bonfire tenant selected from authoritative agency evidence

### Euna IonWave

- [x] Plano ISD — anonymous live grid, details, mixed document access, and later human challenge
- [ ] Second active configured IonWave tenant with a different public-portal configuration

Prefer geographically distinct tenants and capture any differences in host routing, public details, Q&A, addenda, awards, and attachment gating.

### Euna OpenBids/DemandStar

- [x] Butler County, Kansas — authoritative agency-scoped tenant
- [x] City of Lynn Haven, Florida — independently operated agency-scoped tenant
- [x] Will County, Illinois — official legacy member link mapped to modern UUID tenant
- [x] Ramsey County, Minnesota — official legacy member link mapped to modern UUID tenant

Do not use paid DemandStar aggregation as the evidence source. Capture agency-scoped public surfaces and distinguish public metadata from registration- or payment-gated documents.

### PlanetBids

- [ ] First authoritative agency PlanetBids portal
- [ ] Second independently operated agency PlanetBids portal

Do not infer support from VendorLine or unrelated PlanetBids marketing pages. Both targets require authoritative agency linkage and observed public routes.

## Batch 3 — Networks and transportation portals

### BidNet Direct

- [x] Maricopa County Procurement Services — Arizona Purchasing Group member agency
- [x] City and County of Denver General Services Purchasing — Rocky Mountain E-Purchasing System member agency

Record whether metadata is anonymous, documents require registration, and an official agency-hosted public copy exists. Do not use paid geographic aggregation.

### Public Purchase

- [ ] First Public Purchase member agency
- [ ] Second independently operated member agency

Separate anonymous portal metadata, free registration, agency enrollment, document access, notification access, and bid-response functionality.

### Infotech Bid Express/BidX

- [ ] First authoritative participating transportation agency
- [ ] Second authoritative participating transportation agency

Validate the public agency directory, opportunity discovery, detail, plan/document access, amendments, apparent-bidder or bid-result data, and any account or subscription boundary.

## Batch 4 — Oracle enterprise families

### Oracle Fusion Procurement REST

- [ ] City of Detroit configured modern Fusion REST tenant
- [ ] Second modern Fusion REST tenant only after reproducible anonymous REST evidence is found

Do not treat legacy Oracle ADF workflows as Fusion REST evidence. Do not reuse Lucas County, Jacksonville, Virginia Beach, or DC Water unless a capture proves the same modern anonymous REST contract.

### Oracle PeopleSoft Sourcing

- [ ] California Cal eProcure
- [ ] Second independently operated PeopleSoft public-sourcing tenant selected from reproducible evidence

The second target must prove the same family through observed public search/detail behavior, not branding alone.

## Batch 5 — Jurisdiction-specific families

These receive one comprehensive capture each:

- [ ] Virginia eVA — `https://eva.virginia.gov/`
- [ ] Texas ESBD — `https://www.txsmartbuy.gov/esbd`
- [ ] Pennsylvania eMarketplace — `https://www.emarketplace.state.pa.us/`
- [ ] Maryland eMMA — `https://emma.maryland.gov/`
- [ ] Georgia Procurement Registry — `https://ssl.doas.state.ga.us/gpr/`
- [ ] Rhode Island RIVIP External Solicitations — `https://www.purchasing.ri.gov/RIVIP/ExternalBids.aspx`

Where practical, exercise opportunities from at least two issuing agencies to improve schema coverage. Record this as intra-portal coverage, not independent-tenant validation.

## Per-capture processing workflow

1. Create a feature branch from current `origin/master`.
2. Place the capture in `sled-har-evidence/`.
3. Compute and record SHA-256.
4. Import it into the ignored `.sled-validation/` workspace.
5. Run scanning, contract analysis, evidence reporting, and dry-run ingestion.
6. Review public procurement data separately from authentication/session secrets.
7. Approve evidence only after manual review.
8. Derive small fictional fixtures covering observed request and response variants.
9. Correct or extend the connector without broadening access beyond the evidence.
10. Add tests for every claimed capability and access boundary.
11. Update coverage data and family documentation without claiming continuous availability.
12. Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall src tests
ruff check .
python -m sled_aggregator.coverage validate
python -m sled_aggregator.coverage recommend
git diff --check
```

13. Confirm no HAR, HAR archive, downloaded binary, cookie, token, session ID, CSRF/XSRF value, ViewState, authorization credential, or real sensitive fixture data is staged.
14. Commit, publish, review the Codex Diff, and open a draft PR.
15. Merge after review and passing checks.
16. Verify the functionality and evidence record on `master`.
17. Delete only the processed local HAR.

## Final audit

After all batches, generate a family-by-family report using explicit statuses:

- `live_har_validated`
- `single_source_validated`
- `fixture_only`
- `configured_unverified`
- `registration_required`
- `login_required`
- `captcha_required`
- `blocked`
- `changed_markup`
- `unavailable`
- `unsupported`

The state-and-territory connector layer is evidence-validated only to its documented public-access boundaries. It is not a claim of perfect statewide completeness or permanent portal availability.

After the validation audit, proceed to scheduled ingestion, health monitoring, markup-drift detection, retry/dead-letter operations, and then county expansion using the validated family profiles.
