import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from sled_aggregator.connectors.euna_bonfire import (
    ANACORTES,
    BEND,
    BONFIRE_PORTALS,
    CHARLOTTE,
    CNUSD,
    FAIRFAX_COUNTY,
    FCPS,
    FIXTURE_ONLY,
    FLORENCE_1,
    REGION_10,
    BonfireAccessError,
    BonfireAccessState,
    BonfireAvailabilityError,
    BonfireProcurementConnector,
    BonfireQuery,
)
from sled_aggregator.connectors.registry import ConnectorRegistry, connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "bonfire_opportunity_list.html").read_text()
DETAIL = (FIXTURES / "bonfire_opportunity_detail.html").read_text()
EMPTY = (FIXTURES / "bonfire_empty.html").read_text()


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


class BonfireConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, portal=ANACORTES, **kwargs):
        fake = FakeTransport(replies)
        connector = BonfireProcurementConnector(portal, transport=fake, **kwargs)
        return connector, fake, [x async for x in connector.discover(query or BonfireQuery())]

    async def test_presets_variants_entity_timezone_and_registry(self):
        self.assertEqual(
            set(BONFIRE_PORTALS),
            {
                "anacorteswa",
                "bendoregon",
                "fairfaxcounty",
                "fcps",
                "cnusdk12",
                "fsd1",
                "region10",
                "charlottenc",
                "fixture-only",
            },
        )
        expected = [
            (ANACORTES, "anacortes.bonfirehub.com", "city"),
            (BEND, "bendoregon.bonfirehub.com", "city"),
            (FAIRFAX_COUNTY, "fairfaxcounty.bonfirehub.com", "county"),
            (FCPS, "fcps.bonfirehub.com", "school district"),
            (CNUSD, "cnusdk12.bonfirehub.com", "school district"),
            (FLORENCE_1, "fsd1.bonfirehub.com", "school district"),
            (REGION_10, "region10.bonfirehub.com", "cooperative purchasing organization"),
            (CHARLOTTE, "charlottenc.bonfirehub.com", "city"),
        ]
        for portal, host, entity in expected:
            self.assertEqual(portal.portal_hostname, host)
            self.assertEqual(portal.organization_type, entity)
            self.assertTrue(
                BonfireProcurementConnector(
                    portal, transport=FakeTransport([])
                ).health.configuration_valid
            )
        self.assertEqual(FCPS.platform_variant, "euna_branded_bonfire")
        self.assertEqual(CHARLOTTE.verification_status, "registration_required")
        self.assertFalse(FIXTURE_ONLY.production)
        for alias in (
            "euna/bonfire",
            "bonfire",
            "bonfirehub",
            "euna-bonfire",
            "euna-procurement-bonfire",
            "bonfire-interactive",
        ):
            self.assertIs(connector_registry.get(alias), BonfireProcurementConnector)
        with self.assertRaises(KeyError):
            connector_registry.get("euna")

    async def test_discovery_detail_documents_access_and_provenance(self):
        connector, fake, items = await self.collect(
            [
                response(ANACORTES.embed_list_url, LISTING),
                response(ANACORTES.opportunity_url("BF-26001"), DETAIL),
            ]
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source.source_id, "bonfire:anacortes:opportunity:BF-26001")
        self.assertEqual(item.solicitation_number, "RFP-26-017")
        self.assertEqual(item.raw_payload["department"], "Public Works")
        self.assertIn("source_provenance", item.raw_payload)
        candidates = connector.document_candidates(item)
        self.assertEqual(len(candidates), 5)
        self.assertEqual(
            [x.category for x in candidates],
            ["solicitation", "addendum", "other", "questions_and_answers", "award_notice"],
        )
        self.assertEqual(candidates[2].access_state, AccessState.REGISTRATION_REQUIRED)
        self.assertFalse(candidates[2].publicly_retrievable)
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))

    async def test_bounded_local_search_dedup_empty_json_and_source_fallbacks(self):
        _, fake, items = await self.collect(
            [
                response(ANACORTES.embed_list_url, LISTING),
                response(ANACORTES.embed_list_url, LISTING),
            ],
            BonfireQuery(include_details=False, keyword="controls", maximum_pages=4, page_size=2),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(len(fake.calls), 2)
        _, _, empty = await self.collect(
            [response(ANACORTES.embed_list_url, EMPTY)], BonfireQuery(include_details=False)
        )
        self.assertEqual(empty, [])
        payload = '{"opportunities":[{"solicitation_number":"IFB 9","title":"Fixture buses","status":"Open"}]}'
        _, _, fixture = await self.collect(
            [response(FIXTURE_ONLY.embed_list_url, payload, content_type="application/json")],
            BonfireQuery(include_details=False),
            FIXTURE_ONLY,
        )
        self.assertEqual(fixture[0].source.source_id, "bonfire:fixture-public:solicitation:ifb-9")

    async def test_access_classification_changed_shapes_and_safety(self):
        cases = [
            ("Supplier login username password", BonfireAccessState.LOGIN_REQUIRED),
            ("Registration required", BonfireAccessState.REGISTRATION_REQUIRED),
            ("reCAPTCHA", BonfireAccessState.CAPTCHA),
            ("scheduled maintenance", BonfireAccessState.UNAVAILABLE),
            ('<div id="root"></div> JavaScript required', BonfireAccessState.JAVASCRIPT_ONLY),
        ]
        for html, state in cases:
            with self.subTest(state=state):
                c = BonfireProcurementConnector(
                    ANACORTES, transport=FakeTransport([response(ANACORTES.embed_list_url, html)])
                )
                with self.assertRaises(BonfireAccessError) as caught:
                    [x async for x in c.discover(BonfireQuery(include_details=False))]
                self.assertEqual(caught.exception.state, state)
        c = BonfireProcurementConnector(ANACORTES, transport=FakeTransport([]))
        for url in (
            "http://anacortes.bonfirehub.com",
            "https://evil.example/x",
            "https://127.0.0.1/x",
            "javascript:alert(1)",
        ):
            self.assertIsNone(c._safe_url(url))
        invalid = replace(
            ANACORTES,
            portal_hostname="anacortes.bonfirehub.com.evil.example",
            approved_hosts=("anacortes.bonfirehub.com.evil.example",),
        )
        self.assertFalse(
            BonfireProcurementConnector(
                invalid, transport=FakeTransport([])
            ).health.configuration_valid
        )

    async def test_retries_circuit_client_ownership_and_registry_collisions(self):
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        portal = replace(ANACORTES, retry_attempts=1)
        _, fake, items = await self.collect(
            [
                response(portal.embed_list_url, "busy", 429, headers={"Retry-After": "2"}),
                response(portal.embed_list_url, LISTING),
            ],
            BonfireQuery(include_details=False),
            portal,
            sleep=sleep,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(len(fake.calls), 2)
        clock = [datetime(2026, 7, 30, tzinfo=UTC)]
        broken = BonfireProcurementConnector(
            replace(
                ANACORTES,
                retry_attempts=0,
                circuit_breaker_threshold=1,
                circuit_breaker_cooldown=10,
            ),
            transport=FakeTransport([httpx.ConnectError("down")]),
            now=lambda: clock[0],
        )
        with self.assertRaises(BonfireAvailabilityError):
            [x async for x in broken.discover(BonfireQuery())]
        self.assertTrue(broken.health.circuit_open)
        clock[0] += timedelta(seconds=11)
        self.assertFalse(broken.health.circuit_open)
        injected = FakeTransport([])
        await BonfireProcurementConnector(ANACORTES, transport=injected).aclose()
        self.assertFalse(injected.closed)
        registry = ConnectorRegistry()
        registry.register(BonfireProcurementConnector)
        with self.assertRaises(ValueError):
            registry.register_alias("euna/bonfire", BonfireProcurementConnector)
