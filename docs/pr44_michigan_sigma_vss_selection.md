# PR #44 selection: Michigan SIGMA Vendor Self Service

## Merge and selection gate

PR #43 is present as merge commit `1687cff` and substantive commit `a3064b4`.
Its Connecticut and Rhode Island WebProcure profiles, connector tests,
authoritative registry records, generated reports, selection report, and updated
queue are present. Both jurisdictions are baseline-operational and no longer
appear in the missing-primary-source report. This change does not recreate that
tranche.

The pre-change generated queue ranks 17 fixture-operational sources awaiting
live validation first. Those validation-only tasks are excluded from this
fixture-first breadth tranche. Michigan appears at generated recommendation rank
19 with score 20 as a statewide coverage-correction task. After applying the
selection rules, it is breadth implementation rank 1 among remaining candidates
with an evidence-backed existing statewide profile: the reusable CGI Advantage
VSS connector already contains the fixed `michigan/sigma-vss` tenant, the
official SIGMA pages establish its statewide role, and sanitized Advantage4
fixtures establish deterministic behavior without inventing a route or tenant.
Alabama's higher generated coverage-correction rank is not selected because its
fixture is explicitly local and does not establish a primary statewide source.

## Selection report

| Field | Result |
|---|---|
| Recommendation rank and score | Generated rank 19, score 20; breadth implementation rank 1 after excluding 17 live-validation tasks and the local-only Alabama candidate |
| Platform family | `cgi/advantage-vss` |
| Jurisdiction | Michigan (`MI`) |
| Source ID / role | `mi-sigma-vss`; primary statewide source |
| Connector/profile availability | Reuse `CGIAdvantageVSSConnector` and existing fixed `michigan/sigma-vss` Advantage4 profile |
| Source-identity evidence | Michigan SIGMA budget-office guidance and DTMB Contract Connect guidance identify SIGMA Vendor Self Service as the statewide procurement/vendor system |
| Request-contract evidence | Fixed `sigma.michigan.gov/PRDVSS1X1` tenant, explicit Advantage4 landing/search/detail routes, SIGMA-branded sanitized landing fixture, and shared sanitized search/detail fixtures |
| Expected baseline / discovery / detail increase | +1 / +1 / +1 jurisdiction |
| Expected attachment increase | +1 manifest-capable jurisdiction |
| Expected document-pipeline increase | 0; deliberately `manifest_only` until safe retrieval is established |
| Fixture-verification target | Profile routing, GET request construction, bounded pagination/results, stable tenant-scoped IDs, normalization, deduplication, detail enrichment, attachment/amendment manifest metadata, backlinks, raw payload preservation, malformed/access responses, retries, `Retry-After`, circuit breaking, health, host safety, and client ownership |
| Live-validation status | Not validated; live count and dates remain unchanged |
| Authentication / CAPTCHA | None observed in sanitized fixtures; current production behavior remains unknown |
| Remaining uncertainty | Current reachability and markup, anonymous sessions, availability windows, redirects, attachment retrieval, documents outside SIGMA, and any present authentication or CAPTCHA boundary |

## Contract and security boundaries

Collection is asynchronous, bounded, public-read-only, and GET-only. The fixed
profile permits only its reviewed tenant host, retains tenant-scoped IDs and
source backlinks, terminates repeated pagination, deduplicates deterministic
records, and fails closed on disabled profiles, malformed responses, login,
registration, verification, CAPTCHA, invitation-only, stable forbidden, or
scheduled-unavailable responses. Transient retries are bounded and honor both
forms of `Retry-After`; health and circuit state remain isolated by tenant.

Discovery creates attachment manifests only. It does not download documents,
run parsers or OCR, open archives, enter purchasing or response workspaces, log
in, register a vendor, retain credentials/cookies outside the owned client,
bypass CAPTCHA or access controls, impersonate a vendor, or submit a bid.

## Coverage impact and deferred validation

The registry moves from 17 to 18 identified and fixture-verified primary
statewide sources. Baseline-operational, discovery-capable, detail-capable, and
attachment-capable jurisdictions each increase from 17/17/15/15 to 18/18/16/16.
Primary-source gaps and Tier 0 jurisdictions fall from 39 to 38. Identified
primary platform families remain ten because Michigan reuses CGI Advantage VSS.
Document-pipeline-compatible jurisdictions remain six, and live-verified
jurisdictions remain zero. Fixture verification is explicitly **not** live
verification, and no fixture date populates a live-verification field.

Deferred work is a respectful bounded anonymous production check from a
permitted network: first review robots and availability guidance, then request
at most one discovery page, one linked detail, and one explicitly public small
attachment, stopping on restrictions or throttling. ColoradoVSS is the next
existing CGI profile to research, but remains disabled until its tenant-specific
public request contract is independently evidenced; the generated breadth queue
otherwise returns to authoritative statewide-source research for Alabama.
