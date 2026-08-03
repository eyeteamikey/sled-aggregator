# PR #45 selection: remaining statewide evidence capture for Alabama and Ohio

## Merge and selection gate

PR #44 is present as merge commit `afc2852` and substantive commit `9e08e47`.
Its Michigan SIGMA VSS profile, Advantage4 fixture routing, connector tests,
authoritative registry records, generated reports, selection report, and updated
queue are present. Michigan is baseline-operational and no longer appears in the
missing-primary-source report. This change does not recreate that tranche.

The pre-change queue contains 18 fixture-operational sources awaiting live
validation. Those validation-only tasks are excluded from this fixture-first
breadth tranche. No remaining registered statewide connector/profile candidate
has enough committed evidence for deterministic fixture-backed implementation.
The only remaining breadth recommendations are Alabama at generated rank 19 and
Ohio at generated rank 20, each with score 20. Both records are local Tyler
Munis VSS sources and therefore cannot be promoted to statewide coverage.
Accordingly, the queue-exhaustion rule selects the coherent local-evidence
correction tranche for Alabama and Ohio and records the evidence still required.

## Selection report

| Field | Result |
|---|---|
| Recommendation rank and score | Alabama: generated rank 19, score 20; Ohio: generated rank 20, score 20; evidence-capture rank 1 after excluding 18 live-validation tasks |
| Platform family | Unknown for each statewide source; the existing `tyler/munis-vss` evidence is explicitly local-only |
| Jurisdictions | Alabama (`AL`) and Ohio (`OH`) |
| Existing source IDs / roles | `al-opelika-tyler-munis-vss` and `oh-summit-county-tyler-munis-vss`; authoritative local primary sources, not statewide sources |
| Existing connector/profile availability | Reusable Tyler Munis VSS connector and local Opelika/Summit County profiles exist, but no evidence connects that family or either tenant to a statewide role |
| Source-identity evidence | Official municipal/county hosts establish only City of Opelika and Summit County ownership and scope |
| Request-contract evidence | Sanitized Tyler search/detail fixtures establish only the two fixed local profiles |
| Expected baseline / discovery / detail increase | 0 / 0 / 0 jurisdictions |
| Expected attachment / document-pipeline increase | 0 / 0 jurisdictions |
| Fixture-verification target | None in this PR; first capture an official statewide source identity and a tenant-specific public request contract |
| Live-validation status | Not performed; live-verified and production-monitored counts remain zero |
| Authentication / CAPTCHA | None observed in the local sanitized fixtures; statewide behavior is unknown |
| Remaining uncertainty | Statewide source identity and role, platform family, official landing and bid-board URLs, tenant, routes, parameters, response fields, anonymous access, redirects, pagination, detail and attachment contracts, authentication, CAPTCHA, and automated-access policy |

Fixture verification is **not** live verification. Local fixture verification is
also not evidence of statewide scope. No source is promoted to
`source_identified`, `platform_identified`, `fixture_verified`, `live_verified`,
or `production_monitored` statewide status by this evidence-planning change.

## Exact capture checklist for the selected tranche

For both Alabama and Ohio, capture all of the following before implementation:

1. An official state-controlled page naming the primary statewide procurement
   source and describing its statewide role.
2. Stable source IDs for the newly established statewide sources; do not reuse
   the local Opelika or Summit County IDs.
3. Official landing and public bid-board URLs plus the platform family and fixed
   tenant identifier, when applicable.
4. Evidence of each public request method, route, parameter, pagination rule,
   result field, stable opportunity identifier, detail backlink, and attachment
   or amendment contract.
5. A bounded anonymous access observation recording redirects, authentication,
   registration, CAPTCHA, robots/automation guidance, throttling, and
   `Retry-After` behavior without crossing an access boundary.
6. Sanitized search, pagination, empty, detail, attachment, amendment,
   duplicate, missing-field, malformed, access-wall, and transient-failure
   fixtures supported by the captured contract.

Until those prerequisites are committed, implementation would require inventing
a statewide source, tenant, endpoint, or response contract and is prohibited.

