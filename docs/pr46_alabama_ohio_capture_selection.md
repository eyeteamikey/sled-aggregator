# PR #46 selection: AlabamaBuys and OhioBuys public-contract capture

## Merge gate and selection

PR #45 is present as merge commit `890c09d` and substantive commit `8ae815d`. Its remaining-jurisdiction audit, Alabama/Ohio local-evidence correction, capture checklist, generated-report review, and updated recommendation queue are present. Its work no longer appears incomplete and is not recreated here.

After excluding 18 live-validation-only items, the authoritative queue ranked Alabama 19 and Ohio 20, score 20 each. PR #45 selected them as evidence-capture rank 1. This PR completes the first safe part of that capture: it registers the official statewide source identities while declining to invent a platform, tenant, endpoint, parameter, response field, or access behavior.

## Selection report

| Field | Result |
|---|---|
| Recommendation rank / score | Generated ranks 19 and 20, score 20; breadth evidence rank 1 |
| Platform family | Unknown; any JAGGAER or other platform hypothesis remains unverified |
| Jurisdictions | Alabama (`AL`), Ohio (`OH`) |
| Source IDs / role | `al-alabamabuys`, `oh-ohiobuys`; authoritative primary statewide sources |
| Existing connector/profile | No evidenced tenant profile; no connector selected |
| Identity evidence | Official state-controlled AlabamaBuys and OhioBuys landing pages |
| Public-contract evidence | Not captured; outbound CONNECT returned 403 before either official host |
| Expected identified / platform increase | +2 / +0 jurisdictions |
| Expected baseline / discovery / detail | +0 / +0 / +0 |
| Expected attachment / document pipeline | +0 / +0 |
| Fixture target | None until tenant-specific routes and response contract are captured |
| Live status | Not validated; 0 live and 0 production-monitored jurisdictions |
| Authentication / CAPTCHA | Unknown; neither host was reached |
| Remaining uncertainty | Platform, tenant, public bid board, routes, parameters, fields, pagination, redirects, access, CAPTCHA, detail, attachments, amendments, and automation policy |

Fixture verification is **not** live verification. These records remain source-identified only (`verification_status: unknown`), with unknown discovery, detail, attachment, authentication, and CAPTCHA behavior.

## Capture contract and security boundary

A follow-up capture must record an official bid-board link and platform/tenant identity; bounded anonymous GET routes and parameters; pagination and stable identifiers; sanitized result, empty, detail, attachment, amendment, duplicate, missing-field, malformed, access-wall, and transient-error responses; redirect hosts; and access-policy observations. It must not log in, register, submit, retain cookies or credentials, solve CAPTCHA, cross access controls, download documents during discovery, or infer a contract from a different tenant.

## Coverage impact

Primary statewide sources identified increase from 18 to 20; missing-primary and Tier 0 jurisdictions fall from 38 to 36; Tier 1 increases from 0 to 2. Platform families remain 10. Fixture-verified, baseline-operational, and discovery-capable remain 18; detail and attachment remain 16; document-pipeline compatible remains 6; live-verified and production-monitored remain 0.

The queue now correctly schedules unverified identified sources for `public_contract_capture`, rather than prematurely scheduling live validation. Alabama and Ohio remain ranks 19 and 20 with score 20. The next breadth-first work is bounded contract capture for AlabamaBuys, then OhioBuys; split later implementation if evidence shows different platform families. The other 36 Tier 0 jurisdictions still require official statewide identity evidence.
