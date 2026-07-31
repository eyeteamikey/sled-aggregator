# Nationwide SLED Coverage Audit

**Data as of:** 2026-07-31
**Schema version:** 1.0
**Generation:** deterministic and offline (no network requests)

## Summary

| Metric | Count |
|---|---:|
| Primary jurisdictions | 56 |
| Sources | 8 |
| Implemented connectors | 20 |
| Public discovery | 8 |
| Public detail | 8 |
| Public document pipeline | 0 |
| Metadata only | 0 |
| Registration required | 0 |
| Login required | 0 |
| Subscription required | 0 |
| Payment required | 0 |
| CAPTCHA blocked | 0 |
| Robots-policy blocked | 0 |
| Automated-access blocked | 0 |
| Changed markup | 0 |
| Migrated sources | 0 |
| Jurisdictions without a configured source | 48 |
| Sources without live verification | 8 |

### Coverage-tier distribution

| Tier | Jurisdictions |
|---:|---:|
| 0 | 49 |
| 1 | 0 |
| 2 | 7 |
| 3 | 0 |
| 4 | 0 |
| 5 | 0 |
| 6 | 0 |

## Jurisdiction matrix

| Code | Jurisdiction | Type | Tier | Sources | Gaps |
|---|---|---|---:|---|---|
| AK | Alaska | state | 0 | — | no_source_identified |
| AL | Alabama | state | 0 | — | no_source_identified |
| AR | Arkansas | state | 0 | — | no_source_identified |
| AS | American Samoa | territory | 0 | — | no_source_identified, territory_gap |
| AZ | Arizona | state | 0 | — | no_source_identified |
| CA | California | state | 2 | ca-cal-eprocure | incomplete_award_coverage, incomplete_education_coverage, incomplete_local_coverage, incomplete_transportation_coverage, live_verification_missing |
| CO | Colorado | state | 0 | — | no_source_identified |
| CT | Connecticut | state | 0 | — | no_source_identified |
| DC | District of Columbia | district | 0 | — | no_source_identified |
| DE | Delaware | state | 0 | — | no_source_identified |
| FL | Florida | state | 0 | — | no_source_identified |
| GA | Georgia | state | 2 | ga-gpr | incomplete_education_coverage, incomplete_local_coverage, incomplete_transportation_coverage, live_verification_missing |
| GU | Guam | territory | 0 | — | no_source_identified, territory_gap |
| HI | Hawaii | state | 0 | — | no_source_identified |
| IA | Iowa | state | 0 | — | no_source_identified |
| ID | Idaho | state | 0 | — | no_source_identified |
| IL | Illinois | state | 0 | — | no_source_identified |
| IN | Indiana | state | 0 | — | no_source_identified |
| KS | Kansas | state | 0 | — | no_source_identified |
| KY | Kentucky | state | 0 | — | no_source_identified |
| LA | Louisiana | state | 0 | — | no_source_identified |
| MA | Massachusetts | state | 0 | — | no_source_identified |
| MD | Maryland | state | 2 | md-emma | incomplete_award_coverage, incomplete_education_coverage, incomplete_local_coverage, incomplete_transportation_coverage, live_verification_missing |
| ME | Maine | state | 0 | — | no_source_identified |
| MI | Michigan | state | 2 | mi-detroit-oracle-fusion | incomplete_award_coverage, incomplete_education_coverage, incomplete_transportation_coverage, live_verification_missing |
| MN | Minnesota | state | 0 | — | no_source_identified |
| MO | Missouri | state | 0 | — | no_source_identified |
| MP | Commonwealth of the Northern Mariana Islands | territory | 0 | — | no_source_identified, territory_gap |
| MS | Mississippi | state | 0 | — | no_source_identified |
| MT | Montana | state | 0 | — | no_source_identified |
| NC | North Carolina | state | 0 | — | no_source_identified |
| ND | North Dakota | state | 0 | — | no_source_identified |
| NE | Nebraska | state | 0 | — | no_source_identified |
| NH | New Hampshire | state | 0 | — | no_source_identified |
| NJ | New Jersey | state | 0 | — | no_source_identified |
| NM | New Mexico | state | 0 | — | no_source_identified |
| NV | Nevada | state | 0 | — | no_source_identified |
| NY | New York | state | 0 | — | no_source_identified |
| OH | Ohio | state | 0 | — | no_source_identified |
| OK | Oklahoma | state | 0 | — | no_source_identified |
| OR | Oregon | state | 0 | — | no_source_identified |
| PA | Pennsylvania | state | 2 | pa-emarketplace | incomplete_award_coverage, incomplete_education_coverage, incomplete_local_coverage, incomplete_transportation_coverage, live_verification_missing |
| PR | Puerto Rico | territory | 0 | — | no_source_identified, territory_gap |
| RI | Rhode Island | state | 0 | ri-rivip-external | incomplete_award_coverage, incomplete_education_coverage, incomplete_local_coverage, incomplete_transportation_coverage, live_verification_missing, no_source_identified |
| SC | South Carolina | state | 0 | — | no_source_identified |
| SD | South Dakota | state | 0 | — | no_source_identified |
| TN | Tennessee | state | 0 | — | no_source_identified |
| TX | Texas | state | 2 | tx-esbd | incomplete_award_coverage, incomplete_education_coverage, incomplete_local_coverage, incomplete_transportation_coverage, live_verification_missing |
| UT | Utah | state | 0 | — | no_source_identified |
| VA | Virginia | state | 2 | va-eva | incomplete_education_coverage, incomplete_local_coverage, incomplete_transportation_coverage, live_verification_missing |
| VI | U.S. Virgin Islands | territory | 0 | — | no_source_identified, territory_gap |
| VT | Vermont | state | 0 | — | no_source_identified |
| WA | Washington | state | 0 | — | no_source_identified |
| WI | Wisconsin | state | 0 | — | no_source_identified |
| WV | West Virginia | state | 0 | — | no_source_identified |
| WY | Wyoming | state | 0 | — | no_source_identified |

