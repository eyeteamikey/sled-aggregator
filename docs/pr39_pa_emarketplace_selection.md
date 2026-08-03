# PR #39 selection: Pennsylvania eMarketplace public-contract evidence

## Mandatory selection gate

PR #38 is present on the selected base as merge commit `4033425` and substantive
commit `fdf5a64`. Its Maryland eMMA official-source evidence, selection report,
registry regression test, and regenerated summary are present. Maryland remains in
the queue only because the bounded check could not reach its host; repeating PR #38
is excluded, as are the equivalent California and Georgia tasks completed by PRs #36
and #37.

After those exclusions, **Pennsylvania / `pa-emarketplace`** is the highest-ranked
distinct queue item: rank **4**, score **50** (P1), task type `live_validation`.
Pennsylvania eMarketplace is the primary statewide source and uses the existing
`pennsylvania/emarketplace` connector and `pa-emarketplace` profile. The official
`state.pa.us` portal establishes source identity and statewide context. Sanitized
discovery, detail, upcoming-solicitation, and access-boundary fixtures exercise the
public request contract without credentials.

A bounded live check was attempted on 2026-08-03 using an anonymous GET, a 10-second
connect timeout, 30-second total timeout, three-redirect cap, and 200 KB response cap.
The Codex Cloud outbound CONNECT proxy returned HTTP 403 before the Pennsylvania host
was reached. This is an environment limitation, not portal evidence. The registry
therefore retains fixture verification and makes no new authentication, CAPTCHA,
blocking, or live-validation claim.

## Selection report

| Field | Result |
|---|---|
| PR #38 confirmed | Merge `4033425`; Maryland evidence commit `fdf5a64`; registry, report, test, and selection-document changes present |
| Recommendation rank / score | 4 overall; highest distinct work after excluding PRs #36–#38 / 50 (P1) |
| Task type | Source-specific live-validation evidence |
| Jurisdiction | Pennsylvania (`PA`) |
| Source ID / scope | `pa-emarketplace` / primary statewide procurement source |
| Platform family | `pennsylvania/emarketplace` |
| Existing connector / profile | `pennsylvania/emarketplace` / `pa-emarketplace` |
| Evidence available | Official `state.pa.us` portal; sanitized discovery/detail/upcoming/access fixtures; connector tests |
| Evidence added | Explicit official state portal source-identity evidence and bounded-check result |
| Evidence missing | Dated successful bounded anonymous production search/detail result from a network that reaches the Pennsylvania host |
| Authentication / CAPTCHA | None observed in fixtures; live result unknown because the portal was not reached |
| Expected baseline change | 0 (already fixture-operational) |
| Expected discovery change | 0 |
| Expected detail change | 0 |
| Expected attachment change | 0 |
| Expected document-pipeline change | 0 |
| Known limitations | No live claim; metadata-only awards; incomplete award, education, local, and transportation coverage |

Pennsylvania is selected because it is the highest-ranked qualifying coherent tranche
not already addressed by PRs #36–#38. Its explicit jurisdiction and source IDs,
official URL, existing tested platform contract, and primary statewide scope permit
evidence progress without inventing endpoints. Collection remains public, read-only,
GET-only, bounded, and anonymous; it requires no login, registration, credentials,
CAPTCHA bypass, vendor impersonation, bid submission, or state-changing request.
Lower-ranked Texas, Virginia, and local-only correction tasks are not combined with
this portal family.

## Coverage impact and next work

Before and after counts are unchanged: baseline operational 6, discovery 6, detail 6,
attachments 6, document pipeline 6, live validated 0, tier 0 50, blocked 0, and lacking
an identified primary statewide source 50. Official provenance improves, but fixture
evidence and a proxy denial do not promote operational capability.

A permitted environment should repeat the bounded Pennsylvania check. Excluding the
California, Georgia, Maryland, and Pennsylvania evidence tasks addressed by PRs
#36–#39, Texas ESBD (`tx-esbd`, queue rank 5, score 50) is the next distinct
recommendation. CI remains entirely fixture-driven and never contacts a live
procurement portal.
