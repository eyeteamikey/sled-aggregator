# Authoritative procurement coverage control plane

## Scope and authority

The versioned registries in `data/coverage/` are the canonical control plane for procurement
coverage. The fixed baseline denominator is 56: 50 states, the District of Columbia, and American
Samoa, Guam, the Northern Mariana Islands, Puerto Rico, and the U.S. Virgin Islands. Explicit
`state`, `district`, and `territory` types prevent counties, municipalities, education systems,
authorities, tribal governments, and other tenants from entering that denominator. Those scopes
remain useful evidence for future expansion, but never imply statewide coverage.

A jurisdiction record owns its primary and supplemental source relationships and independently
records discovery, detail, attachment, document-pipeline, fixture, and live-validation state. A
source record owns portal identity, public URLs, normalized platform family, connector/profile,
access restrictions, evidence, limitations, and next action. Stable legacy `code` and `key` fields
remain aliases for `jurisdiction_id` and `source_id` for backward compatibility.

## Lifecycle and tiers

Lifecycle values are `unresearched`, `source_identified`, `evidence_pending`,
`connector_family_identified`, `connector_available`, `fixture_verified`, `live_verified`,
`partially_operational`, `operational`, `blocked`, `retired`, and `replaced`.

The deterministic tiers are:

- **Tier 0:** no evidence-backed authoritative statewide primary source.
- **Tier 1:** a primary source is identified but has no executable evidence-backed integration.
- **Tier 2:** a connector/profile is configured or fixture-only, but verified anonymous discovery
  is not established under the legacy tier contract.
- **Tier 3:** evidence-backed discovery is established.
- **Tier 4:** discovery, detail, and attachment identification are established.
- **Tier 5:** safe manifest/queue document-pipeline compatibility is established.
- **Tier 6:** Tier 5 plus dated, bounded, lawful anonymous live validation. Tier 6 is retained for
  backward compatibility; it is equivalent to the requested live-validated operational tier.

## Definitions of completion

**Baseline operational** requires an authoritative primary whose scope is actually statewide or
territory-wide, a registered connector/profile, fixture-tested anonymous discovery, canonical
normalization with authoritative backlinks, explicit failure/access classifications, and no
credential or CAPTCHA-bypass dependency. It does not require live validation. Detail, attachment,
document-pipeline, and live status are separately reported.

**Document-pipeline capable** additionally requires evidence-backed details and attachment
identification plus a connector registered with `PIPELINE_CONNECTORS`. This establishes safe entry
into the existing manifest and bounded retrieval queue; it does not assert every linked document is
publicly retrievable. Parsing, targeted OCR, extraction, and reconciliation remain downstream.

Fixture verification is never live verification. A source URL or connector family alone is never
operational proof. Planning recommendations are work controls, not functionality claims.

## Primary, supplemental, and local sources

`primary_statewide` is the best evidenced central statewide channel. `supplemental_statewide` adds
material statewide coverage without replacing the primary. Agency, transportation, construction,
education, local, legacy, replacement, and research-only records retain their actual scopes.
Detroit, Opelika, and Summit County fixtures therefore demonstrate only their tenants—not Michigan,
Alabama, or Ohio statewide coverage. A document adapter without a valid statewide discovery source
does not establish end-to-end statewide coverage.

## Evidence and access classifications

Every affirmative fixture capability links to an evidence record containing a stable ID, source,
capability, type, repository path or official URL, date, sanitization status, notes, and limitations.
Live claims require a date and public evidence URL. Do not commit credentials, cookies, CSRF or
bearer tokens, personal/vendor identifiers, or unsanitized HAR captures.

Authentication and CAPTCHA are explicit classifications, independent of discovery/detail/document
access. Unknown means unknown, not public or blocked. Collection must not automate login, bypass
CAPTCHA, or circumvent robots and portal restrictions; preserve metadata plus authoritative links
when retrieval is unavailable.

## Validation, reports, and maintenance

Validation checks the exact 56-record denominator, stable and unique IDs, types, source references,
statewide primary scope, connector registration, fixture evidence, safe URLs, live dates,
replacement consistency, and document-adapter registration. Errors name the record and corrective
action.

```bash
PYTHONPATH=src python -m sled_aggregator.coverage validate
PYTHONPATH=src python -m sled_aggregator.coverage status
PYTHONPATH=src python -m sled_aggregator.coverage matrix
PYTHONPATH=src python -m sled_aggregator.coverage missing
PYTHONPATH=src python -m sled_aggregator.coverage blocked
PYTHONPATH=src python -m sled_aggregator.coverage documents
PYTHONPATH=src python -m sled_aggregator.coverage recommend
PYTHONPATH=src python -m sled_aggregator.coverage queue
PYTHONPATH=src python -m sled_aggregator.coverage regenerate
PYTHONPATH=src python -m sled_aggregator.coverage check-reports
```

Regeneration deterministically writes JSON summary, Markdown capability matrix, connector reuse,
missing coverage, blocked sources, document readiness, and the JSON next-PR queue. Consistency
checking fails on missing or drifted output. Recommendations name registered sources and
jurisdictions; unidentified hypothetical families are rejected rather than ranked.

To add evidence, first register the source with its real scope, then add sanitized artifacts and an
evidence record, connector/profile and tests where applicable, and finally update the jurisdiction
relationship. Run validation, regenerate, and check reports. Schema 2.0 preserves existing IDs and
CLI entry points. This registry is the authoritative control plane for future state, county,
education, municipal, authority, tribal, and other expansion without conflating their denominators.
