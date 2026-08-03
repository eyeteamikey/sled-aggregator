import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from sled_aggregator.connectors.jaggaer_sciquest import (
    GEORGIA_SOURCING,
    IOWA_IMPACS,
    JAGGAER_PORTALS,
    UTAH_U3P,
    WISCONSIN_SHOPUW,
    JaggaerAccessError,
    JaggaerAccessState,
    JaggaerAvailabilityError,
    JaggaerQuery,
    JaggaerSciQuestConnector,
)
from sled_aggregator.connectors.registry import ConnectorRegistry, connector_registry
from sled_aggregator.domain.enums import OpportunityStatus

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "jaggaer_listing.html").read_text()
DETAIL = (FIXTURES / "jaggaer_detail.html").read_text()
IOWA_LISTING = (FIXTURES / "jaggaer_iowa_listing.html").read_text()


def response(url, text, status=200, content_type="text/html", headers=None):
    return httpx.Response(
        status,
        text=text,
        headers={"content-type": content_type, **(headers or {})},
        request=httpx.Request("GET", url),
    )


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.calls, self.closed = list(replies), [], False

    async def get(self, url, *, params=None):
        self.calls.append(("GET", url, dict(params or {})))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self):
        self.closed = True


class JaggaerTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, portal=UTAH_U3P, **kwargs):
        fake = FakeTransport(replies)
        connector = JaggaerSciQuestConnector(portal, transport=fake, **kwargs)
        items = [x async for x in connector.discover(query or JaggaerQuery())]
        return connector, fake, items

    async def test_listing_detail_normalization_documents_and_provenance(self):
        detail_url = "https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=StateOfUtah&eventNumExact=U3P-26-1001&timestamp=123"
        connector, fake, items = await self.collect(
            [response(UTAH_U3P.search_url, LISTING), response(detail_url, DETAIL)]
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source.source_id, "utah/u3p:id:UT-1001")
        self.assertEqual(item.agency, "Salt Lake City Corporation")
        self.assertEqual(item.status, OpportunityStatus.OPEN)
        self.assertNotIn("timestamp", str(item.source.opportunity_url))
        self.assertEqual(len(item.raw_payload["documents"]), 5)
        self.assertEqual(item.raw_payload["documents"][-1]["access_state"], "login_required")
        self.assertEqual(item.raw_payload["jaggaer_sciquest"]["customer_org"], "StateOfUtah")
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))
        self.assertEqual(connector.health.access_state, JaggaerAccessState.PUBLIC)

    async def test_presets_and_exact_event_url(self):
        self.assertEqual(
            set(JAGGAER_PORTALS),
            {"utah/u3p", "wisconsin/shopuw", "georgia/sourcing-director", "iowa/impacs"},
        )
        for portal in (UTAH_U3P, WISCONSIN_SHOPUW, GEORGIA_SOURCING, IOWA_IMPACS):
            self.assertIn(f"CustomerOrg={portal.customer_org}", portal.bid_board_url)
        connector = JaggaerSciQuestConnector(GEORGIA_SOURCING, transport=FakeTransport([]))
        url = connector._event_url({}, "GA-100")
        self.assertIn("eventNumExact=GA-100", url)
        self.assertIn("PHX_NAV_SourcingAllOpps", url)

    async def test_iowa_profile_routes_and_normalizes_shared_contract(self):
        connector, fake, items = await self.collect(
            [response(IOWA_IMPACS.search_url, IOWA_LISTING)],
            JaggaerQuery(include_details=False),
            IOWA_IMPACS,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source.jurisdiction, "Iowa")
        self.assertEqual(items[0].source.source_id, "iowa/impacs:id:IA-2001")
        self.assertEqual(items[0].agency, "Iowa Department of Administrative Services")
        self.assertEqual(fake.calls[0][2]["CustomerOrg"], "DASIowa")
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))

    async def test_fixture_only_tenant_and_json_strategy(self):
        portal = replace(
            UTAH_U3P,
            key="test/example",
            display_name="Fixture-only test tenant",
            customer_org="FixtureTenant",
        )
        payload = (
            '{"events":[{"event_id":"9","event_number":"T-9","title":"Test event",'
            '"issuing_organization":"Example district","status":"Closed"}]}'
        )
        _, _, items = await self.collect(
            [response(portal.search_url, payload, content_type="application/json")],
            JaggaerQuery(include_details=False),
            portal,
        )
        self.assertEqual(items[0].status, OpportunityStatus.CLOSED)
        self.assertTrue(items[0].source.source_id.startswith("test/example:"))

    async def test_local_and_remote_keyword_filtering(self):
        _, _, local = await self.collect(
            [response(UTAH_U3P.search_url, LISTING)],
            JaggaerQuery(keyword="missing", include_details=False),
        )
        self.assertEqual(local, [])
        portal = replace(UTAH_U3P, remote_keyword_search=True)
        _, fake, items = await self.collect(
            [response(portal.search_url, LISTING)],
            JaggaerQuery(keyword="network", include_details=False),
            portal,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(fake.calls[0][2]["keyword"], "network")

    async def test_pagination_deduplication_and_bounds(self):
        portal = replace(UTAH_U3P, page_size=1, max_pages=5)
        _, fake, items = await self.collect(
            [response(portal.search_url, LISTING), response(portal.search_url, LISTING)],
            JaggaerQuery(include_details=False),
            portal,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(len(fake.calls), 2)
        _, _, limited = await self.collect(
            [response(portal.search_url, LISTING)],
            JaggaerQuery(include_details=False, max_pages=1, max_results=1, limit=1),
            portal,
        )
        self.assertEqual(len(limited), 1)

    async def test_empty_missing_identity_and_malformed_fields(self):
        _, _, empty = await self.collect(
            [response(UTAH_U3P.search_url, "<html>No results</html>")],
            JaggaerQuery(include_details=False),
        )
        self.assertEqual(empty, [])
        missing_id = (
            '<article data-jaggaer-event=""><span data-field="title">Title</span>'
            '<span data-field="issuing-organization">Agency</span></article>'
        )
        _, _, derived = await self.collect(
            [response(UTAH_U3P.search_url, missing_id)], JaggaerQuery(include_details=False)
        )
        self.assertIn(":derived:", derived[0].source.source_id)

    async def test_access_interstitials(self):
        cases = {
            "Supplier login username password": JaggaerAccessState.LOGIN_REQUIRED,
            "Create your supplier account": JaggaerAccessState.REGISTRATION_REQUIRED,
            "reCAPTCHA": JaggaerAccessState.CAPTCHA,
            "<app-root></app-root> JavaScript required": JaggaerAccessState.UNSUPPORTED,
        }
        for html, state in cases.items():
            with self.subTest(state=state):
                connector = JaggaerSciQuestConnector(
                    UTAH_U3P, transport=FakeTransport([response(UTAH_U3P.search_url, html)])
                )
                with self.assertRaises(JaggaerAccessError) as caught:
                    [x async for x in connector.discover(JaggaerQuery(include_details=False))]
                self.assertEqual(caught.exception.state, state)

    async def test_content_errors_and_404(self):
        for reply, state in (
            (response(UTAH_U3P.search_url, "missing", 404), JaggaerAccessState.NOT_FOUND),
            (
                response(UTAH_U3P.search_url, "binary", content_type="application/pdf"),
                JaggaerAccessState.MALFORMED,
            ),
            (
                response(UTAH_U3P.search_url, '{"wrong":1}', content_type="application/json"),
                JaggaerAccessState.MALFORMED,
            ),
        ):
            with self.subTest(state=state):
                connector = JaggaerSciQuestConnector(UTAH_U3P, transport=FakeTransport([reply]))
                with self.assertRaises(JaggaerAccessError) as caught:
                    [x async for x in connector.discover(JaggaerQuery(include_details=False))]
                self.assertEqual(caught.exception.state, state)

    async def test_retry_after_retry_exhaustion_and_success(self):
        sleeps = []
        portal = replace(UTAH_U3P, max_retries=1)
        unavailable = response(portal.search_url, "busy", 429, headers={"Retry-After": "2"})
        connector, fake, items = await self.collect(
            [unavailable, response(portal.search_url, LISTING)],
            JaggaerQuery(include_details=False),
            portal,
            sleep=lambda delay: self._record_sleep(sleeps, delay),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(sleeps, [2.0])
        connector = JaggaerSciQuestConnector(
            portal,
            transport=FakeTransport([unavailable, unavailable]),
            sleep=lambda delay: self._record_sleep([], delay),
        )
        with self.assertRaises(JaggaerAvailabilityError):
            [x async for x in connector.discover(JaggaerQuery(include_details=False))]

    async def test_http_date_retry_timeout_and_connection(self):
        now = datetime(2026, 7, 30, tzinfo=UTC)
        portal = replace(UTAH_U3P, max_retries=1)
        waits = []
        retry = response(
            portal.search_url, "busy", 503, headers={"Retry-After": "Thu, 30 Jul 2026 00:00:05 GMT"}
        )
        await self.collect(
            [retry, response(portal.search_url, LISTING)],
            JaggaerQuery(include_details=False),
            portal,
            sleep=lambda d: self._record_sleep(waits, d),
            now=lambda: now,
        )
        self.assertEqual(waits, [5.0])
        timeout = httpx.ReadTimeout("timeout")
        _, fake, items = await self.collect(
            [timeout, response(portal.search_url, LISTING)],
            JaggaerQuery(include_details=False),
            portal,
            sleep=lambda d: self._record_sleep([], d),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(len(fake.calls), 2)

    async def test_circuit_isolation_cooldown_and_reset(self):
        clock = [datetime(2026, 7, 30, tzinfo=UTC)]
        portal = replace(
            UTAH_U3P, max_retries=0, circuit_breaker_threshold=1, circuit_breaker_cooldown=10
        )
        bad = JaggaerSciQuestConnector(
            portal, transport=FakeTransport([httpx.ConnectError("down")]), now=lambda: clock[0]
        )
        with self.assertRaises(JaggaerAvailabilityError):
            [x async for x in bad.discover(JaggaerQuery())]
        self.assertTrue(bad.health.circuit_open)
        other = JaggaerSciQuestConnector(
            replace(portal, key="test/other", customer_org="Other"),
            transport=FakeTransport([response(portal.search_url, LISTING)]),
        )
        self.assertEqual(
            len([x async for x in other.discover(JaggaerQuery(include_details=False))]), 1
        )
        clock[0] += timedelta(seconds=11)
        self.assertFalse(bad.health.circuit_open)

    async def test_client_ownership_url_safety_and_registry(self):
        fake = FakeTransport([])
        connector = JaggaerSciQuestConnector(UTAH_U3P, transport=fake)
        await connector.aclose()
        self.assertFalse(fake.closed)
        self.assertIsNone(connector._safe_url("javascript:alert(1)", document=True))
        self.assertIsNone(connector._safe_url("https://127.0.0.1/file.pdf", document=True))
        self.assertIsNone(connector._safe_url("https://evil.example/file.pdf", document=True))
        self.assertIs(connector_registry.get("jaggaer/sciquest"), JaggaerSciQuestConnector)
        self.assertIs(connector_registry.get("sciquest"), JaggaerSciQuestConnector)
        registry = ConnectorRegistry()
        registry.register(JaggaerSciQuestConnector)
        with self.assertRaises(ValueError):
            registry.register(JaggaerSciQuestConnector)
        with self.assertRaises(KeyError):
            registry.get("unknown")

    async def _record_sleep(self, target, delay):
        target.append(delay)
