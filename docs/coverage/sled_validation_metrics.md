# SLED validation reconciliation

As of **2026-08-30**. All counts are derived offline from `data/coverage/sources.json`; fixture evidence is never promoted to live evidence.

## Current metrics

- Registered source records: **38**
- Unique normalized portal tenants: **36**
- Unique platform families: **19**
- Implemented connector families: **21**
- Connector families represented by two independent tenants: **11**

## Coverage funnel

| Stage | Completed | Remaining | Percentage | Denominator | Meaning |
| --- | ---: | ---: | ---: | ---: | --- |
| `core_potential_portal_owners` | 103,947 | 0 | 100.0000% | 103,947 | Fixed universe of potential portal-owning core SLED organizations; not a validation claim. |
| `official_source_discovered` | 38 | 103,909 | 0.0366% | 103,947 | Entities with an official procurement source recorded, measured against the core universe. |
| `normalized_portal_tenant` | 36 | 2 | 94.7368% | 38 | Connector-backed unique tenants among entities with a discovered source. |
| `official_link_evidence` | 36 | 0 | 100.0000% | 36 | Normalized tenants with an official government starting link recorded. |
| `live_listing_validation` | 14 | 22 | 38.8889% | 36 | Normalized tenants with point-in-time anonymous listing evidence. |
| `detail_validation` | 12 | 24 | 33.3333% | 36 | Normalized tenants with live full-detail or explicitly metadata-only detail evidence. |
| `document_validation` | 0 | 36 | 0.0000% | 36 | Normalized tenants with an anonymously downloaded representative document; metadata alone does not qualify. |
| `scheduled_production_monitoring` | 0 | 36 | 0.0000% | 36 | Normalized tenants with scheduled-live or production-monitoring evidence. |

Percentages are stage-specific. In particular, the 103,947 organization universe is used only where stated; tenant-validation percentages use normalized tenants and never imply percent of all SLED complete.

## Evidence tiers

| Evidence tier | Tenants/records |
| --- | ---: |
| `production_monitored` | 0 |
| `scheduled_live_verified` | 0 |
| `live_public_verified` | 9 |
| `public_metadata_only` | 5 |
| `official_link_verified` | 2 |
| `fixture_verified` | 22 |
| `configured_unverified` | 0 |
| `blocked` | 0 |
| `not_researched` | 0 |

## Capability outcomes

- Anonymous listings live-verified: **14**
- Details live-verified or explicitly metadata-only: **12**
- Attachment metadata live-verified: **3**
- Anonymous representative downloads verified: **0**
- Document extraction pipeline fixture/live verified: **10**
- CAPTCHA/WAF-blocked tenants: **2**
- Login/registration-gated tenants: **8**

The complete per-capability status distribution is in `data/coverage/sled_validation_metrics.json`. A visible tab, attachment name, or fixture parser does not count as an anonymous download.

## Buyer classes

| Buyer class | Records |
| --- | ---: |
| county | 13 |
| municipality | 1 |
| K–12 | 1 |
| higher education | 0 |
| special district | 0 |
| housing | 0 |
| transit | 0 |
| port | 0 |
| airport | 0 |
| tribal | 0 |
| regional | 0 |
| cooperative | 3 |

## Reconciled wave boundary

Public Purchase, DemandStar/OpenBids, CGI Advantage/VSS, BidNet Direct, Euna Bonfire, and PlanetBids now have two tenant records apiece. Their point-in-time evidence remains tenant-specific. No family is classified as scheduled-live or production-monitored. Public Purchase details/documents are gated; Bonfire details were WAF-blocked; CGI stateful actions and PlanetBids background requests still need desktop HAR capture; BidNet and DemandStar documents require registration.

## Next wave

The machine-readable plan contains **10** targets: six deepening tasks and four new-family or materially distinct validation tasks. See `data/coverage/next_validation_wave.json`.
