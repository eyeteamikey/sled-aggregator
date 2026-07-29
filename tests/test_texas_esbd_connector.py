import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx

from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.connectors.texas_esbd import (
    ESBDAccessError,
    ESBDAccessState,
    ESBDAvailabilityError,
    ESBDError,
    ESBDQuery,
    TexasESBDConnector,
)

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS = (FIXTURES / "texas_esbd_results.html").read_text()
DETAIL = (FIXTURES / "texas_esbd_detail.html").read_text()
EMPTY = "<html><body>No matching solicitations</body></html>"


def response(body: str, status: int = 200, **headers: str):
    return status, body, headers


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    async def get(self, url, *, params):
        self.calls.append((url, dict(params)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body, headers = item
        return httpx.Response(
            status,
            text=body,
            headers={"content-type": "text/html", **headers},
            request=httpx.Request("GET", url, params=params),
        )

    async def aclose(self):
        self.closed = True


async def collect(connector, query=None):
    return [item async for item in connector.discover(query or ESBDQuery())]


def record(identifier="77", solicitation="S-1", agency="305", status="Posted", due=""):
    return f'''<article data-esbd-record="{identifier}" data-esbd-id="{identifier}"
      data-agency-number="{agency}" data-solicitation-id="{solicitation}">
      <h2 data-field="title">Title {identifier}</h2>
      <span data-field="agency-name">Agency {agency}</span>
      <span data-field="status">{status}</span><span data-field="response-due">{due}</span>
      <a href="/esbd/solicitation/{identifier}">Details</a></article>'''


class TexasESBDConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_statuses_fields_timezone_and_documents(self):
        connector = TexasESBDConnector(
            transport=FakeTransport([response(RESULTS), response(DETAIL)]),
            fetch_details=True,
            max_details=1,
        )
        items = await collect(connector, ESBDQuery(limit=10))
        self.assertEqual(len(items), 6)
        by_id = {item.solicitation_number: item for item in items}
        posted = by_id["RFP-26-001"]
        self.assertEqual(posted.source.source_id, "esbd:1001")
        self.assertEqual(posted.raw_payload["texas_esbd"]["agency_number"], "305")
        self.assertEqual(posted.due_at.utcoffset(), timedelta(hours=-6))
        self.assertEqual(by_id["PRE-1"].due_at.utcoffset(), timedelta(hours=-5))
        self.assertEqual(by_id["PRE-1"].status.value, "forecast")
        self.assertEqual(by_id["IFB-9"].status.value, "open")
        self.assertEqual(by_id["RFP-OLD"].status.value, "awarded")
        self.assertEqual(by_id["NOTICE-1"].status.value, "unknown")
        self.assertEqual(by_id["CANCEL-1"].status.value, "cancelled")
        self.assertEqual(posted.raw_payload["estimated_value"], "$450,000")
        self.assertEqual(posted.categories, ["204-64", "920-45"])
        docs = posted.raw_payload["document_links"]
        self.assertEqual(len(docs), 2)
        self.assertIn("h=ExactHash", docs[0]["source_url"])
        self.assertTrue(docs[0]["internal_esbd_media"])
        self.assertEqual(docs[1]["document_category"], "addendum")
        award_doc = by_id["RFP-OLD"].raw_payload["document_links"][0]
        self.assertEqual(award_doc["access_state"], "external_account_required")

    async def test_search_parameters_and_nigp_normalization(self):
        transport = FakeTransport([response(EMPTY)])
        query = ESBDQuery(
            keywords=("network",),
            solicitation_id="RFP-1",
            agency_name="Facilities",
            agency_number="LOCAL-A7",
            status="Awarded",
            nigp_class="204-00",
            nigp_item="204-64",
            posted_from="01/01/2026",
            posted_to="01/31/2026",
            response_from="02/01/2026",
            response_to="02/28/2026",
        )
        await collect(TexasESBDConnector(transport=transport, fetch_details=False), query)
        params = transport.calls[0][1]
        self.assertEqual(params["keyword"], "network")
        self.assertEqual(params["solicitationId"], "RFP-1")
        self.assertEqual(params["agencyName"], "Facilities")
        self.assertEqual(params["agencyNumber"], "LOCAL-A7")
        self.assertEqual(params["nigpClass"], "20400")
        self.assertEqual(params["nigpItem"], "20464")
        self.assertEqual(TexasESBDConnector.normalize_nigp(" 92-0.45 "), "92045")

    async def test_pagination_deduplication_limits_and_repeated_page(self):
        page = record("1") + record("2")
        transport = FakeTransport([response(page), response(page)])
        items = await collect(
            TexasESBDConnector(transport=transport, page_size=2, max_pages=8, fetch_details=False),
            ESBDQuery(limit=20),
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(len(transport.calls), 2)
        duplicate = record("1") + record("3")
        transport = FakeTransport([response(page), response(duplicate), response(EMPTY)])
        items = await collect(
            TexasESBDConnector(
                transport=transport, page_size=2, max_pages=3, max_results=2, fetch_details=False
            ),
            ESBDQuery(limit=9),
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(len({item.source.source_id for item in items}), 2)

    async def test_duplicate_solicitations_agencies_internal_identity_and_reconciliation(self):
        body = record("10", "SHARED", "305") + record("11", "SHARED", "601")
        items = await collect(
            TexasESBDConnector(transport=FakeTransport([response(body)]), fetch_details=False)
        )
        self.assertEqual({item.source.source_id for item in items}, {"esbd:10", "esbd:11"})
        posted = record("55", "SAME", "305", "Posted") + record("55", "SAME", "305", "Awarded")
        items = await collect(
            TexasESBDConnector(transport=FakeTransport([response(posted)]), fetch_details=False)
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status.value, "awarded")

    async def test_fallback_composite_identity_missing_identity_and_missing_optional_time(self):
        composite = """<article data-esbd-record="" data-agency-number="305"
        data-solicitation-id="A-1">
        <h2 data-field="title">Fallback</h2><span data-field="agency-name">Agency</span>
        <span data-field="response-due">02/15/2026</span><a href="/esbd">Details</a></article>"""
        item = (
            await collect(
                TexasESBDConnector(
                    transport=FakeTransport([response(composite)]), fetch_details=False
                )
            )
        )[0]
        self.assertEqual(item.source.source_id, "agency:305:A-1")
        self.assertIsNone(item.due_at)
        self.assertFalse(item.raw_payload["texas_esbd"]["response_time_inferred"])
        invalid = """<article data-esbd-record=""><h2 data-field="title">No ID</h2>
        <span data-field="agency-name">Agency</span></article>"""
        connector = TexasESBDConnector(
            transport=FakeTransport([response(invalid)]), fetch_details=False
        )
        self.assertEqual(await collect(connector), [])
        self.assertEqual(connector.health.skipped_records, 1)

    async def test_unexpected_shape_malformed_success_and_access_false_success(self):
        for body, state in (
            ("Supplier Login email address and password", ESBDAccessState.LOGIN_REQUIRED),
            ("reCAPTCHA bot challenge", ESBDAccessState.CAPTCHA),
            ("Scheduled maintenance", ESBDAccessState.MAINTENANCE),
        ):
            connector = TexasESBDConnector(
                transport=FakeTransport([response(body)]), fetch_details=False
            )
            with self.assertRaises(ESBDAccessError):
                await collect(connector)
            self.assertEqual(connector.health.access_state, state)
        with self.assertRaises(ESBDError):
            await collect(
                TexasESBDConnector(
                    transport=FakeTransport([response("<html>generic</html>")]), fetch_details=False
                )
            )
        with self.assertRaises(ESBDError):
            await collect(
                TexasESBDConnector(
                    transport=FakeTransport(
                        [response("{}", **{"content-type": "application/json"})]
                    ),
                    fetch_details=False,
                )
            )

    async def test_stable_403_not_retried(self):
        transport = FakeTransport([response("Forbidden", 403), response(RESULTS)])
        connector = TexasESBDConnector(transport=transport, max_retries=3, fetch_details=False)
        with self.assertRaises(ESBDAccessError):
            await collect(connector)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(connector.health.last_status_code, 403)

    async def test_all_transient_statuses_connection_retry_and_retry_after(self):
        for status in (429, 502, 503, 504):
            sleeps = []

            async def sleep(delay, target=sleeps):
                target.append(delay)

            transport = FakeTransport(
                [response("busy", status, **{"Retry-After": "2"}), response(EMPTY)]
            )
            await collect(
                TexasESBDConnector(
                    transport=transport,
                    max_retries=1,
                    sleep=sleep,
                    jitter_seconds=0,
                    fetch_details=False,
                )
            )
            self.assertEqual(sleeps, [2])
        now = datetime(2026, 1, 1, tzinfo=UTC)
        header = "Thu, 01 Jan 2026 00:00:04 GMT"
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        transport = FakeTransport(
            [response("busy", 503, **{"Retry-After": header}), response(EMPTY)]
        )
        await collect(
            TexasESBDConnector(
                transport=transport,
                max_retries=1,
                sleep=sleep,
                now=lambda: now,
                jitter_seconds=0,
                fetch_details=False,
            )
        )
        self.assertEqual(sleeps, [4])
        transport = FakeTransport([ConnectionError(), response(EMPTY)])
        await collect(
            TexasESBDConnector(transport=transport, max_retries=1, sleep=sleep, fetch_details=False)
        )
        self.assertEqual(len(transport.calls), 2)

    async def test_retry_exhaustion_circuit_cooldown_health_and_reset(self):
        now = datetime(2026, 1, 1, tzinfo=UTC)
        transport = FakeTransport([response("busy", 503), response(EMPTY)])
        connector = TexasESBDConnector(
            transport=transport,
            max_retries=0,
            circuit_breaker_threshold=1,
            circuit_breaker_cooldown=2,
            now=lambda: now,
            fetch_details=False,
        )
        with self.assertRaises(ESBDAvailabilityError):
            await collect(connector)
        self.assertTrue(connector.health.circuit_open)
        with self.assertRaises(ESBDAvailabilityError):
            await collect(connector)
        now += timedelta(seconds=3)
        self.assertEqual(await collect(connector), [])
        self.assertEqual(connector.health.consecutive_failures, 0)
        self.assertTrue(connector.health.available)

    async def test_transport_ownership_registry_and_visibility_policy(self):
        for key in ("texas/esbd", "esbd", "texas-esbd", "texas-smartbuy-esbd"):
            self.assertIs(connector_registry.get(key), TexasESBDConnector)
        with self.assertRaises(KeyError):
            connector_registry.get("texas-smartbuy")
        transport = FakeTransport([])
        await TexasESBDConnector(transport=transport).aclose()
        self.assertFalse(transport.closed)
        fake_owned = FakeTransport([])
        with patch(
            "sled_aggregator.connectors.texas_esbd.httpx.AsyncClient", return_value=fake_owned
        ):
            owned = TexasESBDConnector()
            await owned.aclose()
        self.assertTrue(fake_owned.closed)
        item = (
            await collect(
                TexasESBDConnector(
                    transport=FakeTransport([response(record())]), fetch_details=False
                )
            )
        )[0]
        self.assertEqual(
            item.raw_payload["texas_esbd"]["visibility_gap_policy"],
            "retain_last_known; absence_is_not_deletion",
        )


if __name__ == "__main__":
    unittest.main()
