# PR #48 selection: bounded Periscope validation harness

## Phase determination

PR #47 is present as merge commit `7fb9b8a` and substantive commit `bce5371`. Its registry,
fixtures, breadth-closeout manifest, live-validation tasks, and generated recommendation queue are
present. The closeout formally ends fixture-backed breadth work: all 18 platform-identified primary
sources have profiles, while Alabama and Ohio need contract evidence and 36 Tier 0 jurisdictions
lack authoritative primary-source evidence.

Path B therefore begins the live-validation campaign. The first coherent same-family batch is the
Periscope/BuySpeed sources for Illinois (`il-bidbuy`), Massachusetts (`ma-commbuys`), and New Jersey
(`nj-njstart`). These are fixture verified, discovery/detail/attachment capable, and queued for
bounded anonymous validation. This PR supplies the reusable harness and records one bounded request per source without claiming that any
portal was promoted to `live_verified`.

## Harness and evidence policy

The harness accepts only explicit registered source IDs and performs bounded, anonymous, read-only
GET requests. Operators control request budgets, timeouts, page/result ceilings, rate delay, retry
limits, and user-agent identification. Dry runs perform no requests. Evidence contains redacted
URLs, status and content type, redirect URLs, response-shape hashes, classifications, timestamps,
and limitations; response bodies, cookies, credentials, and private headers are never emitted.

Authentication pages, CAPTCHA, rate limits, and network/proxy failures remain distinct. A source is
promotion eligible only when the authoritative request returns a successful public response with a
shape fingerprint; unobserved detail, attachment, addenda, document, normalization, and idempotency
capabilities remain explicitly `not_observed`. Normal CI performs simulated and dry-run validation
only, never live portal requests.

## Coverage impact and limitations

The authoritative before and after counts remain: 56 targets, 20 identified primaries, 18 platform
families, 18 registered profiles, 18 fixture-verified/discovery-capable jurisdictions, 16 detail and
attachment capable, 6 document-pipeline compatible, 0 live verified, 0 production monitored, 36
Tier 0, and 2 evidence blocked. No registry evidence fields are changed. On 2026-08-03, one request reached each registered
portal search URL and returned HTTP 200 HTML containing CAPTCHA indicators. The selected capabilities
are therefore `captcha_blocked`; detail, attachments, documents, addenda, normalization, handoff, and
idempotency remain `not_observed`. There was no proxy/network, authentication, or rate-limit finding.
A permitted operator must review access conditions before any future promotion. Subsequent coherent batches should follow the generated live-validation queue.
