# PR #37 selection: Georgia Procurement Registry public-contract evidence

## Mandatory selection gate

PR #36 is present on the base as merge commit `230b44e` and substantive commit
`9c03eff`. It added the Cal eProcure official-source evidence, selection report,
registry regression test, and regenerated summary. California remains queue rank 1
only because the bounded check could not reach the California hosts; repeating that
same evidence capture is excluded as PR #36 work.

The next distinct authoritative queue item is **Georgia / `ga-gpr`**, originally rank
**2**, with score **50** (P1), for the `live_validation` task type. It is the primary
statewide source for Georgia and uses the existing `georgia/gpr` connector and
`ga-gpr` profile. The official Georgia Department of Administrative Services source
page and configured public registry establish source identity and statewide context;
sanitized listing, detail, attachment, amendment, and access fixtures exercise the
anonymous contract without credentials.

The recommendation affects GA and source `ga-gpr`, has statewide scope, and requires
no login, registration, bid submission, state-changing request, CAPTCHA bypass, or
vendor impersonation. Fixture-observed authentication is `none` and CAPTCHA is
`none_observed_in_fixture`. Public documents are classified rather than downloaded
during discovery, and mixed-access attachments fail closed.

A bounded live check was attempted on 2026-08-03 with an anonymous GET, a 10-second
connect timeout, 30-second total timeout, three-redirect cap, and 200 KB response cap.
The Codex Cloud outbound CONNECT proxy returned its own HTTP 403 before
`ssl.doas.state.ga.us` was reached. The same environment restriction affected all six
P1 live-validation hosts. This is not portal evidence, so the registry retains fixture
verification and does not claim authentication, CAPTCHA, blocking, or live validation.

## Selection report

| Field | Result |
|---|---|
| PR #36 confirmed | Merge `230b44e`; Cal eProcure evidence commit `9c03eff` |
| Current recommendation rank / score | 2 overall; next distinct work after PR #36 / 50 (P1) |
| Task type | Source-specific live-validation evidence |
| Jurisdiction | Georgia (`GA`) |
| Source | `ga-gpr`, primary statewide |
| Source scope | Primary statewide procurement notices |
| Platform family | `georgia/gpr` |
| Existing connector / profile | `georgia/gpr` / `ga-gpr` |
| Evidence available | Official DOAS source page; public registry URL; sanitized discovery/detail/document/access fixtures; connector tests |
| Evidence added | Explicit official DOAS source-identity evidence and bounded-check result |
| Evidence missing | Dated successful bounded anonymous production search/detail result from a network that reaches Georgia hosts |
| Authentication / CAPTCHA | None observed in fixtures; live result unknown because the source was not reached |
| Expected baseline change | 0 (already fixture-operational) |
| Expected discovery/detail/attachment/pipeline change | 0 / 0 / 0 / 0 |
| Known limitations | No live claim; mixed document access; incomplete education, local, and transportation coverage |

Georgia belongs in PR #37 because it is the highest-ranked distinct qualifying source
after excluding PR #36's California evidence work. The official page gives a precise,
authoritative source identity without speculative connector changes. Lower-ranked
Maryland, Pennsylvania, Texas, Virginia, and local-only correction tasks are not
combined with this connector family.

## Coverage impact and next work

Counts remain: baseline 6, discovery 6, detail 6, attachments 6, document pipeline 6,
live validated 0, tier 0 50, blocked 0, and lacking an identified primary statewide
source 50. Official provenance improves, but fixture evidence and a proxy denial do
not promote operational capability.

A permitted environment should next repeat the bounded Georgia check. Excluding the
California and Georgia evidence tasks already addressed by PRs #36 and #37, Maryland
EMMA (`md-emma`, queue rank 3) is the next distinct recommendation. CI remains entirely
fixture-driven and never contacts a procurement portal.
