import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from sled_aggregator.connectors.opengov_procurement import (
    BRIDGEPORT,
    CLEVELAND,
    GALLUP,
    MOHAVE_COUNTY,
    OPENGOV_PORTALS,
    PHOENIX,
    SEATTLE,
    OpenGovAccessError,
    OpenGovAccessState,
    OpenGovAvailabilityError,
    OpenGovPortal,
    OpenGovProcurementConnector,
    OpenGovQuery,
)
from sled_aggregator.connectors.registry import ConnectorRegistry, connector_registry
from sled_aggregator.domain.enums import AccessState, OpportunityStatus

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "opengov_project_list.html").read_text()
DETAIL = (FIXTURES / "opengov_project_detail.html").read_text()
EMPTY = (FIXTURES / "opengov_empty.html").read_text()


def response(url, text, status=200, content_type="text/html", headers=None):
    return httpx.Response(status, text=text,
                          headers={"content-type": content_type, **(headers or {})},
                          request=httpx.Request("GET", url))


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


class OpenGovConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, portal=PHOENIX, **kwargs):
        fake = FakeTransport(replies)
        connector = OpenGovProcurementConnector(portal, transport=fake, **kwargs)
        items = [x async for x in connector.discover(query or OpenGovQuery())]
        return connector, fake, items

    async def test_presets_routes_configuration_and_registry_aliases(self):
        self.assertEqual(set(OPENGOV_PORTALS),
                         {"phoenix", "seattle", "cleveland", "bridgeport", "mohave-county", "gallup"})
        expected = (
            (PHOENIX, "phoenix", "America/Phoenix", "city"),
            (SEATTLE, "seattle", "America/Los_Angeles", "city"),
            (CLEVELAND, "clevelandoh", "America/New_York", "city"),
            (BRIDGEPORT, "bridgeportct", "America/New_York", "city"),
            (MOHAVE_COUNTY, "mohavecounty", "America/Phoenix", "county"),
            (GALLUP, "gallupnm", "America/Denver", "city"),
        )
        for portal, slug, timezone, kind in expected:
            self.assertEqual(portal.tenant_slug, slug)
            self.assertEqual(portal.default_timezone, timezone)
            self.assertEqual(portal.organization_type, kind)
            self.assertEqual(portal.portal_url, f"https://procurement.opengov.com/portal/{slug}")
            self.assertIn(f"/embed/{slug}/project-list", portal.embed_list_url)
        self.assertEqual(MOHAVE_COUNTY.contracts_portal_url,
                         "https://procurement.opengov.com/portal/mohavecounty/contracts")
        for alias in ("opengov", "opengov-procurement", "opengov/procurement",
                      "procurenow", "procurenow/opengov", "opengov-procurenow"):
            self.assertIs(connector_registry.get(alias), OpenGovProcurementConnector)

    async def test_listing_detail_documents_provenance_and_manifest_candidates(self):
        connector, fake, items = await self.collect([
            response(PHOENIX.embed_list_url, LISTING),
            response(PHOENIX.project_url("42001"), DETAIL),
        ])
        self.assertEqual(len(items), 1)  # closed records are opt-in
        item = items[0]
        self.assertEqual(item.source.source_id, "phoenix:project:42001")
        self.assertEqual(item.title, "Network Modernization Services")
        self.assertEqual(item.status, OpportunityStatus.OPEN)
        self.assertNotIn("timestamp", str(item.source.opportunity_url))
        self.assertEqual(item.raw_payload["department"], "Information Technology Services")
        self.assertEqual(item.raw_payload["procurement_officer"], "Alex Public")
        self.assertEqual(len(item.raw_payload["documents"]), 3)
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))
        candidates = connector.document_candidates(item)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[0].source_document_id, "doc-1")
        self.assertEqual(candidates[1].category, "addendum")
        self.assertEqual(candidates[2].access_state, AccessState.LOGIN_REQUIRED)
        self.assertFalse(candidates[2].publicly_retrievable)
        self.assertIn("source_provenance", item.raw_payload)
        self.assertEqual(connector.health.access_state, OpenGovAccessState.PUBLIC)

    async def test_fixture_only_tenant_proves_configuration_driven_json(self):
        portal = OpenGovPortal(
            "fixture-only", "fixturedistrict", "Fixture-only non-production tenant",
            "Test Territory", "TT", "school district", "Fixture District",
            production=False, verification_status="test_fixture_only",
        )
        payload = ('{"projects":[{"project_id":"T-7","title":"Bus services",'
                   '"agency":"Fixture District","status":"Awarded"}]}')
        _, _, items = await self.collect(
            [response(portal.embed_list_url, payload, content_type="application/json")],
            OpenGovQuery(include_details=False, include_awarded=True), portal,
        )
        self.assertEqual(items[0].source.source_id, "fixture-only:project:T-7")
        self.assertFalse(items[0].raw_payload["opengov_procurement"]["production_preset"])

    async def test_local_filters_exact_ids_dates_departments_status_and_order(self):
        query = OpenGovQuery(keyword="network", project_id="42001",
                             solicitation_number="RFP-26-001", statuses=("open",),
                             department="technology", released_from=date(2026, 7, 1),
                             released_to=date(2026, 7, 2), due_from=date(2026, 8, 1),
                             due_to=date(2026, 8, 31), include_details=False)
        _, _, items = await self.collect([response(PHOENIX.embed_list_url, LISTING)], query)
        self.assertEqual([x.source.source_id for x in items], ["phoenix:project:42001"])
        _, _, closed = await self.collect(
            [response(PHOENIX.embed_list_url, LISTING)],
            OpenGovQuery(include_details=False, include_closed=True))
        self.assertEqual(len(closed), 2)

    async def test_empty_is_distinct_from_malformed_and_javascript_shell(self):
        _, _, items = await self.collect([response(PHOENIX.embed_list_url, EMPTY)],
                                         OpenGovQuery(include_details=False))
        self.assertEqual(items, [])
        for html, state in (
            ("<html>unexpected changed markup</html>", OpenGovAccessState.MALFORMED),
            ('<div id="root"></div><p>JavaScript required</p>', OpenGovAccessState.JAVASCRIPT_ONLY),
            ("Supplier login username password", OpenGovAccessState.LOGIN_REQUIRED),
            ("reCAPTCHA", OpenGovAccessState.CAPTCHA),
        ):
            with self.subTest(state=state):
                connector = OpenGovProcurementConnector(
                    PHOENIX, transport=FakeTransport([response(PHOENIX.embed_list_url, html)]))
                with self.assertRaises(OpenGovAccessError) as caught:
                    [x async for x in connector.discover(OpenGovQuery(include_details=False))]
                self.assertEqual(caught.exception.state, state)

    async def test_unsupported_search_invalid_config_and_url_safety(self):
        portal = replace(PHOENIX, keyword_search_support="unsupported")
        connector = OpenGovProcurementConnector(portal, transport=FakeTransport([]))
        with self.assertRaises(OpenGovAccessError) as caught:
            [x async for x in connector.discover(OpenGovQuery(keyword="roads"))]
        self.assertEqual(caught.exception.state, OpenGovAccessState.UNSUPPORTED_SEARCH)
        self.assertIsNone(connector._safe_url("javascript:alert(1)"))
        self.assertIsNone(connector._safe_url("https://127.0.0.1/document.pdf", document=True))
        self.assertIsNone(connector._safe_url("https://evil.example/document.pdf", document=True))
        invalid = replace(PHOENIX, organization_type="corporation")
        self.assertFalse(OpenGovProcurementConnector(invalid, transport=FakeTransport([])).health.configuration_valid)

    async def test_bounded_pagination_deduplication_limit_and_get_only(self):
        portal = replace(PHOENIX, page_size=2, maximum_pages=4)
        connector, fake, items = await self.collect(
            [response(portal.embed_list_url, LISTING), response(portal.embed_list_url, LISTING)],
            OpenGovQuery(include_details=False, include_closed=True, limit=1), portal)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0][2], {"page": 1, "pageSize": 2})
        self.assertTrue(all(method == "GET" for method, _, _ in fake.calls))
        await connector.aclose()
        self.assertFalse(fake.closed)

    async def test_retry_transient_failure_and_circuit_isolation(self):
        sleeps = []
        portal = replace(PHOENIX, retry_attempts=1)
        retry = response(portal.embed_list_url, "busy", 429, headers={"Retry-After": "2"})
        _, fake, items = await self.collect(
            [retry, response(portal.embed_list_url, LISTING)],
            OpenGovQuery(include_details=False), portal,
            sleep=lambda d: self._record_sleep(sleeps, d))
        self.assertEqual(len(items), 1)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(len(fake.calls), 2)
        clock = [datetime(2026, 7, 30, tzinfo=UTC)]
        circuit_portal = replace(PHOENIX, retry_attempts=0, circuit_breaker_threshold=1,
                                 circuit_breaker_cooldown=10)
        broken = OpenGovProcurementConnector(
            circuit_portal, transport=FakeTransport([httpx.ConnectError("down")]),
            now=lambda: clock[0])
        with self.assertRaises(OpenGovAvailabilityError):
            [x async for x in broken.discover(OpenGovQuery())]
        self.assertTrue(broken.health.circuit_open)
        clock[0] += timedelta(seconds=11)
        self.assertFalse(broken.health.circuit_open)

    async def test_registry_safety_and_http_errors(self):
        registry = ConnectorRegistry()
        registry.register(OpenGovProcurementConnector)
        with self.assertRaises(ValueError):
            registry.register(OpenGovProcurementConnector)
        for reply, state in (
            (response(PHOENIX.embed_list_url, "missing", 404), OpenGovAccessState.NOT_FOUND),
            (response(PHOENIX.embed_list_url, "binary", content_type="application/pdf"), OpenGovAccessState.MALFORMED),
            (response(PHOENIX.embed_list_url, '{"wrong":1}', content_type="application/json"), OpenGovAccessState.MALFORMED),
        ):
            connector = OpenGovProcurementConnector(PHOENIX, transport=FakeTransport([reply]))
            with self.assertRaises(OpenGovAccessError) as caught:
                [x async for x in connector.discover(OpenGovQuery(include_details=False))]
            self.assertEqual(caught.exception.state, state)

    async def _record_sleep(self, target, delay):
        target.append(delay)
