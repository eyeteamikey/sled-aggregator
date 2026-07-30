## Motivation
Add anonymous procurement intelligence for configurable, agency-specific PlanetBids portals without using VendorLine or crossing participation boundaries.

## Description
Adds the `planetbids` family, explicit aliases, sanitized fixtures, tests, and operator documentation.

## Platform architecture
Separates transport, profile configuration, HTML/JSON parsing, normalization, per-resource access classification, document extraction, and per-profile health. PlanetBids uses agency-specific vendor portals.

## Agency-profile configuration
Profiles define tenant identity, jurisdiction, official and portal URLs, exact approved hosts, collection bounds, variant, verification notes, lifecycle state, and replacement metadata.

## Public access boundaries
Some metadata and documents can be public, while agencies can restrict individual documents behind login. Some resources require prospective-bidder participation and some solicitations are invitation-only. The connector does not register, authenticate, participate, acknowledge, RSVP, ask, or submit.

## Discovery and detail behavior
Anonymous GET-only discovery is bounded, filtered, deduplicated, stably ordered, and tenant-qualified. Detail records preserve raw payload, authoritative links, and field provenance.

## Document pipeline integration
Public candidates feed the existing manifest and safe retrieval pipeline. Gated candidates retain access state but are not queued. Shared downloading, parsing, targeted OCR, structured extraction, and version reconciliation remain unchanged.

## Q&A, addenda, results, and awards
Publicly released resources are preserved separately with source metadata; prospective-bidder lists are not treated as submissions or awards.

## Resilience and safety
Exact HTTPS allowlists, credential/IP rejection, bounded retries and exponential backoff, Retry-After, per-profile circuits, changed-markup detection, and owned-client lifecycle behavior are covered. VendorLine aggregation and paid functionality are not used.

## Migration handling
Legacy, migrated, and unavailable profiles fail closed and can identify a replacement without aliasing it to PlanetBids.

## Verification status
Behavior is `fixture_verified`; no live portal is configured. Fixture tests do not prove that every live agency remains anonymously accessible. No live verification was performed.

## Testing
The full unit, compile, Ruff lint/format, and diff checks were run (see final task report).

## Known limitations
Only fixture-demonstrated public GET shapes are supported. POST-only search, authentication, CAPTCHA, VendorLine, participation actions, private APIs, sealed responses, and invitation-only content are intentionally unsupported.

## Codex Cloud publication notes
The changes are ready for publication through the Codex Cloud Create PR button. No fetch, pull, push, shell GitHub authentication, or shell PR publication is required.
