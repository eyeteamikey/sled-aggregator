## Motivation

Connect California Cal eProcure, Texas ESBD, and Rhode Island RIVIP's existing fixture-backed document metadata to the shared document pipeline.

## Implementation

- Adds canonical `DocumentCandidate` adapters for PeopleSoft/Cal eProcure and Texas ESBD.
- Enables the existing RIVIP adapter and removes document URLs from its sanitized raw metadata.
- Preserves stable source attachment identities, versions, addenda, access states, and authoritative parent provenance.
- Adds all three connector families to the orchestration compatibility set.
- Refreshes the generated coverage reports; the derived public document pipeline count increases from 7 to 10.

## Access and security boundaries

Discovery remains anonymous and read-only. Public PeopleSoft session reacquisition does not cross a login boundary. ESBD external account-required files and RIVIP public bid response links remain metadata-only. The adapters do not download files, log in, register vendors, solve CAPTCHA, acknowledge addenda, or enter response workflows.

## Evidence

Sanitized deterministic fixtures and injected transports cover all three adapters. This is fixture verification, not a claim of current live portal availability. Explicit source IDs are preferred; path or official media identifiers provide stable fallbacks without using session tokens, retrieval time, or row position.

## Testing

- `python -m unittest discover -s tests -v`
- `python -m compileall src tests`
- `ruff check .`
