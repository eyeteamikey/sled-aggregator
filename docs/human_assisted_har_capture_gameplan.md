# Human-Assisted HAR Capture Game Plan

Status: proposed operating model
Scope: anonymous, public, read-only procurement portal validation

## Purpose

This plan separates portals that can be captured without human intervention from portals that
occasionally require a lawful human action, then defines how to operate both groups with minimal
human overhead.

Automation remains responsible for every capture job from scheduling through evidence packaging.
Human operators receive a narrow, temporary browser handoff only when a public workflow genuinely
requires their attention. Human assistance does not expand the allowed access boundary.

This plan supplements:

- [Safe HAR validation toolkit](safe_har_validation.md)
- [Connector-family HAR validation roadmap](connector_validation/README.md)

## Non-negotiable boundary

All work is anonymous, public, and read-only.

Allowed human actions:

- Complete an explicitly presented public CAPTCHA or browser challenge manually.
- Navigate public search, filter, sort, pagination, detail, amendment, Q&A, award, and document
  metadata pages.
- Select representative public documents when the portal permits anonymous download.
- Label the observed boundary and choose Resume, Abort, or Escalate.

Prohibited actions:

- CAPTCHA-solving services, automated challenge solving, proxy rotation, fingerprint evasion, or
  attempts to defeat bot protection.
- Login automation, credential use, account creation, registration, or vendor enrollment.
- Uploads, bid submission, questions to agencies, profile changes, acknowledgements, watch lists,
  subscriptions, or other mutations.
- Sharing browser sessions, cookies, credentials, profiles, or active session material between
  capture jobs.
- Indiscriminate production-document downloading.

Login, registration, payment, enrollment, or bid-participation requirements are terminal findings.
They are not tasks for a human operator to overcome.

## Portal classification

Every registered portal receives one operational class after bounded validation.

| Class | Definition | Default treatment |
| --- | --- | --- |
| `zero_touch` | A bounded capture completes without human action. | Schedule in the automated capture pool. |
| `transient_challenge` | A verification screen appears but may clear naturally. | Wait for a bounded interval; continue or escalate. |
| `human_challenge` | A public challenge requires a person to proceed. | Pause and enter the assistance queue. |
| `manual_walkthrough` | Public controls cannot yet be automated reliably. | Assign a trained operator while engineering records the missing recipe. |
| `authentication_boundary` | Login, registration, credentials, enrollment, or payment is required. | Record the boundary and stop. |
| `prohibited` | Continuing would require a mutation, bypass, or bid workflow. | Never execute. |
| `changed_contract` | A previously validated request or response contract no longer matches. | Quarantine for engineering review. |

The classification record should contain:

- Source and tenant identifiers.
- Portal family and starting URL.
- Classification and reason code.
- Last validation date.
- Capture recipe version.
- Allowed hosts and exact read-only POST rules.
- Expected request and response fingerprints.
- Per-host concurrency and rate limits.
- Challenge type and typical expiration time.
- Average human seconds per successful capture.
- Recent success, escalation, and abandonment rates.
- Evidence retention status.

## Capture job state machine

The capture job—not the operator—owns continuation.

```text
queued
  -> provisioning
  -> capturing
  -> bounded_wait                transient challenge only
  -> needs_human                 public challenge or manual control
  -> leased                      one operator, one browser, time limited
  -> resumed
  -> capturing
  -> hashing_raw_evidence
  -> sanitizing
  -> scanning
  -> analyzing
  -> review_ready
  -> approved | rejected | engineering_review
```

Terminal states include:

- `completed`
- `authentication_boundary`
- `prohibited_boundary`
- `operator_aborted`
- `challenge_expired`
- `capture_budget_exhausted`
- `changed_contract`
- `unsafe_response`
- `infrastructure_failure`

An abandoned human lease returns to the queue if the challenge remains usable. It does not give
the next operator access to the previous operator's account or a different portal session.

## Technical architecture

### Control plane

The control plane:

- Schedules capture jobs.
- Enforces global and per-host concurrency.
- Creates and destroys workers.
- Applies capture duration, request count, response size, and storage budgets.
- Owns the job state machine and operator leases.
- Records reason codes and audit events.
- Starts sanitization and scanning automatically.
- Prevents evidence promotion while high-severity findings remain.

### Ephemeral workers

Each capture receives an isolated worker with:

- One browser context and temporary profile.
- One evidence directory.
- No credentials or authenticated browser state.
- A source-specific host and request policy.
- Network and storage budgets.
- Automatic termination after artifacts are persisted.

Workers must not reuse cookies, local storage, profiles, downloads, or HARs from another job.

### Human-assistance console

Operators should receive a streamed view of only the assigned browser—not SSH, RDP, the cloud
console, the worker filesystem, or raw HAR storage.

The console should display:

- Source name and approved public URL.
- Why the job paused.
- The single allowed action.
- Prohibited actions and stop conditions.
- Challenge and lease timers.
- `Resume`, `Abort`, and `Escalate` controls.

Disable clipboard, local file transfer, browser-profile export, developer tools, and arbitrary URL
entry where practical. Record operator identity, job ID, timestamps, actions, and outcome.

