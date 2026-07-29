# TrustEST SLED Aggregator

Backend-first procurement-intelligence service for discovering, normalizing,
and evaluating State, Local, Education, and Tribal opportunities.

The aggregator is the intake layer for a broader teaming-intelligence product.
It is intentionally limited to public, authorized, read-only procurement data.
It does not submit bids, bypass CAPTCHA, automate login walls, or circumvent
portal controls.

## Initial capabilities

- FastAPI service with versioned routes and health checks
- Canonical opportunity and solicitation-document models
- Reusable platform-family connector contract and registry
- Opportunity normalization and deterministic deduplication
- Document eligibility classification
- Access-state handling for public and restricted documents
- Configuration for targeted OCR and bounded ZIP processing
- PostgreSQL-ready runtime configuration
- SQLAlchemy persistence adapter and Alembic migration baseline
- Unit tests for normalization, classification, and connector registration
- Public WebProcure/PROACTIS discovery for Connecticut (CTsource), Missouri's
  legacy bid board, and Rhode Island (Ocean State Procures)
- Docker and GitHub Actions development baseline

## Architecture

```text
Portal connector
      |
      v
RawOpportunity ---> OpportunityNormalizer ---> CanonicalOpportunity
                                                |
Attachment metadata ---> DocumentClassifier ----+
                                                |
                                      downstream intelligence
                         matching | teaming | bid/no-bid | alerts | exports
```

Connectors are organized by platform family rather than jurisdiction. A single
connector may support multiple states, territories, agencies, counties, school
systems, or public authorities when they share the same portal implementation.

## Quick start

Requirements:

- Python 3.12+
- Docker (optional)

Create an environment and install the development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run the API:

```bash
uvicorn sled_aggregator.main:app --reload
```

Run checks:

```bash
python -m unittest discover -s tests -v
python -m compileall src tests
ruff check .
```

Or with Docker:

```bash
docker compose up --build
```

## API baseline

- `GET /health`
- `GET /api/v1/opportunities`
- `POST /api/v1/opportunities/normalize`
- `POST /api/v1/documents/classify`
- `GET /api/v1/connectors`

The opportunity service is repository-backed. PostgreSQL is the production
adapter; an in-memory adapter supports deterministic unit testing.

## Data principles

1. Store normalized text, structured fields, metadata, provenance, hashes, and
   links back to the opportunity and source document.
2. Retrieve only documents likely to contain the solicitation package,
   including RFP/RFQ/IFB, SOW/PWS, specifications, amendments, Q&A, pricing,
   evaluation, and submission instructions.
3. Run OCR only on image-only pages or standalone images.
4. Expand ZIP packages only inside configurable size, file-count, depth, path,
   encryption, and type safeguards.
5. Keep the newest valid active document record; historical redlines are
   deferred.
6. For login-, CAPTCHA-, or policy-restricted files, retain metadata and link
   back to the portal without attempting circumvention.
7. Use parsed data for summaries, matching, bid/no-bid, teaming, compliance,
   alerts, proposal planning, search, and user downloads.

## Adding a connector

Implement `BaseConnector`, declare its platform-family name and supported
jurisdictions, then register it:

```python
from sled_aggregator.connectors.base import BaseConnector
from sled_aggregator.connectors.registry import connector_registry

class ExampleConnector(BaseConnector):
    platform_family = "example"
    jurisdictions = ("Example State",)

    async def discover(self, query):
        ...

connector_registry.register(ExampleConnector)
```

Connector implementations must enforce public/read-only behavior, use bounded
timeouts and rate limits, and return source URLs and access-state metadata.

### WebProcure/PROACTIS

The reusable WebProcure connector searches only the public full-text endpoint
and supports bounded keyword or wildcard discovery for Connecticut, Missouri,
and Rhode Island. It performs GET requests only: it does not submit bids,
register vendors, automate login, bypass CAPTCHA or robots controls, store
credentials, or retrieve restricted documents. Restricted content remains at
its authoritative portal link.

Every result retains its complete source record. An authoritative direct URL is
used when supplied; otherwise the connector links to the configured public bid
board (including Rhode Island's owner-organization OID). Transient 429, 502,
503, and 504 responses and connection failures receive bounded exponential
backoff with jitter and `Retry-After` support. Repeated failed collection runs
open a configurable cooldown circuit, and connector health reports availability,
failure count, status, and failure time.

The production full-text endpoint has recently returned 502 and 503 responses.
Automated tests therefore use fixtures and test transports rather than requiring
live portal availability.

## Project layout

```text
src/sled_aggregator/
  api/             HTTP routes and dependencies
  connectors/      Platform-family connector contracts and registry
  domain/          Canonical models and enums
  services/        Normalization and document-selection rules
tests/             Standard-library unit tests
docs/              Architecture and operating constraints
```

## Roadmap

1. Add connector execution jobs, change detection, and observability.
2. Add more reusable public portal-family connectors.
3. Implement document retrieval, extraction, targeted OCR, and safe archives.
4. Add profile/capability matching and explainable fit scoring.
5. Feed teaming, compliance, risk, alert, and export workflows.

## Database migrations

Apply the current schema:

```bash
alembic upgrade head
```

Create a migration after changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe change"
```
