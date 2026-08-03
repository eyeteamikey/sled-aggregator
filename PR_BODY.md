## Motivation

Continue the breadth-first 56-jurisdiction baseline without inventing a connector after the fixture-verifiable implementation queue is exhausted. This PR records the exact evidence prerequisites for every remaining Tier 0 jurisdiction and selects the highest-ranked coherent correction tranche: Alabama and Ohio, whose existing Tyler Munis VSS evidence is local-only.

## PR #44 merge verification

PR #44 is present as merge commit `afc2852` and substantive commit `9e08e47`. Its Michigan SIGMA VSS profile, Advantage4 fixture routing, tests, registry changes, generated reports, selection report, and revised queue are present. Michigan is baseline-operational and absent from the missing-primary-source report; this PR does not recreate that work.

## Selection rationale

- Generated recommendation ranks/scores: Alabama rank 19, score 20; Ohio rank 20, score 20.
- Evidence-capture rank: 1 after excluding 18 live-validation-only recommendations.
- Platform family: unknown for either statewide source. `tyler/munis-vss` applies only to the existing local profiles.
- Jurisdictions/source IDs: Alabama (`al-opelika-tyler-munis-vss`) and Ohio (`oh-summit-county-tyler-munis-vss`). These IDs are authoritative local evidence anchors, not statewide source IDs.
- Statewide role: not yet established. Official statewide source identity and scope are the first required capture.

No remaining statewide connector/profile candidate has enough committed evidence for deterministic fixture-backed implementation. Promoting either local profile would incorrectly count municipal or county procurement as statewide coverage.

## Evidence and implementation summary

The new PR #45 selection report:

- records source-identity and request-contract evidence currently available for the local profiles;
- enumerates the exact identity, platform, tenant, request, response, access, and fixture evidence required before statewide implementation;
- audits all 38 remaining Tier 0 jurisdictions;
- groups them into local-evidence correction, state/district identity, and territory-authority capture tranches; and
- preserves every affected source below statewide `fixture_verified` status.

Discovery, detail, attachment, and document-pipeline behavior are not implemented or claimed. Their expected increases are all zero. Attachment retrieval remains `unknown` for any future statewide source until independently evidenced.

## Fixture and live-validation status

The existing local Tyler profiles remain fixture-verified for their local scopes. No new fixture contract or live production validation was performed. **Fixture verification is not live verification, and local fixture verification is not proof of statewide scope.** Live-verified and production-monitored counts remain unchanged at zero.

Authentication and CAPTCHA were not observed in the existing sanitized local fixtures; behavior for the unidentified statewide sources remains unknown. The capture checklist requires bounded observation of authentication, registration, CAPTCHA, redirects, throttling, and automation guidance before implementation.

## Security boundaries

Evidence capture remains anonymous, bounded, public, read-only, and fail-closed. This work does not automate login or vendor registration, submit bids, retain/replay credentials or cookies, circumvent CAPTCHA or access controls, disable SSRF protections, permit arbitrary hosts, follow unvalidated redirects, perform unbounded collection, download documents during discovery, or count local sources as statewide.

## Coverage before and after

| Metric | Before | After |
|---|---:|---:|
| Primary statewide sources identified | 18 | 18 |
| Platform families identified | 10 | 10 |
| Fixture-verified jurisdictions | 18 | 18 |
| Baseline-operational jurisdictions | 18 | 18 |
| Discovery-capable jurisdictions | 18 | 18 |
| Detail-capable jurisdictions | 16 | 16 |
| Attachment-capable jurisdictions | 16 | 16 |
| Document-pipeline-compatible jurisdictions | 6 | 6 |
| Live-verified jurisdictions | 0 | 0 |
| Production-monitored jurisdictions | 0 | 0 |
| Tier 0 jurisdictions | 38 | 38 |
| Jurisdictions lacking primary statewide sources | 38 | 38 |

## Reports regenerated and files changed

All authoritative coverage reports were regenerated and checked for deterministic consistency; no generated report changed because registry evidence and derived counts are intentionally unchanged.

- `docs/pr45_remaining_statewide_capture_selection.md`
- `PR_BODY.md`

Commit: `COMMIT_HASH` (replaced with the focused commit hash in the published PR metadata).

## Exact validation results

- `PYTHONPATH=src python -m unittest discover -s tests -v` — passed, 286 tests.
- `PYTHONPATH=src python -m compileall src tests` — passed.
- `ruff check .` — passed.
- `git diff --check` — passed.
- `PYTHONPATH=src python -m sled_aggregator.coverage validate` — passed: 56 jurisdictions, 0 warnings, 0 errors.
- `PYTHONPATH=src python -m sled_aggregator.coverage recommend` — passed; Alabama and Ohio remain ranks 19 and 20 after 18 live-validation tasks.
- All coverage status, matrix, missing, blocked, documents, queue, report, and gaps commands — passed.
- `PYTHONPATH=src python -m sled_aggregator.coverage regenerate` — passed.
- `PYTHONPATH=src python -m sled_aggregator.coverage check-reports` — passed: 0 files drifted.
- `python -m build` — not run successfully because the environment lacks the optional `build` module; `python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/pr45-wheel .` was also unavailable because the environment lacks the Hatchling build backend. The repository defines no separate type-check command.

## Known limitations and deferred work

This PR establishes no statewide source URL, platform family, tenant, endpoint, request parameter, response field, anonymous access behavior, or operational coverage for Alabama or Ohio. Those facts must be captured from official public evidence rather than inferred from local Tyler deployments.

The next breadth-first recommendation is bounded evidence capture for Alabama and Ohio. If they resolve to different platform families, their implementation must be split by family. If neither yields a deterministic public contract, proceed to the state/district identity tranche in jurisdiction-code order, followed by the territory-authority tranche. Live validation remains deferred until a lawful, anonymous, bounded production check is possible.
