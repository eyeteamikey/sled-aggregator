## Motivation

Execute PR #45's highest-value evidence-capture tranche without speculative connector code by registering AlabamaBuys and OhioBuys as the authoritative statewide source identities and explicitly recording the contract evidence still required.

## PR #45 merge verification

PR #45 is present as merge `890c09d` and substantive commit `8ae815d`. Its audit, capture checklist, reports, and queue are present; this PR does not recreate them.

## Selection rationale and evidence

After 18 fixture-operational live-validation tasks are excluded, Alabama and Ohio are generated ranks 19 and 20 (score 20) and breadth evidence rank 1. Source IDs are `al-alabamabuys` and `oh-ohiobuys`; both are primary statewide sources. Official state-controlled landing pages establish identity and scope. Platform family, tenant, and public request contract remain unknown: Codex Cloud's outbound CONNECT proxy returned 403 before reaching either host. No JAGGAER or other profile is inferred.

## Implementation and behavior

- Adds source-identified statewide registry records and official identity evidence.
- Keeps discovery, detail, attachments, amendments, document retrieval, authentication, and CAPTCHA `unknown`; document compatibility is not claimed.
- Changes queue generation so only fixture/live-verified sources receive live-validation tasks; identified-but-unverified sources receive deterministic `public_contract_capture` tasks.
- Adds regression coverage and regenerates the complete report set.

No fixture or production validation occurred. **Fixture verification is not live verification.** Live-verified and production-monitored counts remain zero.

## Security boundaries

No login, vendor registration, bid submission, credential/cookie handling, CAPTCHA circumvention, access-control bypass, unvalidated redirect, arbitrary host, unbounded collection, or discovery-time document download is introduced. Unknown contracts fail closed.

## Coverage before / after

| Metric | Before | After |
|---|---:|---:|
| Primary statewide sources identified | 18 | 20 |
| Platform families identified | 10 | 10 |
| Fixture-verified / baseline / discovery | 18 | 18 |
| Detail / attachment | 16 | 16 |
| Document-pipeline compatible | 6 | 6 |
| Live-verified / production-monitored | 0 | 0 |
| Tier 0 | 38 | 36 |
| Tier 1 | 0 | 2 |
| Missing primary statewide source | 38 | 36 |

## Reports and files

Regenerated status, missing sources, capability matrix, connector reuse, blocked sources, document readiness, next-PR queue, and consistency outputs. Changed the two coverage registries, queue generator, audit tests, generated reports, this PR body, and `docs/pr46_alabama_ohio_capture_selection.md`.

## Validation

Exact final results are recorded after the focused commit. Commit: `COMMIT_HASH`.

## Limitations and next work

No public bid-board URL, platform, tenant, route, parameter, response schema, anonymous access behavior, attachment contract, authentication, or CAPTCHA behavior has been established. Next perform bounded sanitized AlabamaBuys contract capture, then OhioBuys; split implementation by platform family if evidence differs. The remaining 36 Tier 0 jurisdictions require official statewide source identity evidence. Live validation remains deferred.