## Remaining platform-family gaps and prioritized next work

| Band | Score | Family | Factors | Next action |
|---|---:|---|---|---|
| P1 | 36 | Tyler Munis/VSS public bid search | jurisdictions_unlocked=5, statewide_impact=1, public_access=2, documents=2, reuse=3, complexity=2, maintenance_risk=1, blocked_penalty=0, territory_impact=0 | Build a reusable family only after confirming common public markup. |
| P1 | 33 | public CSV, RSS, XML, and JSON feeds | jurisdictions_unlocked=3, statewide_impact=1, public_access=3, documents=1, reuse=3, complexity=1, maintenance_risk=1, blocked_penalty=0, territory_impact=1 | Inventory stable official feeds and implement a reusable feed connector. |
| P1 | 31 | Oracle Cloud Procurement | jurisdictions_unlocked=4, statewide_impact=2, public_access=2, documents=1, reuse=3, complexity=2, maintenance_risk=2, blocked_penalty=0, territory_impact=0 | Research public tenant APIs; a new connector may be required. |
| P1 | 30 | Vendor Registry | jurisdictions_unlocked=4, statewide_impact=1, public_access=2, documents=1, reuse=3, complexity=2, maintenance_risk=1, blocked_penalty=0, territory_impact=0 | Confirm anonymous discovery and document boundaries. |
| P3 | 15 | territory-specific legacy portals | jurisdictions_unlocked=3, statewide_impact=2, public_access=1, documents=1, reuse=1, complexity=3, maintenance_risk=3, blocked_penalty=1, territory_impact=3 | Research authoritative territory sources without bypassing access controls. |

## Methodology and limitations

Tier 0 has no authoritative source; tier 1 identifies a source without executable integration; tier 2 is configured, unverified, or fixture-only; tier 3 verifies metadata discovery; tier 4 supports details and document links; tier 5 requires public document-pipeline compatibility; tier 6 additionally requires bounded live-public verification plus operational health. Changed markup and migrations downgrade coverage. Gated documents prevent full-document coverage.

The denominator is 50 states, the District of Columbia, and five inhabited territories. Tribal procurement is a separate future layer. Statewide sources do not imply complete local, education, transportation, authority, or quasi-public coverage. Fixture verification is not live verification. Configured coverage is not production verification. Unknown values remain unknown. Rankings are deterministic planning aids, not proof that a connector will work.

Registration, login, subscription, payment, CAPTCHA, robots-policy, and automated-access restrictions remain explicit gaps. Migrations count only when a current replacement is configured. Add evidence only from committed fixtures/documentation or a bounded public verification with its date and public evidence URL.
