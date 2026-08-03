# PR #38 selection: eMaryland Marketplace Advantage public-contract evidence

## Mandatory selection gate

PR #37 is present on the selected base as merge commit `f5252b4` and substantive
commit `fad0bed`. Its Georgia GPR official-source evidence, selection report,
registry regression test, and regenerated summary are present. Georgia remains in
the queue only because the bounded check could not reach its host; repeating PR #37
is excluded, as is PR #36's equivalent California evidence work.

After those exclusions, **Maryland / `md-emma`** is the highest-ranked distinct queue
item: rank **3**, score **50** (P1), task type `live_validation`. eMMA is Maryland's
primary statewide source and uses the existing `maryland/emma` connector and
`md-emma` profile. The official Maryland Office of State Procurement page and public
portal establish source identity and statewide context. Sanitized discovery, detail,
empty, notice, access-boundary, and changed-markup fixtures exercise the request
contract without credentials.

A bounded live check was attempted on 2026-08-03 using an anonymous GET, a 10-second
connect timeout, 30-second total timeout, three-redirect cap, and 200 KB response cap.
The Codex Cloud outbound CONNECT proxy returned HTTP 403 before either Maryland host
was reached. This is an environment limitation, not portal evidence. The registry
therefore retains fixture verification and makes no new authentication, CAPTCHA,
blocking, or live-validation claim.

## Selection report

| Field | Result |
|---|---|
| PR #37 confirmed | Merge `f5252b4`; Georgia evidence commit `fad0bed`; registry, report, test, and selection-document changes present |
| Recommendation rank / score | 3 overall; highest distinct work after excluding PRs #36 and #37 / 50 (P1) |
| Task type | Source-specific live-validation evidence |
| Jurisdiction | Maryland (`MD`) |
| Source ID / scope | `md-emma` / primary statewide procurement source |
| Platform family | `maryland/emma` |
| Existing connector / profile | `maryland/emma` / `md-emma` |
| Evidence available | Official Office of State Procurement eMMA page; configured public portal; sanitized discovery/detail/access fixtures; connector tests |
| Evidence added | Explicit official state source-identity evidence and bounded-check result |
| Evidence missing | Dated successful bounded anonymous production search/detail result from a network that reaches Maryland hosts |
| Authentication / CAPTCHA | None observed in fixtures; live result unknown because the portal was not reached |
| Expected baseline change | 0 (already fixture-operational) |
| Expected discovery change | 0 |
| Expected detail change | 0 |
| Expected attachment change | 0 |
| Expected document-pipeline change | 0 |
| Known limitations | No live claim; mixed document access; metadata-only awards; incomplete award, education, local, and transportation coverage |

Maryland is selected because it is the highest-ranked qualifying coherent tranche not
already addressed by PR #36 or PR #37. Its explicit jurisdiction and source IDs,
official URLs, existing tested platform contract, and primary statewide scope permit
evidence progress without inventing endpoints. Collection remains public, read-only,
GET-only, bounded, and anonymous; it requires no login, registration, credentials,
CAPTCHA bypass, vendor impersonation, bid submission, or state-changing request.
Lower-ranked Pennsylvania, Texas, Virginia, and local-only correction tasks are not
combined with this portal family.

## Coverage impact and next work

Before and after counts are unchanged: baseline operational 6, discovery 6, detail 6,
attachments 6, document pipeline 6, live validated 0, tier 0 50, blocked 0, and lacking
an identified primary statewide source 50. Official provenance improves, but fixture
evidence and a proxy denial do not promote operational capability.

A permitted environment should repeat the bounded Maryland check. Excluding the
California, Georgia, and Maryland evidence tasks addressed by PRs #36–#38,
Pennsylvania eMarketplace (`pa-emarketplace`, queue rank 4, score 50) is the next
distinct recommendation. CI remains entirely fixture-driven and never contacts a live
procurement portal.
