# PR #40 selection: Maine CGI Advantage Vendor Self Service

## Merge and selection gate

PR #39 is present as merge commit `da65d4a` and substantive commit `4fe0069`.
Its Pennsylvania connector/profile fixtures, authoritative registry evidence,
generated reports, regression test, selection report, and updated queue are all
present. This change does not recreate that work.

The generated queue ranks six already fixture-operational sources first because
they await live validation. This PR is explicitly the next **breadth-first**
implementation tranche, so those validation-only entries are excluded. Maine is
the highest-value evidence-backed reuse opportunity already represented by an
enabled, fixture-verified tenant in the reusable CGI Advantage VSS connector.
It adds a primary statewide source without inventing a tenant or endpoint.

## Selection report

| Field | Result |
|---|---|
| Recommendation rank | First breadth-first implementation after excluding ranks 1–6, which are live-validation tasks |
| Platform family | `cgi/advantage-vss` |
| Jurisdiction | Maine (`ME`) |
| Source ID / role / scope | `me-vss` / primary / statewide |
| Connector requirement | Reuse existing connector and explicit `maine/vss` profile |
| Platform evidence | Existing architecture, connector profile, CGI family documentation, and Maine-branded sanitized landing fixture |
| Public-contract evidence | Explicit `mevss.hostams.com/PRDVSS1X1` tenant routes plus sanitized guest, listing, pagination, empty, malformed/access, detail, attachment, award, duplicate, retry, and circuit-breaker tests |
| Authoritative evidence | Maine Division of Procurement Services VSS guidance and its public tenant link |
| Expected baseline / discovery / detail increase | +1 / +1 / +1 jurisdiction |
| Expected attachment increase | +1 manifest-capable jurisdiction |
| Expected document-pipeline increase | 0; deliberately `manifest_only` |
| Live-validation status | Not validated; no live claim and no live-verification date |
| Authentication / CAPTCHA | None observed in fixtures; production behavior remains unknown |
| Remaining uncertainty | Current live routes, redirects, availability, attachment retrieval, and records before October 1, 2025 |

Maine is a coherent single-profile tranche because Michigan and Colorado remain
disabled and configured-unverified. Branding alone is not used to promote either
one. Collection is anonymous, read-only, bounded, and capability-gated. It does
not log in, register, solve CAPTCHA, impersonate a vendor, enter a response
workspace, or submit a bid.

## Coverage impact and deferred validation

The registry moves from 10 to 11 identified sources and from 6 to 7
fixture-verified, baseline-operational, discovery-capable, detail-capable, and
attachment-capable jurisdictions. Primary-source gaps and Tier 0 jurisdictions
fall from 50 to 49. Primary platform-family identification increases from 6 to 7; CGI Advantage
VSS family reuse increases from zero to one primary jurisdiction. Document-pipeline-compatible jurisdictions remain 6 because the
fixture proves a manifest only, and live-verified jurisdictions remain 0.

A later validation phase should perform bounded anonymous guest discovery,
detail, and at most one clearly public small attachment request from a network
that reaches Maine's hosts. It must separately preserve pre-October 2025 archive
coverage. The next breadth-first recommendation is to research an authoritative
primary statewide source that can safely reuse an existing connector; Michigan
SIGMA and ColoradoVSS must remain unpromoted until tenant-specific public
contracts are independently evidenced.
