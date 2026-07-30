## Motivation
Public Purchase hosts agency-specific procurement portals with distinct anonymous, registered,
agency-enrolled, bid-participation, and paid-syndication layers. Procurement intelligence needs a
safe way to retain public metadata and official alternatives without crossing those boundaries.

## Description
Adds the reusable `public-purchase` connector, explicit aliases, configurable profiles,
fixture-backed semantic HTML/JSON parsing, agency-qualified identities, document candidates,
access classification, bounded collection, retry/circuit health, tests, and documentation.

## Platform architecture
Profiles define the agency, observed `/gems/` routes, lifecycle and verification state, explicit
host allowlists, parser variant, and strict page/result bounds. Transport, parsing, normalization,
and document discovery remain separate. Public Purchase is kept separate from BidNet Direct,
PlanetBids, DemandStar, BidX, Public Surplus, Vendor Registry, OpenGov, and BuySpeed.

## Public metadata behavior
Anonymous listing and detail metadata is normalized with raw identifiers, canonical/discovered
URLs, timestamps, and field provenance. Stable IDs are
`public-purchase:{profile_key}:{opportunity_id}`. Public metadata is retained when documents are
gated.

## Registration and agency-enrollment boundaries
Free registration is still an access boundary. Agency enrollment is a separate boundary and is not
automated. The connector never creates accounts, authenticates, manages vendor profiles, receives
notifications, acknowledges addenda, asks questions, or submits responses.

## Paid Bid Syndication exclusion
Paid Bid Syndication and non-member-agency paid aggregation are not used. An anonymously visible
syndicated notice retains upstream authority and should defer to the dedicated upstream connector.

## Source provenance
Records distinguish Public Purchase member agencies, official agency mirrors, syndicated external
notices, and unknown sources. Material values and source/agency URLs retain provenance.

## Document pipeline integration
Document candidates cover solicitations, specifications, plans, forms, addenda, Q&A, results, and
awards. Gated metadata is retained but not queued. Eligible anonymous files use the existing
manifest, durable queue, safe downloader, parsing, targeted OCR, extraction, and versioning path.

## Official agency alternatives
Approved public agency copies are preferred when available. Both the gated platform reference and
public official reference remain linked, while only the public candidate is retrieval eligible.

## Robots and automated-access policy
Robots policy, login/registration/enrollment walls, CAPTCHA, bot challenges, and technical blocks
are terminal. Redirects are revalidated and unsafe/private/unapproved targets fail closed. No
browser impersonation, proxy rotation, CAPTCHA bypass, or technical evasion is implemented.

## Resilience and safety
Collection is read-only and bounded. Only transient transport failures and 429/502/503/504 are
retried with Retry-After, exponential backoff, and jitter. Per-profile circuits, cooldown, recovery,
and health timestamps prevent retry storms. Owned clients close; injected clients remain owned by
the caller.

## Verification status
The included profile and sanitized captures are `fixture_verified`; no live request was made.
Fixture verification demonstrates behavior against captured test inputs. It does not prove that
every live Public Purchase agency, opportunity, or attachment remains anonymously accessible.

## Testing
- `PYTHONPATH=src python -m unittest discover -s tests -v` (227 tests)
- `PYTHONPATH=src python -m compileall src tests`
- `ruff check .`
- `ruff format --check` for changed Python files
- `git diff --check`

## Known limitations
Only explicitly configured agencies, approved hosts, and fixture-observed route/markup variants are
supported. Availability may differ by agency and change over time. No universal live anonymous
access is claimed, gated files remain unavailable, and paid aggregation is intentionally excluded.

## Codex Cloud publication notes
No fetch, pull, push, GitHub authentication, or shell PR command was used. The local commit is ready
for publication through Codex Cloud Create PR. Any future live check must be at most two bounded,
anonymous, short-timeout requests with no login, registration, enrollment, download, or bid action.
