import json
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx

from sled_aggregator.connectors.opengov_procurement import (
    ALAMEDA_COUNTY,
    OCEAN_COUNTY,
    OPENGOV_PORTALS,
    SAN_MATEO_COUNTY,
    OpenGovAccessError,
    OpenGovAccessState,
    OpenGovAvailabilityError,
    OpenGovError,
    OpenGovProcurementConnector,
    OpenGovQuery,
)
from sled_aggregator.connectors.registry import ConnectorRegistry, connector_registry
from sled_aggregator.domain.enums import AccessState, OpportunityStatus

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


OCEAN_PAGE_1 = fixture("opengov_ocean_listing_page1.json")
OCEAN_PAGE_2 = fixture("opengov_ocean_listing_page2.json")
OCEAN_DETAIL = fixture("opengov_ocean_detail.json")
OCEAN_QUESTIONS = fixture("opengov_ocean_questions.json")
OCEAN_AWARDED = fixture("opengov_ocean_awarded_detail.json")
ALAMEDA_LISTING = fixture("opengov_alameda_listing.json")
ALAMEDA_DETAIL = fixture("opengov_alameda_detail.json")
ALAMEDA_PLANHOLDERS = fixture("opengov_alameda_planholders.json")


def response(url, payload, status=200, content_type="application/json", method="GET", headers=None):
    if isinstance(payload, (dict, list)):
        return httpx.Response(
            status,
            json=payload,
            headers={"content-type": content_type, **(headers or {})},
            request=httpx.Request(method, url),
        )
    return httpx.Response(
        status,
        text=payload,
        headers={"content-type": content_type, **(headers or {})},
        request=httpx.Request(method, url),
    )


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.closed = False

    async def get(self, url):
        self.calls.append(("GET", url, None))
        return self._next()

    async def post(self, url, *, json):
        self.calls.append(("POST", url, json))
        return self._next()

    def _next(self):
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self):
        self.closed = True


class OpenGovConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, portal=OCEAN_COUNTY, **kwargs):
        fake = FakeTransport(replies)
        connector = OpenGovProcurementConnector(portal, transport=fake, **kwargs)
        items = [item async for item in connector.discover(query or OpenGovQuery())]
        return connector, fake, items

    async def test_validated_profiles_routes_and_registry_aliases(self):
        self.assertIn("ocean-county-nj", OPENGOV_PORTALS)
        self.assertIn("alameda-county-ca", OPENGOV_PORTALS)
        self.assertIn("san-mateo-county-ca", OPENGOV_PORTALS)
        expected = (
            (OCEAN_COUNTY, "oceancounty", "America/New_York", "live_validated_2026-08-24"),
            (ALAMEDA_COUNTY, "acgov", "America/Los_Angeles", "live_validated_2026-08-24"),
            (SAN_MATEO_COUNTY, "smcgov", "America/Los_Angeles", "live_validated_2026-08-30"),
        )
        for portal, code, timezone, verification_status in expected:
            self.assertEqual(portal.tenant_slug, code)
            self.assertEqual(portal.default_timezone, timezone)
            self.assertEqual(portal.verification_status, verification_status)
            self.assertEqual(
                portal.public_projects_url,
                f"https://api.procurement.opengov.com/api/v1/government/{code}/project/public",
            )
        self.assertFalse(OCEAN_COUNTY.planholders_observed)
        self.assertTrue(ALAMEDA_COUNTY.planholders_observed)
        self.assertFalse(SAN_MATEO_COUNTY.planholders_observed)
        for alias in (
            "opengov",
            "opengov-procurement",
            "opengov/procurement",
            "procurenow",
            "procurenow/opengov",
            "opengov-procurenow",
        ):
            self.assertIs(connector_registry.get(alias), OpenGovProcurementConnector)

    async def test_shared_listing_filter_and_sort_contract_for_both_tenants(self):
        query = OpenGovQuery(
            keyword="Parking",
            statuses=("closed",),
            department_id=11400,
            include_details=False,
            sort_field="releaseProjectDate",
            sort_direction="ASC",
        )
        for portal, listing in ((OCEAN_COUNTY, {"count": 0, "rows": []}), (ALAMEDA_COUNTY, ALAMEDA_LISTING)):
            with self.subTest(tenant=portal.tenant_key):
                _, fake, _ = await self.collect(
                    [response(portal.public_projects_url, listing, method="POST")], query, portal
                )
                method, url, body = fake.calls[0]
                self.assertEqual((method, url), ("POST", portal.public_projects_url))
                self.assertNotIn("data", body)
                self.assertEqual(body["page"], 1)
                self.assertEqual(body["limit"], 10)
                self.assertEqual(body["sortField"], "releaseProjectDate")
                self.assertEqual(body["sortDirection"], "ASC")
                self.assertEqual(body["quickSearchQuery"], None)
                self.assertEqual(
                    body["filters"],
                    [
                        {"type": "title", "value": "Parking"},
                        {"type": "department_id", "value": 11400},
                        {"type": "status", "value": "closed"},
                    ],
                )

    async def test_bounded_pagination_deduplication_and_result_limit(self):
        portal = replace(OCEAN_COUNTY, page_size=2, maximum_pages=4)
        connector, fake, items = await self.collect(
            [
                response(portal.public_projects_url, OCEAN_PAGE_1, method="POST"),
                response(portal.public_projects_url, OCEAN_PAGE_2, method="POST"),
            ],
            OpenGovQuery(include_details=False, include_closed=True, limit=3),
            portal,
        )
        self.assertEqual([item.source.source_id for item in items], [
            "ocean-county-nj:project:101",
            "ocean-county-nj:project:102",
            "ocean-county-nj:project:103",
        ])
        self.assertEqual([call[2]["page"] for call in fake.calls], [1, 2])
        self.assertEqual(connector.health.consecutive_failures, 0)

    async def test_ocean_detail_contacts_amendments_questions_and_documents(self):
        listing = {"count": 1, "rows": [OCEAN_PAGE_1["rows"][0]]}
        connector, fake, items = await self.collect([
            response(OCEAN_COUNTY.public_projects_url, listing, method="POST"),
            response(OCEAN_COUNTY.project_api_url("101"), OCEAN_DETAIL),
            response(OCEAN_COUNTY.question_api_url("101"), OCEAN_QUESTIONS),
        ])
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.title, "Fictional Sidewalk Engineering")
        self.assertEqual(item.solicitation_number, "OC-2026-01")
        self.assertEqual(item.status, OpportunityStatus.OPEN)
        self.assertEqual(item.description, "Design public sidewalks.")
        self.assertEqual(item.categories, ["92517"])
        self.assertEqual(len(item.raw_payload["contacts"]), 2)
        self.assertNotIn("Hidden Procurement", str(item.raw_payload["contacts"]))
        self.assertEqual(item.raw_payload["amendments"][0]["project_id"], 101)
        self.assertEqual(len(item.raw_payload["notices"]), 1)
        self.assertTrue(item.raw_payload["questions"][0]["is_answered"])
        self.assertEqual(
            item.raw_payload["questions"][0]["comments"][0]["description"],
            "Public agency answer",
        )
        self.assertNotIn("files.example.invalid", str(item.raw_payload))
        candidates = connector.document_candidates(item)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[1].filename, "Scope of Work.pdf")
        self.assertEqual(candidates[2].category, "addendum")
        self.assertEqual(candidates[2].addendum_number, "1")
        self.assertTrue(all(x.opportunity_id == item.source.source_id for x in candidates))
        self.assertTrue(all(x.access_state == AccessState.LOGIN_REQUIRED for x in candidates))
        self.assertTrue(all(x.publicly_retrievable is False for x in candidates))
        self.assertEqual([call[0] for call in fake.calls], ["POST", "GET", "GET"])
        self.assertFalse(connector.health.document_download_supported)

    async def test_award_vendor_and_public_contact_normalization(self):
        listing = {"count": 1, "rows": [OCEAN_PAGE_1["rows"][1]]}
        _, _, items = await self.collect([
            response(OCEAN_COUNTY.public_projects_url, listing, method="POST"),
            response(OCEAN_COUNTY.project_api_url("102"), OCEAN_AWARDED),
        ], OpenGovQuery(include_closed=True, include_awarded=True))
        item = items[0]
        self.assertEqual(item.status, OpportunityStatus.AWARDED)
        self.assertEqual([v["name"] for v in item.raw_payload["vendors"]], [
            "Example Signal Products", "Example Traffic LLC",
        ])
        self.assertNotIn("vendor@example.invalid", str(item.raw_payload["vendors"]))
        self.assertEqual({x["role"] for x in item.raw_payload["contacts"]}, {
            "project_contact", "procurement_contact",
        })

    async def test_cross_tenant_same_contract_and_tenant_specific_timezone(self):
        _, fake, items = await self.collect([
            response(ALAMEDA_COUNTY.public_projects_url, ALAMEDA_LISTING, method="POST"),
            response(ALAMEDA_COUNTY.project_api_url("201"), ALAMEDA_DETAIL),
        ], portal=ALAMEDA_COUNTY)
        item = items[0]
        self.assertEqual(item.source.source_id, "alameda-county-ca:project:201")
        self.assertEqual(item.solicitation_number, "902999")
        self.assertEqual(item.raw_payload["government"]["organization"]["timezone"], "America/Los_Angeles")
        self.assertEqual(fake.calls[0][2]["filters"], [{"type": "status", "value": "open"}])
        self.assertEqual(fake.calls[0][1], ALAMEDA_COUNTY.public_projects_url)

    async def test_alameda_opt_in_planholder_vendor_normalization(self):
        detail = {**ALAMEDA_DETAIL, "showPlanholders": True}
        _, fake, items = await self.collect([
            response(ALAMEDA_COUNTY.public_projects_url, ALAMEDA_LISTING, method="POST"),
            response(ALAMEDA_COUNTY.project_api_url("201"), detail),
            response(ALAMEDA_COUNTY.planholders_api_url("201"), ALAMEDA_PLANHOLDERS),
        ], OpenGovQuery(include_planholders=True), portal=ALAMEDA_COUNTY)
        vendors = items[0].raw_payload["vendors"]
        self.assertEqual([vendor["name"] for vendor in vendors], [
            "Example Builders LLC", "Sample Plan Room",
        ])
        self.assertEqual(vendors[0]["designations"], ["Prime"])
        self.assertTrue(vendors[0]["is_proposer"])
        self.assertEqual(vendors[0]["contact"]["email"], "alex@example.invalid")
        self.assertEqual(fake.calls[-1][1], ALAMEDA_COUNTY.planholders_api_url("201"))
        self.assertEqual(items[0].raw_payload["source_provenance"]["planholders_retained"], 2)
        alameda_health = OpenGovProcurementConnector(
            ALAMEDA_COUNTY, transport=FakeTransport([])
        ).health
        self.assertTrue(alameda_health.public_vendor_discovery_supported)

        _, _, limited = await self.collect([
            response(ALAMEDA_COUNTY.public_projects_url, ALAMEDA_LISTING, method="POST"),
            response(ALAMEDA_COUNTY.project_api_url("201"), detail),
            response(ALAMEDA_COUNTY.planholders_api_url("201"), ALAMEDA_PLANHOLDERS),
        ], OpenGovQuery(include_planholders=True, maximum_planholders=1), portal=ALAMEDA_COUNTY)
        self.assertEqual(len(limited[0].raw_payload["vendors"]), 1)

        connector = OpenGovProcurementConnector(
            ALAMEDA_COUNTY,
            transport=FakeTransport([
                response(ALAMEDA_COUNTY.public_projects_url, ALAMEDA_LISTING, method="POST"),
                response(ALAMEDA_COUNTY.project_api_url("201"), detail),
                response(ALAMEDA_COUNTY.planholders_api_url("201"), {"wrong": []}),
            ]),
        )
        with self.assertRaises(OpenGovAccessError) as caught:
            [
                item
                async for item in connector.discover(
                    OpenGovQuery(include_planholders=True)
                )
            ]
        self.assertEqual(caught.exception.state, OpenGovAccessState.MALFORMED)

    async def test_dates_are_local_post_filter_not_unobserved_post_vocabulary(self):
        query = OpenGovQuery(
            include_details=False,
            released_from=date(2026, 8, 1),
            released_to=date(2026, 8, 5),
            due_from=date(2026, 9, 1),
            due_to=date(2026, 10, 1),
        )
        _, fake, items = await self.collect([
            response(OCEAN_COUNTY.public_projects_url, {"count": 1, "rows": [OCEAN_PAGE_1["rows"][0]]}, method="POST")
        ], query)
        self.assertEqual(len(items), 1)
        self.assertNotIn("date", str(fake.calls[0][2]).casefold())

    async def test_malformed_login_captcha_and_exact_post_boundary(self):
        cases = (
            (response(OCEAN_COUNTY.public_projects_url, {"wrong": []}, method="POST"), OpenGovAccessState.MALFORMED),
            (response(OCEAN_COUNTY.public_projects_url, "Sign in to continue", content_type="text/html", method="POST"), OpenGovAccessState.LOGIN_REQUIRED),
            (response(OCEAN_COUNTY.public_projects_url, "Performing security verification cf-chl-", content_type="text/html", method="POST"), OpenGovAccessState.CAPTCHA),
            (response(OCEAN_COUNTY.public_projects_url, {}, status=401, method="POST"), OpenGovAccessState.LOGIN_REQUIRED),
        )
        for reply, state in cases:
            with self.subTest(state=state):
                connector = OpenGovProcurementConnector(OCEAN_COUNTY, transport=FakeTransport([reply]))
                with self.assertRaises(OpenGovAccessError) as caught:
                    [item async for item in connector.discover(OpenGovQuery(include_details=False))]
                self.assertEqual(caught.exception.state, state)
        connector = OpenGovProcurementConnector(OCEAN_COUNTY, transport=FakeTransport([]))
        with self.assertRaises(OpenGovError):
            await connector._request_json("POST", OCEAN_COUNTY.project_api_url("101"), {"data": {}})

    async def test_unobserved_filter_and_tenant_planholder_contracts_fail_closed(self):
        cases = (
            OpenGovQuery(category_ids=(811118,), include_details=False),
            OpenGovQuery(solicitation_number="902999", include_details=False),
            OpenGovQuery(statuses=("pending",), include_details=False),
            OpenGovQuery(sort_field="title", include_details=False),
            OpenGovQuery(include_planholders=True, include_details=False),
        )
        for query in cases:
            with self.subTest(query=query):
                connector = OpenGovProcurementConnector(
                    OCEAN_COUNTY, transport=FakeTransport([])
                )
                with self.assertRaises(OpenGovAccessError) as caught:
                    [item async for item in connector.discover(query)]
                self.assertEqual(caught.exception.state, OpenGovAccessState.UNSUPPORTED_SEARCH)

    async def test_retry_timeout_circuit_breaker_and_health(self):
        sleeps = []
        portal = replace(OCEAN_COUNTY, retry_attempts=1)
        retry = response(portal.public_projects_url, "busy", 429, method="POST", headers={"Retry-After": "2"})
        connector, fake, items = await self.collect([
            retry,
            response(portal.public_projects_url, {"count": 0, "rows": []}, method="POST"),
        ], OpenGovQuery(include_details=False), portal, sleep=lambda d: self._record_sleep(sleeps, d))
        self.assertEqual(items, [])
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(connector.health.available)

        clock = [datetime(2026, 8, 24, tzinfo=UTC)]
        broken_portal = replace(portal, retry_attempts=0, circuit_breaker_threshold=1, circuit_breaker_cooldown=10)
        broken = OpenGovProcurementConnector(
            broken_portal, transport=FakeTransport([httpx.ReadTimeout("slow")]), now=lambda: clock[0]
        )
        with self.assertRaises(OpenGovAvailabilityError):
            [item async for item in broken.discover(OpenGovQuery(include_details=False))]
        self.assertTrue(broken.health.circuit_open)
        clock[0] += timedelta(seconds=11)
        self.assertFalse(broken.health.circuit_open)

    async def test_client_ownership_and_invalid_configuration(self):
        injected = FakeTransport([])
        connector = OpenGovProcurementConnector(OCEAN_COUNTY, transport=injected)
        await connector.aclose()
        self.assertFalse(injected.closed)

        owned = FakeTransport([])
        with patch("sled_aggregator.connectors.opengov_procurement.httpx.AsyncClient", return_value=owned):
            connector = OpenGovProcurementConnector(OCEAN_COUNTY)
            await connector.aclose()
        self.assertTrue(owned.closed)

        invalid = replace(OCEAN_COUNTY, organization_type="corporation")
        connector = OpenGovProcurementConnector(invalid, transport=FakeTransport([]))
        self.assertFalse(connector.health.configuration_valid)

    async def test_unsupported_sort_and_registry_duplicate_safety(self):
        connector = OpenGovProcurementConnector(OCEAN_COUNTY, transport=FakeTransport([]))
        with self.assertRaises(OpenGovAccessError) as caught:
            [item async for item in connector.discover(OpenGovQuery(sort_field="created_at"))]
        self.assertEqual(caught.exception.state, OpenGovAccessState.UNSUPPORTED_SEARCH)
        registry = ConnectorRegistry()
        registry.register(OpenGovProcurementConnector)
        with self.assertRaises(ValueError):
            registry.register(OpenGovProcurementConnector)

    async def _record_sleep(self, target, delay):
        target.append(delay)