## Initial instance plan

Begin with concurrency tokens rather than permanently assigning machines to people.

| Pool | Initial slots | Purpose |
| --- | ---: | --- |
| Automated capture | 6 | Zero-touch and pre-challenge capture stages |
| Human-assisted | 2 | Browser sessions actively waiting for an operator |
| Engineering quarantine | 1 | Changed contracts and unsafe/malformed behavior |
| Sanitization/analysis | 2 | Offline artifact processing |

Initial operating limits:

- One active capture per public host.
- One active interactive browser per operator.
- An operator may hold at most two leases, but only one may require current interaction.
- A shift lead may oversee all assisted slots but cannot expose raw HARs to operators.
- Scale workers from measured queue depth and utilization.
- Keep sanitization workers separate from browser workers where practical.

Before increasing concurrency, verify that the portal family tolerates the existing bounded rate
without rate limiting or bot-protection escalation. Do not use alternate IPs to evade a limit.

## Access-control model

Use named accounts, SSO, MFA, short-lived authorization, and just-in-time task access.

| Role | Permitted access |
| --- | --- |
| Level 1 operator | One leased browser session and job instructions |
| Shift lead | Assistance queue, reassignment, termination, reason-code correction, sanitized summaries |
| Evidence reviewer | Sanitized HARs, scan results, analysis, fixtures, reports, and hashes |
| Engineer | Quarantined debug worker, sanitized diagnostics, code and capture recipes |
| Security reviewer | Break-glass raw HAR access and sensitive-finding resolution |
| Cloud administrator | Infrastructure and identity configuration; no routine capture operation |

Raw HAR access should be exceptional. Operators and ordinary reviewers do not need it. At least two
named administrators should be capable of infrastructure recovery, but routine work should not use
administrator accounts.

Recommended controls:

- Central identity with immediate offboarding.
- MFA for every non-service identity.
- Device requirements for remote operators.
- Short session and idle timeouts.
- Per-task authorization instead of persistent instance membership.
- Recorded operator sessions and immutable audit events.
- No production credentials in the capture environment.
- Raw evidence encrypted at rest with a separate access role.
- Automatic access revocation when a lease ends.

## Staffing model

### Recommended launch model

- Paid operators aged 18 or older.
- Overseas virtual assistants for predictable assistance coverage.
- U.S. college-age interns for quality assurance, portal classification, and fixture review.
- One experienced shift lead.
- One engineering escalation owner.
- One designated evidence/security reviewer.

Workers under 18 should not be part of the initial production operation. Youth-employment hours,
school schedules, state-specific rules, supervision, consent, insurance, and security access add
more overhead than they remove. A later educational program can be evaluated separately with
employment counsel and participating schools.

Paid positions should be the default. An internship label does not by itself determine whether a
worker is entitled to wages. Relevant official guidance includes:

