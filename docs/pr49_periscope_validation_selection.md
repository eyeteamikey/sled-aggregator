# PR #49 selection: remaining Periscope validation batch

## Merge gate and inherited phase

PR #48 is present as merge commit `f0cb17e` and substantive commit `013046e`. Its bounded
validation harness, tests, selection record, and sanitized Illinois (`il-bidbuy`), Massachusetts
(`ma-commbuys`), and New Jersey (`nj-njstart`) validation reports are present. PR #48 inherited the
breadth closeout from PR #47 and selected Path B, so this PR continues the live-validation campaign
rather than reopening fixture-backed breadth implementation.

The regenerated recommendation and live-validation queues still identify fixture-verified primary
statewide sources for bounded validation. After excluding the three Periscope sources completed by
PR #48, the next coherent same-family batch is the remaining Periscope/BuySpeed profiles: Nevada
(`nv-nevadaepro`), Oregon (`or-oregonbuys`), and the U.S. Virgin Islands (`vi-gvibuy`). All three
share the same connector, request contract, sanitized fixtures, and discovery, detail, and attachment
claims that require current production confirmation.

## Bounded validation and evidence

On 2026-08-03, the PR #48 harness issued exactly one anonymous, read-only GET request to each
registered public search URL, with a ten-second timeout and no retries. The committed evidence keeps
only redacted request URLs, timestamps, status and content type, response-shape hashes, error types,
capability classifications, and limitations. It contains no response bodies, credentials, cookies,
authorization headers, session data, personal information, or downloaded solicitation documents.

Nevada and Oregon each returned HTTP 200 HTML containing CAPTCHA indicators and are classified
`captcha_blocked`. The GVIBUY request failed with a `ProxyError` and is classified
`network_blocked`, not as a portal failure. No source showed an authentication or rate-limit trigger.
Because discovery was not verified beyond either barrier, search contracts, pagination, empty
results, details, attachments, addenda, public documents, normalization, document handoff, and
repeated-run idempotency remain `not_observed`. No source is promoted to `live_verified`.

## Coverage impact and next batch

The authoritative before and after counts remain unchanged: 20 primary sources identified, 18
registered statewide profiles, 18 fixture-verified and discovery-capable jurisdictions, 16 detail-
and attachment-capable jurisdictions, 6 document-pipeline-compatible jurisdictions, 0 live-verified
jurisdictions, 0 production-monitored jurisdictions, 36 Tier 0 jurisdictions, and 36 jurisdictions
lacking a primary statewide source. Registry blocker counts also remain 0 network-blocked, 0
authentication-required, and 0 CAPTCHA-blocked because a bounded point-in-time validation report
does not rewrite fixture-supported registry claims or establish a durable portal status.

The next validation work should return to the generated queue and select a coherent same-family
batch not completed by PR #48 or this PR. The WebProcure/Proactis pair for Connecticut
(`ct-ctsource`) and Rhode Island (`ri-ocean-state-procures`) or the JAGGAER/SciQuest pair for Iowa
(`ia-impacs`) and Utah (`ut-u3p`) are the remaining multi-jurisdiction families; each needs bounded
current validation from a permitted network before any promotion.
