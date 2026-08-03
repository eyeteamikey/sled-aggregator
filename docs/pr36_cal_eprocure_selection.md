# PR #36 selection: Cal eProcure public-contract evidence

## Mandatory selection gate

The authoritative PR #35 queue ranked **California / `ca-cal-eprocure` first**, with
score **50** (P1), for the `live_validation` task type. It is the primary statewide
source for California and uses the existing `oracle/peoplesoft-sourcing` connector
and `ca-cal-eprocure` portal profile. The official California Department of General
Services Cal eProcure page and the configured public bid board establish the source
identity and platform context; sanitized search, detail, partial-response, and access
fixtures exercise anonymous behavior without credentials.

The recommendation affects CA and source `ca-cal-eprocure`, has statewide scope, and
requires no login, registration, bid submission, state-changing request, CAPTCHA
bypass, or vendor impersonation. Fixture-observed authentication is `none` and CAPTCHA
is `none_observed_in_fixture`. Public documents are classified rather than downloaded
during discovery, and mixed-access attachments fail closed.

A bounded live check was attempted on 2026-08-03 with GET/HEAD requests, a 10-second
connect timeout, 30-second total timeout, three-redirect cap, and 200 KB response cap.
The Codex Cloud outbound CONNECT proxy returned its own HTTP 403 before either
`caleprocure.ca.gov` or `www.dgs.ca.gov` was reached. That result is an environment
limitation—not evidence of portal authentication, CAPTCHA, or blocking—so this PR does
not misclassify it as source behavior and does not claim live validation.

## Selection report

| Field | Result |
|---|---|
| Recommendation rank / score | 1 / 50 (P1) |
| Recommended task type | Source-specific live-validation evidence |
| Jurisdiction | California (`CA`) |
| Source | `ca-cal-eprocure`, primary statewide |
| Platform family | `oracle/peoplesoft-sourcing` (Oracle PeopleSoft / FI$Cal profile) |
| Existing connector / profile | `oracle/peoplesoft-sourcing` / `ca-cal-eprocure` |
| Evidence already available | Official DGS landing page; public portal URLs; sanitized search/detail/access fixtures; connector tests |
| Evidence added | Explicit official DGS source-identity evidence and bounded-check limitations |
| Evidence still missing | A dated successful bounded anonymous production search/detail result from a network that reaches California hosts |
| Expected baseline increase | 0 (already fixture-operational) |
| Expected discovery/detail/attachment/pipeline increase | 0 / 0 / 0 / 0 |
| Authentication / CAPTCHA | None observed in fixtures; live result remains unknown because the source was not reached |
| Known limitations | No live claim; mixed document access; incomplete award, education, local, and transportation coverage |

This is the correct PR #36 target because it is the highest-ranked current queue item,
has explicit statewide identity and an implemented reusable connector, and permits
honest evidence progress without speculative code. Lower-ranked GA, MD, PA, TX, and VA
live-validation items were not selected because rank 1 qualifies; the shell limitation
does not justify combining unrelated families.

## Coverage impact and next work

Capability counts remain deliberately unchanged: baseline 6, discovery 6, detail 6,
attachments 6, document pipeline 6, live validated 0, tier 0 50, blocked 0, and lacking
an identified primary statewide source 50. The added official evidence strengthens
California source provenance but is not promoted to operational proof.

After this PR, the queue correctly keeps California first until a permitted environment
can perform the dated anonymous check. Once that evidence is captured, Georgia
Procurement Registry (`ga-gpr`, rank 2 in the pre-PR queue) is the next distinct source.
CI remains wholly fixture-driven and never contacts a procurement portal.