- [U.S. Department of Labor youth-employment rules](https://www.dol.gov/agencies/whd/fact-sheets/43-child-labor-non-agriculture)
- [U.S. Department of Labor internship guidance](https://www.dol.gov/agencies/whd/fact-sheets/71-flsa-internships)

For overseas personnel, begin with a vetted agency or employer-of-record unless the organization
already has local employment, tax, payroll, and security capability. Country selection should
follow a pilot and review of time-zone coverage, labor arrangements, English proficiency, vendor
security, connectivity, retention, and local legal requirements.

Vendor and employment agreements should address:

- Confidentiality and acceptable use.
- Required devices, patching, and endpoint protection.
- Prohibition on subcontracting without approval.
- Data access, retention, copying, sharing, and deletion.
- Incident reporting and investigation cooperation.
- Session monitoring and audit retention.
- Immediate access revocation and offboarding.
- Quality, scheduling, and escalation expectations.

Security expectations should be contractual and verified rather than assumed. See the
[FTC's service-provider security guidance](https://www.ftc.gov/business-guidance/resources/start-security-guide-business)
and [NIST Zero Trust Architecture](https://www.nist.gov/publications/zero-trust-architecture).

## Operator procedure

For every human-assisted job:

1. Accept one job lease.
2. Confirm the displayed source and public URL match the assignment.
3. Read the allowed action and stop conditions.
4. Complete only the explicitly permitted public challenge or navigation action.
5. Do not log in, register, upload, submit, follow, acknowledge, or enroll.
6. Choose `Resume` as soon as the allowed action is complete.
7. Choose `Abort` if a known terminal boundary appears.
8. Choose `Escalate` if the page is ambiguous, changed, or requests information.
9. Select one predefined outcome reason.
10. Release the lease; automation completes capture and evidence processing.

Operators must not improvise a new request contract. Engineering reviews and registers any new
route, field, host, or POST behavior before it becomes an automated recipe.

## Reason codes

Use a small controlled vocabulary:

- `challenge_completed`
- `challenge_cleared_without_action`
- `challenge_expired`
- `login_required`
- `registration_required`
- `payment_required`
- `vendor_enrollment_required`
- `terms_or_acknowledgement_required`
- `mutation_risk`
- `changed_page`
- `unexpected_host`
- `unsafe_download`
- `operator_uncertain`
- `infrastructure_problem`

Free-form notes may supplement a reason code but must not contain cookies, credentials, tokens, or
unsanitized request values.

## Evidence workflow

After capture, automation must:

1. Preserve the source HAR in ignored, access-controlled storage.
2. Compute and record SHA-256.
3. Inventory risk without printing sensitive values.
4. Sanitize into a separate artifact.
5. Remove cookies, authorization material, session state, browser fingerprints, active signed URLs,
   oversized bodies, binary documents, and login responses as required.
6. Preserve useful public procurement contacts, agency data, solicitation identifiers, vendors,
   awards, amendments, attachment metadata, and provenance.
7. Run the sensitive-data scanner.
8. Quarantine unresolved high-severity findings.
9. Produce request-contract analysis and capability evidence.
10. Derive only reviewed, minimal, fictionalized fixtures.

Raw HARs remain outside Git until the evidence-derived change is reviewed, merged, and confirmed on
`master`. Production documents, browser profiles, cookies, and complete HARs are never committed.

## Reducing human overhead

Prioritize these improvements in order:

1. Automate all work before and after the intervention.
2. Detect challenges without attempting to solve them.
3. Use a bounded wait for challenges known to clear naturally.
4. Notify operators only when an unexpired challenge is ready.
5. Resume the same job automatically after the operator acts.
6. Version reusable portal-family recipes instead of jurisdiction-specific scripts.
7. Automatically retry intermittent failures later without changing identity or evading protection.
8. Promote a portal back to `zero_touch` when repeated captures no longer require assistance.
9. Quarantine changed contracts instead of sending every failure to an operator.
10. Schedule assistance windows around actual queue arrival patterns.

The target is not maximum operator utilization. The target is minimum human seconds per approved,
safe evidence package.

## Four-week pilot

### Scope

- 20 previously validated zero-touch portals.
- 5 portals with known transient or human challenges.
- 6 automated, 2 assisted, and 1 engineering worker slots.
- 2 paid Level 1 operators with overlapping part-time shifts.
- 1 shift lead and 1 engineering escalation owner.

### Week 1: inventory and dry runs

- Assign operational classifications.
- Record host policies, recipes, expected fingerprints, and stop conditions.
- Dry-run the job state machine without granting external operator access.
- Confirm raw evidence storage, sanitization, scanning, and audit logs.

### Week 2: supervised assistance

- Run all operator sessions with a shift lead present.
- Measure challenge duration, human seconds, and reason-code accuracy.
- Fix console and runbook ambiguities immediately.

### Week 3: scheduled production pilot

- Introduce defined assistance windows.
- Permit automatic lease assignment.
- Review every completed evidence package.
- Compare domestic and overseas coverage windows if both are included.

### Week 4: scale decision

- Review cost, throughput, security, quality, and operator performance.
- Identify portals that can move to `zero_touch`.
- Identify portal families needing engineering recipes.
- Decide whether to add slots, shifts, or operators.

## Metrics

Track at least:

- Zero-touch completion percentage.
- Human-assisted completion percentage.
- Median and 95th-percentile human seconds per successful capture.
- Challenge detection-to-operator response time.
- Challenges clearing without human action.
- Expired and abandoned leases.
- Operator abort and escalation rates.
- Contract-drift and unsafe-response rates.
- Sanitizer and scanner rejection rates.
- Evidence-review rejection rate.
- Worker startup time and capture duration.
- Instance utilization and idle cost.
- Cost per approved evidence package.
- Revalidation success by portal family and recipe version.

## Scale gates

Increase staffing or instances only when:

- The access boundary and operator runbook are stable.
- Sanitized evidence consistently passes review.
- The queue, not avoidable workflow inefficiency, is causing delay.
- Per-host concurrency remains safe.
- Operator errors and escalations are within the agreed threshold.
- Offboarding, audit, and incident procedures have been tested.

Do not scale a portal family while its contract is changing, its challenge rate is increasing, or
its evidence packages frequently fail sanitization.

## Implementation backlog

1. Add operational classifications and intervention metrics to the source registry.
2. Implement the resumable job state machine and terminal boundary states.
3. Add per-host concurrency tokens and capture budgets.
4. Build ephemeral browser worker provisioning.
5. Build the browser-only assistance console.
6. Implement short-lived operator leases and automatic reassignment.
7. Add reason codes, audit events, and session recording.
8. Automate raw hashing, sanitization, scanning, analysis, and packaging.
9. Add the reviewer and security break-glass workflows.
10. Run the four-week pilot before selecting long-term staffing geography or fleet size.

## Definition of operational readiness

The human-assisted capture system is ready to scale only when:

- Every portal is classified.
- Zero-touch jobs run without operator access.
- Human jobs pause and resume without losing evidence continuity.
- Operators cannot access infrastructure, raw HAR storage, or unrelated jobs.
- Login and prohibited boundaries fail closed.
- All access is named, time limited, and auditable.
- Raw and sanitized evidence remain separate.
- High-severity findings block promotion.
- The pilot establishes measured staffing and instance requirements.
- An operations owner and engineering escalation owner are assigned.
