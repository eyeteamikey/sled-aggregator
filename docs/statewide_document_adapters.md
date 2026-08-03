# Statewide document adapters

The statewide Georgia GPR, Maryland eMMA, and Virginia eVA connectors translate
their existing fixture-backed detail metadata into the canonical document pipeline.
They do not download files during discovery and do not implement a second queue,
downloader, parser, OCR system, or extraction engine.

California Cal eProcure, Texas ESBD, and Rhode Island RIVIP now follow the same
adapter contract. Cal eProcure reacquires only its anonymous public session, ESBD
retains account-gated external links as metadata, and RIVIP excludes public bid
response links from retrieval eligibility.

## Evidence and access boundaries

All three adapters are verified with sanitized HTML/embedded-JSON fixtures and
injected transports. Public and gated rows occur in those fixtures. Only an explicitly
public, direct attachment is retrieval eligible. Login, supplier registration/profile,
unavailable, unknown, and unsafe rows remain metadata-only; the connectors never log in,
register, solve CAPTCHA, or enter bid-response workflows.

* Georgia accepts the official GPR hosts and explicitly configured document hosts.
* Maryland accepts eMMA and its explicitly configured approved document hosts.
* Virginia accepts HTTPS attachments on the public eVA host. An anonymous public
  session may be reacquired by ordinary public detail discovery, but authentication is
  never attempted.
* California uses fixture-verified PeopleSoft event attachments and never persists
  session state in document metadata.
* Texas distinguishes direct public ESBD media and public external files from
  account-required external documents.
* Rhode Island accepts only configured purchasing hosts and never retrieves public
  bid response links.

## Identity and versions

An explicit source attachment ID is the stable identity. Where eVA omits that ID, the
sanitized fallback combines source lot, round, and normalized attachment path. Query
parameters, tokens, retrieval time, row position, filename, and title are not used as
the sole identity. URLs remain retrieval material but are removed from sanitized raw
document metadata. Numeric versions and eVA rounds populate canonical version fields;
addendum and amendment numbers remain queryable. Shared manifest reconciliation keeps
the newest operational version current without collapsing addenda into the base file.

## Known limitations

Verification is fixture-only, not a statement about current live availability. eVA
temporary links can expire and must be reacquired through the bounded public detail
workflow. A future host or markup change fails closed until fixtures and the explicit
allowlist are updated. Metadata without any safe source URL cannot form the current
required `DocumentCandidate` and is therefore skipped rather than fabricated.