## Breadth-completion audit

All 56 jurisdictions have been audited. Eighteen have fixture-verified primary
statewide sources; the 38 rows below remain Tier 0. For every row, the minimum
missing prerequisite is official primary statewide-source identity and scope.
Rows with local evidence additionally require an explicit correction that keeps
the local source supplemental to any future statewide record. Territory rows
require territory-wide authority and scope rather than an assumed state model.

| Jurisdiction | Current evidence | Exact missing prerequisite | Capture tranche |
|---|---|---|---|
| Alabama (`AL`) | Opelika Tyler Munis VSS, local only | Official statewide identity/scope, then platform, tenant, and public contract evidence | 1 — selected local-evidence correction |
| Ohio (`OH`) | Summit County Tyler Munis VSS, local only | Official statewide identity/scope, then platform, tenant, and public contract evidence | 1 — selected local-evidence correction |
| Alaska (`AK`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Arkansas (`AR`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Arizona (`AZ`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Colorado (`CO`) | No registered statewide source; disabled ColoradoVSS preset is unverified | Official statewide identity/scope and tenant-specific public contract evidence; do not infer it from the preset | 2 — states and district source identity |
| District of Columbia (`DC`) | No registered source | Official district-wide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Delaware (`DE`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Florida (`FL`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Hawaii (`HI`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Idaho (`ID`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Indiana (`IN`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Kansas (`KS`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Kentucky (`KY`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Louisiana (`LA`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Minnesota (`MN`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Missouri (`MO`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Mississippi (`MS`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Montana (`MT`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| North Carolina (`NC`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| North Dakota (`ND`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Nebraska (`NE`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| New Hampshire (`NH`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| New Mexico (`NM`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| New York (`NY`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Oklahoma (`OK`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| South Carolina (`SC`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| South Dakota (`SD`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Tennessee (`TN`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Vermont (`VT`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Washington (`WA`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Wisconsin (`WI`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| West Virginia (`WV`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| Wyoming (`WY`) | No registered source | Official statewide identity/scope, official URLs, platform/tenant, and public contract evidence | 2 — states and district source identity |
| American Samoa (`AS`) | No registered source | Official territory-wide procurement authority/source identity and scope, official URLs, platform/tenant, and public contract evidence | 3 — territory authority and source identity |
| Guam (`GU`) | No registered source | Official territory-wide procurement authority/source identity and scope, official URLs, platform/tenant, and public contract evidence | 3 — territory authority and source identity |
| Northern Mariana Islands (`MP`) | No registered source | Official territory-wide procurement authority/source identity and scope, official URLs, platform/tenant, and public contract evidence | 3 — territory authority and source identity |
| Puerto Rico (`PR`) | No registered source | Official territory-wide procurement authority/source identity and scope, official URLs, platform/tenant, and public contract evidence | 3 — territory authority and source identity |

## Coverage impact and next breadth-first work

Because this is an evidence-capture plan, all before/after coverage counts are
unchanged: primary statewide sources identified 18/18; platform families
identified 10/10; fixture-verified, baseline-operational, and discovery-capable
jurisdictions 18/18; detail-capable 16/16; attachment-capable 16/16;
document-pipeline-compatible 6/6; live-verified 0/0; production-monitored 0/0;
Tier 0 jurisdictions 38/38; and jurisdictions lacking primary statewide sources
38/38.

The next breadth-first recommendation is to perform tranche 1 evidence capture
for Alabama and Ohio. If that capture establishes different platform families,
split implementation by family rather than combining them. If neither produces
a deterministic public contract, proceed to tranche 2 in jurisdiction-code
order while keeping every unevidenced source below fixture-verified status.

## Security boundaries

Evidence capture is bounded, anonymous, public, and read-only. It must not log
in, register a vendor, submit a bid, retain or replay credentials or cookies,
solve CAPTCHA, bypass controls, follow unvalidated redirects, permit arbitrary
hosts, or treat local procurement as statewide. Discovery must not download
documents. Attachment access remains `unknown` until independently established.
