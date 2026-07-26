# Repository guidance

## Product boundary

This repository provides public procurement intelligence. It does not submit
bids, bypass CAPTCHA, automate login walls, or circumvent portal restrictions.
Prefer metadata plus a source link whenever public retrieval is unavailable.

## Architecture

- Build reusable platform-family connectors before jurisdiction-specific ones.
- Normalize source records into canonical domain models before scoring them.
- Keep connector transport details outside domain and API layers.
- Every material extracted field must retain source provenance.
- OCR is a targeted fallback for image-only pages, not a default PDF step.
- Archive processing must remain bounded and path-safe.

## Development workflow

- Use feature branches; do not commit directly to `master`.
- Add or update tests with behavior changes.
- Run `python -m unittest discover -s tests -v`.
- Run `python -m compileall src tests`.
- Keep configuration in environment variables and never commit credentials.

