import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.connectors.tyler_munis_vss import (
    OPELIKA,
    SUMMIT,
    TylerMunisVssAccessError,
    TylerMunisVssConnector,
    TylerMunisVssError,
    TylerMunisVssQuery,
    form_state,
    parse_page,
    redact_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text()


def reply(body, url, status=200, headers=None):
    request = httpx.Request("GET", url)
    return httpx.Response(
        status, text=body, request=request, headers=headers or {"content-type": "text/html"}
    )


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.closed = False

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.replies.pop(0)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.replies.pop(0)

    async def aclose(self):
        self.closed = True


class TylerMunisVssTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_profiles_and_mobile_unsupported(self):
        cls = connector_registry.get("tyler/munis-vss")
        for alias in ("tyler-munis-vss", "munis-vss", "tyler/vss", "munis/vendor-self-service"):
            self.assertIs(connector_registry.get(alias), cls)
        self.assertEqual(SUMMIT.key, "oh-summit-county-tyler-munis-vss")
        self.assertEqual(OPELIKA.key, "al-opelika-tyler-munis-vss")
        self.assertNotIn("mobile", " ".join(p.key for p in (SUMMIT, OPELIKA)))

    def test_profile_validation_and_ssrf(self):
        for change in (
            {"base_url": "http://summitcountyoh.munisselfservice.com/vss/"},
            {"base_url": "https://user@sumit.example/vss/"},
            {"base_url": "https://127.0.0.1/vss/", "allowed_hosts": frozenset({"127.0.0.1"})},
            {"maximum_pages": 0},
            {"document_path": "../private"},
        ):
            with self.assertRaises(ValueError):
                replace(SUMMIT, **change)

    def test_form_state_and_semantic_search_controls(self):
        html = fixture("tyler_vss_search.html")
        state = form_state(html, require_event_validation=True)
        self.assertEqual(state["__VIEWSTATE"], "TEST_VIEWSTATE")
        connector = TylerMunisVssConnector(transport=FakeTransport([]))
        data = connector.search_form(
            html, TylerMunisVssQuery(keywords=("roads",), bid_number="100", open_only=False)
        )
        self.assertEqual(data["ctl00$Main$BidDescription"], "roads")
        self.assertEqual(data["ctl00$Main$BidNumber"], "100")
        self.assertEqual(data["ctl00$Main$OpenBidsOnly"], "off")
        with self.assertRaises(ValueError):
            connector.search_form(html, TylerMunisVssQuery())
        with self.assertRaises(TylerMunisVssError):
            form_state(fixture("tyler_vss_missing_state.html"))
        missing_event = html.replace('name="__EVENTVALIDATION"', 'name="removed"')
        with self.assertRaises(TylerMunisVssError):
            form_state(missing_event, require_event_validation=True)

    def test_live_control_names_grid_rows_and_page_events(self):
        connector = TylerMunisVssConnector(transport=FakeTransport([]))
        data = connector.search_form(
            fixture("tyler_vss_live_search.html"),
            TylerMunisVssQuery(keywords=("safety",), bid_type="All"),
        )
        self.assertEqual(
            data[
                "ctl00$ctl00$PrimaryPlaceHolder$ContentPlaceHolderMain$BidTypeDropBox"
            ],
            "All",
        )
        page = parse_page(fixture("tyler_vss_live_results.html"))
        self.assertEqual(len(page.rows), 1)
        self.assertEqual(page.rows[0]["bid_number"], "RFP-FIXTURE-100")
        self.assertEqual(page.rows[0]["title"], "Fixture public safety equipment")
        self.assertEqual(page.page_events[1][1], "page:11-20:1")

    async def test_live_detail_contacts_vendor_and_document_contract(self):
        results = fixture("tyler_vss_live_results.html")
        results_url = SUMMIT.url(SUMMIT.results_path)
        redirect = reply(
            "", results_url, 302, {"location": SUMMIT.detail_path, "content-type": "text/html"}
        )
        detail_url = SUMMIT.url(SUMMIT.detail_path)
        connector = TylerMunisVssConnector(
            transport=FakeTransport(
                [redirect, reply(fixture("tyler_vss_live_detail.html"), detail_url)]
            )
        )
        fields, docs = await connector.detail(results, "RFP-FIXTURE-100")
        self.assertIn("casey@example.invalid", fields["contacts"])
        self.assertEqual(fields["vendor"], "Example Public Vendor LLC")
        self.assertEqual(docs[0].filename, "Fixture Addendum.pdf")
        self.assertEqual(docs[0].mime_type, "application/pdf")
        self.assertIn("token=REDACTED", docs[0].raw_metadata["retrieval_url"])

    def test_result_and_detail_parsing(self):
        page = parse_page(fixture("tyler_vss_results_1.html"))
        self.assertEqual(page.next_event, ("grid", "Page$Next"))
        item = TylerMunisVssConnector(transport=FakeTransport([])).normalize(page.rows[0])
        self.assertEqual(item.solicitation_number, "RFP-100")
        self.assertEqual(item.source.source_id, "oh-summit-county-tyler-munis-vss:RFP-100")
        self.assertEqual(item.raw_payload["detail_navigation"]["target"], "grid$ctl02$View")

    async def test_search_redirect_pagination_fresh_state_dedup_and_limit(self):
        search_url = SUMMIT.url(SUMMIT.search_path)
        results_url = SUMMIT.url(SUMMIT.results_path)
        transport = FakeTransport(
            [
                reply(fixture("tyler_vss_search.html"), search_url),
                reply(
                    "",
                    search_url,
                    302,
                    {"location": SUMMIT.results_path, "content-type": "text/html"},
                ),
                reply(fixture("tyler_vss_results_1.html"), results_url),
                reply(fixture("tyler_vss_results_2.html"), results_url),
            ]
        )
        found = [
            x
            async for x in TylerMunisVssConnector(transport=transport).discover(
                TylerMunisVssQuery(keywords=("public",), limit=10)
            )
        ]
        self.assertEqual([x.solicitation_number for x in found], ["RFP-100", "IFB-200"])
        self.assertEqual(transport.calls[-1][2]["data"]["__VIEWSTATE"], "TEST_VIEWSTATE_PAGE_1")
        self.assertEqual(transport.calls[-1][2]["data"]["__EVENTARGUMENT"], "Page$Next")
        self.assertTrue(all(call[0] in {"GET", "POST"} for call in transport.calls))

    async def test_repeated_page_empty_and_result_bound(self):
        url = SUMMIT.url(SUMMIT.search_path)
        results = SUMMIT.url(SUMMIT.results_path)

        async def run(pages, limit=10):
            transport = FakeTransport(
                [reply(fixture("tyler_vss_search.html"), url), reply(pages[0], results)]
                + [reply(x, results) for x in pages[1:]]
            )
            return [
                x
                async for x in TylerMunisVssConnector(transport=transport).discover(
                    TylerMunisVssQuery(keywords=("x",), limit=limit)
                )
            ], transport

        found, transport = await run(
            [fixture("tyler_vss_results_1.html"), fixture("tyler_vss_results_1.html")]
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(len(transport.calls), 3)
        found, _ = await run([fixture("tyler_vss_empty.html")])
        self.assertEqual(found, [])
        found, _ = await run([fixture("tyler_vss_results_1.html")], 1)
        self.assertEqual(len(found), 1)

    async def test_detail_documents_redaction_identity_and_reacquisition(self):
        results = fixture("tyler_vss_results_1.html")
        url = SUMMIT.url(SUMMIT.results_path)
        redirect = reply(
            "", url, 302, {"location": SUMMIT.detail_path, "content-type": "text/html"}
        )
        detail_url = SUMMIT.url(SUMMIT.detail_path)
        transport = FakeTransport([redirect, reply(fixture("tyler_vss_detail.html"), detail_url)])
        fields, docs = await TylerMunisVssConnector(transport=transport).detail(results, "RFP-100")
        self.assertEqual(fields["department"], "Engineering")
        self.assertEqual([d.category for d in docs], ["attachment", "addendum"])
        self.assertEqual(
            [d.mime_type for d in docs],
            [
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ],
        )
        self.assertNotIn("TEST_DOCUMENT_TOKEN", str(docs[0].raw_metadata))
        self.assertIn("REDACTED", docs[0].raw_metadata["retrieval_url"])
        self.assertNotIn("token", docs[0].source_document_id)
        transport = FakeTransport([redirect, reply(fixture("tyler_vss_detail.html"), detail_url)])
        fresh = await TylerMunisVssConnector(transport=transport).reacquire_document_url(
            results, "RFP-100", docs[0].source_document_id
        )
        self.assertIn("DocumentViewer.ashx", fresh)

    def test_login_cross_host_non_html_and_unexpected_detection(self):
        connector = TylerMunisVssConnector(transport=FakeTransport([]))
        url = SUMMIT.url(SUMMIT.search_path)
        with self.assertRaises(TylerMunisVssAccessError):
            connector._validate_response(reply(fixture("tyler_vss_login.html"), url), "anything")
        with self.assertRaises(TylerMunisVssAccessError):
            connector._validate_response(
                reply("", url, 302, {"location": "https://identity.example/login"}), "x"
            )
        with self.assertRaises(TylerMunisVssError):
            connector._validate_response(
                reply("pdf", url, headers={"content-type": "application/pdf"}), "x"
            )
        with self.assertRaises(TylerMunisVssError):
            connector._validate_response(
                reply(fixture("tyler_vss_unexpected.html"), url), "bid-results"
            )
        self.assertEqual(
            redact_url("https://x.test/a?id=1&token=a&hash=b"),
            "https://x.test/a?id=1&token=REDACTED&hash=REDACTED",
        )

    async def test_retries_health_and_client_ownership(self):
        profile = replace(SUMMIT, retry_count=1, backoff_seconds=0, jitter_seconds=0)
        url = profile.url(profile.search_path)
        transport = FakeTransport(
            [reply("busy", url, 503), reply(fixture("tyler_vss_search.html"), url)]
        )
        connector = TylerMunisVssConnector(profile, transport)
        response = await connector._request("get", url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(connector.health_snapshot()["consecutive_failures"], 0)
        await connector.aclose()
        self.assertFalse(transport.closed)
        owned = TylerMunisVssConnector()
        await owned.aclose()
        self.assertTrue(owned._client.is_closed)

    def test_fixtures_are_synthetic_and_no_har(self):
        paths = list(FIXTURES.glob("tyler_vss*"))
        self.assertGreaterEqual(len(paths), 9)
        self.assertFalse(list(FIXTURES.glob("*.har")))
        for path in paths:
            text = path.read_text()
            self.assertNotIn("Cookie:", text)
            self.assertNotIn("Authorization:", text)
