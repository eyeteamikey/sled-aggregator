# IonWave and OpenBids/DemandStar HAR evidence — 2026-08-16

Six anonymous browser captures were reviewed locally. The misleading `oracle-fusion` filename
label came from the recorder and is not the observed platform family. Complete HARs, cookies,
session values, Cloudflare challenge material, telemetry identifiers, and downloaded production
document bodies are excluded from Git.

## Evidence inventory

| SHA-256 | Classification |
| --- | --- |
| `7b41353ddcfd1f578e9a19d9e620206008156c8f9c371183003a93f86af95b4a` | Plano ISD IonWave invalid `CurrentSourcingEvents.aspx` attempt |
| `043ff1cf2e20e9b4081b04fe85da1a6de1afd19e45ffa125e7f6994f33d1fd98` | Plano ISD IonWave invalid-route confirmation |
| `08b32013ec05f1fd9b1221ef93fa18ff2d97c47b125d187accd36a1de8826335` | Town of Prosper IonWave invalid-route confirmation |
| `c2727d393e77279eab888affdbbaf599b42600a5b617b2deca274c8ee7de908e` | Plano ISD IonWave public listing/detail/document capture and challenge boundary |
| `4be59e42d7ec381d232a3853441e04c1c32a4f6d481b4a1e5967a87ae2438611` | Butler County, Kansas OpenBids/DemandStar agency capture |
| `b7e9365baa4d1172aa97721738e5bfe00585d70f4c94347f3e115b36ca4098b6` | City of Lynn Haven, Florida OpenBids/DemandStar agency capture |

## IonWave findings

- `CurrentSourcingEvents.aspx` redirected to `InvalidRequest.html` for both observed tenants.
- The confirmed anonymous listing route is `SourcingEvents.aspx?SourceType=1`.
- The live ASP.NET/Telerik grid exposes bid IDs separately from visible row cells. The row cells
  contain solicitation number, title, type, agency, issue date, and due date.
- `PublicDetail.aspx?bidID={id}&SourceType=1` exposed detail fields, public contacts, attachment
  metadata, public `Extract.aspx?e=...` links, and explicit login-required attachment labels.
- After several public interactions, Cloudflare returned HTTP 429 with an interactive human
  challenge. This is recorded as `captcha_required`; it is not retried as ordinary availability
  failure and is never bypassed.
- The Prosper capture proves the invalid route only, so it does not count as a second successful
  reusable-tenant validation.

## OpenBids/DemandStar findings

Both independently operated agency pages loaded an anonymous Euna OpenBids single-page app backed
by narrowly observed `https://api.demandstar.com/contents/agency` contracts:

- `GET /search?id={agency-uuid}` for agency-scoped discovery;
- `POST /summary` with `bidId` for details;
- `POST /documents` with `bidId` for document metadata;
- `POST /commodityByType` with `bidId` and `type: Bid` for categories;
- `POST /legal` with `bidId` was observed for Butler County; and
- `POST /planholders` with `bidId` was observed for Lynn Haven.

Public detail pages use `/app/limited/bids/{numeric-bid-id}/details`, not an agency UUID as the
opportunity identifier. Document metadata was anonymous, but returned document records lacked a
public path. Those documents are therefore classified `registration_required` and are not handed
to the download pipeline. Public planholder data is retained with source provenance where the
agency exposes it.

Only the listed host/path/method/body-key combinations are implemented. The connector does not
call token endpoints, register, authenticate, pay, submit bids, or infer download URLs.
