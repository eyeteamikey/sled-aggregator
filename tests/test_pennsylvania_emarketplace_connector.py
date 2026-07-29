import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx

from sled_aggregator.connectors.pennsylvania_emarketplace import (
    PennsylvaniaAccessError,
    PennsylvaniaAccessState,
    PennsylvaniaAvailabilityError,
    PennsylvaniaEMarketplaceConnector,
    PennsylvaniaEMarketplaceQuery,
)
from sled_aggregator.connectors.registry import ConnectorRegistry, connector_registry

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = (FIXTURES / "pennsylvania_emarketplace_search.html").read_text()
DETAIL = (FIXTURES / "pennsylvania_emarketplace_detail.html").read_text()
UPCOMING = (FIXTURES / "pennsylvania_emarketplace_upcoming.html").read_text()
LANDING = (
    '<html><form action="Search.aspx"><input type="hidden" name="__VIEWSTATE" '
    'value="SANITIZED"></form></html>'
)
EMPTY = "<html><body>No matching records</body></html>"


def reply(body, status=200, **headers):
    return status, body, headers


class FakeTransport:
    def __init__(self, responses):
        self.responses, self.calls, self.closed = list(responses), [], False

    async def get(self, url, *, params=None):
        return self._take("GET", url, params)

    async def post(self, url, *, data):
        return self._take("POST", url, data)

    def _take(self, method, url, data):
        self.calls.append((method, url, dict(data or {})))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body, headers = item
        return httpx.Response(
            status,
            text=body,
            headers={"content-type": "text/html", **headers},
            request=httpx.Request(method, url),
        )

    async def aclose(self):
        self.closed = True


async def collect(connector, query=None):
    return [
        x
        async for x in connector.discover(
            query or PennsylvaniaEMarketplaceQuery(include_details=False)
        )
    ]


class PennsylvaniaConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_hidden_state_filters_current_and_normalization(self):
        transport = FakeTransport([reply(LANDING), reply(SEARCH)])
        q = PennsylvaniaEMarketplaceQuery(
            keyword="network",
            solicitation_number="6100054321",
            agency="DGS",
            county="Allegheny",
            statewide=True,
            multiple_counties=True,
            solicitation_type="RFP",
            advertisement_types=("Service", "Materials"),
            small_business_only=True,
            sdb_vbe_goal_only=True,
            bid_open_date="07/16/2026",
            posted_since="05/01/2026",
            page_size=25,
            include_details=False,
        )
        items = await collect(PennsylvaniaEMarketplaceConnector(transport=transport), q)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source.source_id, "sid:321")
        self.assertEqual(first.solicitation_number, "6100054321")
        self.assertEqual(first.status.value, "open")
        self.assertEqual(first.due_at.utcoffset(), timedelta(hours=-4))
        form = transport.calls[1][2]
        self.assertEqual(form["__VIEWSTATE"], "SANITIZED")
        self.assertEqual(form["ctl00$MainContent$txtSolicitationNumber"], "6100054321")
        self.assertNotIn("SANITIZED_FIXTURE_STATE", repr(first.raw_payload))

    async def test_detail_documents_dates_external_systems_and_provenance(self):
        transport = FakeTransport([reply(LANDING), reply(SEARCH), reply(DETAIL), reply(DETAIL)])
        items = await collect(
            PennsylvaniaEMarketplaceConnector(transport=transport),
            PennsylvaniaEMarketplaceQuery(include_details=True),
        )
        first = items[0]
        docs = first.raw_payload["document_links"]
        self.assertEqual(first.description, "Managed network services")
        self.assertEqual(first.categories[:2], ["RFP", "Service & Materials"])
        self.assertEqual(first.due_at.hour, 15)
        self.assertEqual(first.raw_payload["opening_time"], "10:00 AM")
        self.assertTrue(
            any(
                d["document_category"] == "addendum" and d["addendum_or_version"] == "2"
                for d in docs
            )
        )
        self.assertTrue(any(d["access_state"] == "supplier_portal_required" for d in docs))
        self.assertTrue(any(d["classification"] == "external_system" for d in docs))
        self.assertTrue(any(d["document_category"] == "tabulation" for d in docs))
        self.assertFalse(any("winner" in d for d in docs))
        self.assertIn("date_authority_note", first.raw_payload["pennsylvania_emarketplace"])

    async def test_archived_dedup_repeated_pages_and_limits(self):
        transport = FakeTransport([reply(LANDING), reply(SEARCH), reply(SEARCH)])
        q = PennsylvaniaEMarketplaceQuery(
            include_current=False,
            include_archived=True,
            include_details=False,
            page_size=2,
            max_pages=8,
            result_limit=1,
        )
        items = await collect(PennsylvaniaEMarketplaceConnector(transport=transport), q)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(
            items[0].raw_payload["pennsylvania_emarketplace"]["search_lane"], "archived"
        )

    async def test_upcoming_is_forecast_without_deadline(self):
        transport = FakeTransport([reply(LANDING), reply(UPCOMING)])
        q = PennsylvaniaEMarketplaceQuery(
            include_current=False, include_upcoming=True, include_details=False
        )
        item = (await collect(PennsylvaniaEMarketplaceConnector(transport=transport), q))[0]
        self.assertEqual(item.source.source_id, "upcoming:88")
        self.assertEqual(item.status.value, "forecast")
        self.assertIsNone(item.due_at)
        self.assertEqual(item.raw_payload["record_type"], "upcoming_procurement")

    async def test_dst_missing_time_malformed_date_statuses_and_identity(self):
        parse = PennsylvaniaEMarketplaceConnector._datetime
        self.assertEqual(parse("01/15/2026", "03:00 PM").utcoffset(), timedelta(hours=-5))
        self.assertEqual(parse("07/15/2026", "03:00 PM").utcoffset(), timedelta(hours=-4))
        self.assertIsNone(parse("07/15/2026"))
        self.assertIsNone(parse("bad", "also bad"))
        status = PennsylvaniaEMarketplaceConnector._status
        expected = {
            "Created": "unknown",
            "Open": "open",
            "Extended": "open",
            "Amended": "open",
            "Closed": "closed",
            "Cancelled": "cancelled",
            "Awarded": "awarded",
            "New State": "unknown",
        }
        for source, canonical in expected.items():
            self.assertEqual(status(source).value, canonical)

    async def test_access_false_success_and_invalid_postback_refresh(self):
        cases = (
            ("Supplier Login user name and password", PennsylvaniaAccessState.LOGIN_REQUIRED),
            (
                "Supplier Registration create an account",
                PennsylvaniaAccessState.REGISTRATION_REQUIRED,
            ),
            ("Enter verification code", PennsylvaniaAccessState.MFA_REQUIRED),
            ("reCAPTCHA", PennsylvaniaAccessState.CAPTCHA),
            ("Scheduled maintenance", PennsylvaniaAccessState.MAINTENANCE),
            ("Access denied", PennsylvaniaAccessState.RESTRICTED),
            ("<title>Error</title>", PennsylvaniaAccessState.MALFORMED_RESPONSE),
        )
        for body, state in cases:
            with self.subTest(state=state):
                c = PennsylvaniaEMarketplaceConnector(
                    transport=FakeTransport([reply(body)]), max_retries=0
                )
                with self.assertRaises(PennsylvaniaAccessError):
                    await collect(c)
                self.assertEqual(c.health.access_state, state)
        transport = FakeTransport(
            [reply(LANDING), reply("Invalid postback"), reply(LANDING), reply(SEARCH)]
        )
        self.assertEqual(
            len(await collect(PennsylvaniaEMarketplaceConnector(transport=transport))), 2
        )

    async def test_http_retries_retry_after_connection_circuit_and_health(self):
        delays = []

        async def sleep(value):
            delays.append(value)

        transport = FakeTransport(
            [reply("busy", 429, **{"Retry-After": "2"}), reply(LANDING), reply(SEARCH)]
        )
        c = PennsylvaniaEMarketplaceConnector(transport=transport, sleep=sleep, jitter_seconds=0)
        self.assertEqual(len(await collect(c)), 2)
        self.assertGreaterEqual(delays[0], 2)
        self.assertTrue(c.health.available)
        for code in (502, 503, 504):
            with self.subTest(code=code):
                c = PennsylvaniaEMarketplaceConnector(
                    transport=FakeTransport([reply("busy", code)]), max_retries=0
                )
                with self.assertRaises(PennsylvaniaAvailabilityError):
                    await collect(c)
        c = PennsylvaniaEMarketplaceConnector(
            transport=FakeTransport([httpx.ConnectError("no")]),
            max_retries=0,
            circuit_breaker_threshold=1,
        )
        with self.assertRaises(PennsylvaniaAvailabilityError):
            await collect(c)
        self.assertTrue(c.health.circuit_open)
        with self.assertRaises(PennsylvaniaAvailabilityError):
            await collect(c)

    async def test_unsafe_url_no_results_registry_and_client_ownership(self):
        self.assertIsNone(
            PennsylvaniaEMarketplaceConnector._safe_url(
                "javascript:alert(1)", "https://example.com"
            )
        )
        self.assertEqual(
            await collect(
                PennsylvaniaEMarketplaceConnector(
                    transport=FakeTransport([reply(LANDING), reply(EMPTY)])
                )
            ),
            [],
        )
        for key in (
            "pennsylvania/emarketplace",
            "pa-emarketplace",
            "pennsylvania-emarketplace",
            "pa/emarketplace",
        ):
            self.assertIs(connector_registry.get(key), PennsylvaniaEMarketplaceConnector)
        registry = ConnectorRegistry()
        registry.register(PennsylvaniaEMarketplaceConnector)
        with self.assertRaises(ValueError):
            registry.register_alias("pennsylvania/emarketplace", PennsylvaniaEMarketplaceConnector)
        injected = FakeTransport([])
        await PennsylvaniaEMarketplaceConnector(transport=injected).aclose()
        self.assertFalse(injected.closed)
        owned = FakeTransport([])
        with patch(
            "sled_aggregator.connectors.pennsylvania_emarketplace.httpx.AsyncClient",
            return_value=owned,
        ):
            connector = PennsylvaniaEMarketplaceConnector()
            await connector.aclose()
            self.assertTrue(owned.closed)

    async def test_types_file_extensions_and_safe_urls(self):
        c = PennsylvaniaEMarketplaceConnector(transport=FakeTransport([]))
        parent = "https://www.emarketplace.state.pa.us/Solicitations.aspx?SID=1"
        record = {
            "documents": [
                {"title": x, "url": f"Files/{i}.{ext}"}
                for i, (x, ext) in enumerate(
                    (
                        ("RFP", "pdf"),
                        ("Terms", "docx"),
                        ("Pricing", "xlsx"),
                        ("Data", "csv"),
                        ("Readme", "txt"),
                        ("Plans", "zip"),
                        ("Binary", "bin"),
                    )
                )
            ]
        }
        docs = c._documents(record, "sid:1", parent)
        self.assertEqual(
            {d["apparent_file_type"] for d in docs},
            {"pdf", "docx", "xlsx", "csv", "txt", "zip", "bin"},
        )
        self.assertTrue(all(d["retrieval_eligible"] for d in docs))
        self.assertEqual(len(docs), 7)


if __name__ == "__main__":
    unittest.main()
