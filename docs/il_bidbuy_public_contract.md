# Illinois BidBuy anonymous public contract

The request contracts below are fixture-verified from a successful anonymous public browser
capture dated 2026-08-12. This is evidence of the observed contract, not a claim of continuous
production availability.

The connector starts with `GET /bso/view/search/external/advancedSearchBid.xhtml`, retains the
anonymous HTTP session, and extracts `_csrf` and `javax.faces.ViewState` dynamically. It then uses
only the observed read-only POST contracts:

- search and filtering at `/bso/view/search/external/advancedSearchBid.xhtml`;
- bounded PrimeFaces pagination at the same path;
- attachment retrieval metadata at `/bso/external/bidDetail.sda`.

Solicitation details use `GET /bso/external/bidDetail.sda` with the observed `docId`, `external`,
and `parentUrl` query shape. Search responses are XML JSF partial responses. The connector fails
closed on missing tokens, malformed partial responses, login walls, CAPTCHA responses, and
unexpected HTTP failures. Duplicate source identifiers and configured page/result limits bound
collection. Public CSV, Excel, and PDF export behavior was observed but is not a discovery
dependency.

Public procurement contacts—including buyer/contact names, government email addresses, public
phone numbers, departments, and addresses—are retained as aggregation data in source provenance.
Publicly disclosed vendor data is likewise retained where present. The capture exposed an awarded
vendor column and vendor content on representative detail pages; no broader bidder or awardee
capability is claimed.

Cookies, JSESSIONID, CSRF/XSRF tokens, ViewState, authorization values, and other authentication or
session state are never persisted in fixtures or opportunity payloads. Attachment metadata keeps
the public filename/description, parent opportunity, and required request field names, while live
values are acquired within the current anonymous session. No bid submission, vendor mutation,
login, registration, or CAPTCHA bypass is supported.

Deterministic fixtures:

- `tests/fixtures/il_bidbuy_initial.html`
- `tests/fixtures/il_bidbuy_results.xml`
- `tests/fixtures/il_bidbuy_detail.html`

The full HAR and downloaded binary attachment bodies are intentionally excluded from the
repository.
