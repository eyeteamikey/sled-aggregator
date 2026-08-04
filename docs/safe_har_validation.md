# Safe HAR validation toolkit

This toolkit extends the bounded validation harness introduced in PRs #48–#50. It turns an
anonymous browser observation into reviewable capability evidence; it is not a crawler, login
assistant, CAPTCHA solver, bid-submission tool, or proof that every connector capability works.
Fixture evidence remains distinct from dated live verification.

## Storage and security boundary

Use `.sled-validation/{raw,sanitized,evidence,fixtures,reports}` for local work. The entire
workspace is ignored by Git. Raw HARs, cookies, production document bodies, browser binaries,
`node_modules`, executables, external `.git` history, and unsanitized responses must never be
committed. The CLI rejects repository roots and tracked fixture, coverage, documentation, and
report paths as raw workspaces. It accepts only registered source hosts, public HTTP(S), fresh
anonymous contexts, safe resource methods, and narrowly registered read-only POST contracts.
Public read-only is not synonymous with GET-only: source-specific, host- and path-bound rules may
permit anonymous search/detail POSTs after checking content type, field names, body size, and
prohibited actions. Capture permission is not connector replay approval. Private, local,
credential-bearing, special-purpose, and unregistered redirect URLs are rejected.

The sanitizer removes cookie collections and sensitive request/response headers, redacts query
and form secrets (including Oracle `_afrLoop` and `_adf.ctrl-state`), removes authentication,
oversize, binary, and production-document bodies, and creates a fingerprint-only audit trail.
The post-sanitization scanner finds authentication material, JWTs, email/phone data, private IPs,
and high-entropy strings without printing their values. Unresolved high-severity findings fail
approval closed. Sanitization never overwrites the raw capture.

JSF/PrimeFaces ViewState and session fields may pass only within a registered live browser rule;
their values are ephemeral secrets, are never logged or replayed, and are redacted in evidence.
Analytics, tag managers, Hotjar, fonts, and marketing/session-replay traffic remain nonessential
third-party traffic and are blocked rather than added to a source allowlist.

## Installation (Windows PowerShell)

The sanitizer, scanner, analyzer, reporter, fixture extractor, approval gate, and ingestion gate
need only the normal project installation. Playwright is optional and isolated:

```powershell
py -m pip install -e ".[validation]"
py -m playwright install chromium
New-Item -ItemType Directory -Force .sled-validation\raw
```

Do not install or launch Playwright in CI. Browser capture is deliberately visible, uses a new
context without a personal profile, cookie import, or stored login state, and flushes the HAR when
the context closes.

## Repeatable portal workflow

1. Preview the registered source and allowlist without network access:

   ```powershell
   py -m sled_aggregator.validation capture --source al-alabamabuys --label al-20260803 --dry-run
   ```

2. Start a manual capture (omit `--dry-run`). In the visible browser, remain anonymous and perform
   only: landing visit, keyword and empty/wildcard searches, one filter change, page two/infinite
   scroll, one detail, attachment list, at most one small public document request, amendment view,
   and return to results. Never log in, register, solve CAPTCHA, submit, or take vendor actions.
   Press Enter in the terminal to close the fresh context and reliably flush the HAR. A browser or
   terminal interruption can leave an incomplete raw file; preserve it, start a new label, and do
   not overwrite or destructively clean either capture.

3. Import an existing browser HAR directly. The command copies rather than moves or overwrites the
   original, emits a category/count-only raw risk inventory, creates a manual-browser manifest,
   sanitizes separately, and scans immediately:

   ```powershell
   py -m sled_aggregator.validation import-har --source il-bidbuy --input C:\captures\bidbuy.har --workspace .\.sled-validation
   ```

   Continue the review workflow with the exact commands printed by import:

   ```powershell
   py -m sled_aggregator.validation sanitize .sled-validation\raw\al.har .sled-validation\sanitized\al.har --source al-alabamabuys
   py -m sled_aggregator.validation scan .sled-validation\sanitized\al.har --output .sled-validation\reports\al-findings.json
   py -m sled_aggregator.validation analyze .sled-validation\sanitized\al.har --output .sled-validation\reports\al-contract.json
   py -m sled_aggregator.validation report .sled-validation\sanitized\al.har --analysis .sled-validation\reports\al-contract.json --source al-alabamabuys --capture-id al-20260803 --output .sled-validation\evidence\al.json
   ```

4. Compare the guided checklist with observed entries. A checked action is not network evidence.
   Review every finding and the sanitizer audit. Proxy-produced 403s are `proxy_blocked`, transport
   failures are `network_blocked`, target login walls are `authentication_required`, and CAPTCHA
   pages are `captcha_present`; none are silently converted into a target 403 or live success.

5. Record approval for only proven capabilities, then extract a small candidate fixture or propose
   registry evidence:

   ```powershell
   py -m sled_aggregator.validation approve .sled-validation\evidence\al.json .sled-validation\reports\al-findings.json --reviewer "Reviewer Name" --capability discovery --output .sled-validation\evidence\al-approved.json
   py -m sled_aggregator.validation extract-fixture .sled-validation\sanitized\al.har .sled-validation\fixtures\al.json --approved
   py -m sled_aggregator.validation ingest .sled-validation\evidence\al-approved.json --dry-run --confirm
   ```

   Inspect the dry-run diff before running ingestion without `--dry-run`. Ingestion requires both
   explicit approval and `--confirm`; it adds capability-scoped evidence and never promotes a
   source to `live_verified`. Fixture candidates contain only a few non-static structural entries,
   preserve pagination/relationship shapes where observed, record transformations, and exclude
   removed document bodies. Review again before deliberately copying a compact fixture or report
   into a tracked location.

## Limits

Manual capture requires a local terminal because completion uses Enter. Runtime termination is a
human-visible bound; request and host enforcement are automatic. Select `--browser chromium`,
`--browser msedge`, or `--browser chrome`; the manifest reports the choice without stealth or
automation evasion. The standard-library sanitizer uses bounded body policies, hashes omitted
content, and canonical output, but currently parses the HAR JSON document as a whole; for
exceptionally large captures, configure Playwright to omit bodies and split capture
sessions by checklist phase before sanitizing. Batch capture is intentionally not exposed: broad
crawling is outside the product boundary. Evidence reports infer endpoints from conservative URL
patterns and require human review, especially for opaque RPC routes.

## Illinois BidBuy local acceptance

Run the dry-run first, then repeat without `--dry-run` (PowerShell line continuations shown):

```powershell
python -m sled_aggregator.validation capture `
  --source il-bidbuy --label anonymous-public-validation `
  --workspace .\.sled-validation --browser msedge --dry-run
python -m sled_aggregator.validation capture `
  --source il-bidbuy --label anonymous-public-validation `
  --workspace .\.sled-validation --browser msedge
```

Search for `software`, page once, open two public opportunities, inspect public documents, and
attempt at most one anonymous download. Stop at login, registration, CAPTCHA, terms acceptance,
or response functionality. The registered JSF search and detail POSTs may proceed; all arbitrary
POSTs and mutations remain denied. Telemetry is nonessential and must not prevent manual finish.
The Illinois spinner cause is inferred from operator HAR evidence: the original GET-only router
aborted essential same-origin JSF/Ajax POSTs, leaving the client waiting for their responses.
