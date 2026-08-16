import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from sled_aggregator.connectors.euna_ionwave import (
    CFB_PURCHASING,
    CLEMSON,
    FIXTURE_ONLY,
    IONWAVE_PORTALS,
    IOWA_DOT,
    MT_SOURCE,
    PISD,
    PROSPER_TX,
    UM_SYSTEM,
    EunaIonWaveConnector,
    IonWaveAccessError,
    IonWaveAccessState,
    IonWaveAvailabilityError,
    IonWaveMigrationClassifier,
    IonWaveQuery,
)
from sled_aggregator.connectors.registry import ConnectorRegistry, connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "ionwave_event_list.html").read_text()
DETAIL = (FIXTURES / "ionwave_public_detail.html").read_text()
EMPTY = (FIXTURES / "ionwave_empty.html").read_text()
LIVE_GRID = (FIXTURES / "ionwave_live_grid.html").read_text()
LIVE_DETAIL = (FIXTURES / "ionwave_live_detail.html").read_text()


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


class IonWaveConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, portal=PISD, **kwargs):
        fake = FakeTransport(replies)
        connector = EunaIonWaveConnector(portal, transport=fake, **kwargs)
        items = [x async for x in connector.discover(query or IonWaveQuery())]
        return connector, fake, items

    async def test_presets_configuration_variants_and_routes(self):
        self.assertEqual(
            set(IONWAVE_PORTALS),
            {
                "pisd",
                "prospertx",
                "clemson",
                "umsystembids",
                "cfbpurchasing",
                "mtsource",
                "iowadotebid",
                "fixture-only",
            },
        )
        expected = [
            (PISD, "pisd.ionwave.net", "school district"),
            (PROSPER_TX, "prospertx.ionwave.net", "town"),
            (CLEMSON, "clemson.ionwave.net", "university/state agency"),
            (UM_SYSTEM, "umsystembids.ionwave.net", "university system"),
            (CFB_PURCHASING, "cfbpurchasing.ionwave.net", "school district"),
            (MT_SOURCE, "mtsource.ionwave.net", "university/state institution"),
            (IOWA_DOT, "iowadotebid.ionwave.net", "state transportation agency"),
        ]
        for portal, host, entity in expected:
            self.assertEqual((portal.portal_hostname, portal.organization_type), (host, entity))
            self.assertIn("SourcingEvents.aspx?SourceType=1", portal.embed_list_url)
            self.assertIn("PublicDetail.aspx?bidID=42&SourceType=1", portal.opportunity_url("42"))
            self.assertTrue(
                EunaIonWaveConnector(portal, transport=FakeTransport([])).health.configuration_valid
            )
        self.assertEqual(CFB_PURCHASING.platform_variant, "registration_required")
        self.assertEqual(IOWA_DOT.platform_variant, "legacy_archive_only")
        self.assertFalse(FIXTURE_ONLY.production)

    async def test_registry_canonical_aliases_and_family_separation(self):
        for alias in (
            "euna/ionwave",
            "ionwave",
            "ion-wave",
            "ionwave-technologies",
            "euna-ionwave",
            "euna-procurement-ionwave",
            "iwt",
        ):
            self.assertIs(connector_registry.get(alias), EunaIonWaveConnector)
        self.assertIsNot(connector_registry.get("euna/bonfire"), EunaIonWaveConnector)
        with self.assertRaises(KeyError):
            connector_registry.get("euna")
        registry = ConnectorRegistry()
        registry.register(EunaIonWaveConnector)
        with self.assertRaises(ValueError):
            registry.register_alias("euna/ionwave", EunaIonWaveConnector)

    async def test_discovery_detail_canonical_identity_documents_and_provenance(self):
        c, fake, items = await self.collect(
            [response(PISD.embed_list_url, LISTING), response(PISD.opportunity_url("530"), DETAIL)]
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source.source_id, "ionwave:pisd:bid:530")
        self.assertEqual(str(item.source.opportunity_url), PISD.opportunity_url("530"))
        self.assertEqual(
            (item.solicitation_number, item.raw_payload["department"]), ("RFP-26-017", "Facilities")
        )
        self.assertIn("source_provenance", item.raw_payload)
        candidates = c.document_candidates(item)
        self.assertEqual(len(candidates), 6)
        self.assertEqual(
            [x.category for x in candidates],
            ["solicitation", "other", "addendum", "other", "questions_and_answers", "award_notice"],
        )
        self.assertEqual(candidates[3].access_state, AccessState.LOGIN_REQUIRED)
        self.assertFalse(candidates[3].publicly_retrievable)
        self.assertTrue(all(method == "GET" for method, _, _ in fake.calls))
        self.assertNotIn("__VIEWSTATE", repr(fake.calls))

    async def test_local_filters_bounds_empty_json_and_alternate_route(self):
        _, fake, items = await self.collect(
            [response(PISD.embed_list_url, LISTING), response(PISD.embed_list_url, LISTING)],
            IonWaveQuery(include_details=False, keyword="controls", maximum_pages=4, page_size=2),
        )
        self.assertEqual((len(items), len(fake.calls)), (1, 2))
        _, _, exact = await self.collect(
            [response(PISD.embed_list_url, LISTING)],
            IonWaveQuery(include_details=False, bid_id="530", solicitation_number="RFP-26-017"),
        )
        self.assertEqual(len(exact), 1)
        _, _, empty = await self.collect(
            [response(PISD.embed_list_url, EMPTY)], IonWaveQuery(include_details=False)
        )
        self.assertEqual(empty, [])
        payload = (
            '{"bids":[{"solicitation_number":"IFB 9","title":"Fixture buses","status":"Open"}]}'
        )
        _, fake, fixture = await self.collect(
            [response(FIXTURE_ONLY.embed_list_url, payload, content_type="application/json")],
            IonWaveQuery(include_details=False),
            FIXTURE_ONLY,
        )
        self.assertEqual(fixture[0].source.source_id, "ionwave:fixture-public:solicitation:ifb-9")
        self.assertIn("SourcingEvents.aspx?SourceType=1", fake.calls[0][1])

    async def test_live_aspx_grid_detail_documents_and_human_boundary(self):
        connector, fake, items = await self.collect(
            [response(PISD.embed_list_url, LIVE_GRID), response(PISD.opportunity_url("42"), LIVE_DETAIL)]
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual((item.solicitation_number, item.title), ("RFP-26-042", "Fixture fleet services"))
        self.assertEqual(item.source.source_id, "ionwave:pisd:bid:42")
        documents = connector.document_candidates(item)
        self.assertEqual(len(documents), 2)
        self.assertTrue(documents[0].publicly_retrievable)
        self.assertEqual(documents[1].access_state, AccessState.LOGIN_REQUIRED)
        self.assertTrue(all(method == "GET" for method, _, _ in fake.calls))

        challenged = EunaIonWaveConnector(
            PISD,
            transport=FakeTransport(
                [response(PISD.embed_list_url, "Cloudflare challenge CAPTCHA", status=429)]
            ),
        )
        with self.assertRaises(IonWaveAccessError) as caught:
            [x async for x in challenged.discover(IonWaveQuery(include_details=False))]
        self.assertEqual(caught.exception.state, IonWaveAccessState.CAPTCHA)

    async def test_access_migration_changed_shapes_and_ssrf_safety(self):
        cases = [
            ("Supplier Login username password", IonWaveAccessState.LOGIN_REQUIRED),
            ("VendorRegistration PreliminaryInfo", IonWaveAccessState.REGISTRATION_REQUIRED),
            ("reCAPTCHA", IonWaveAccessState.CAPTCHA),
            ("scheduled maintenance", IonWaveAccessState.UNAVAILABLE),
            ('<div id="root"></div> JavaScript required', IonWaveAccessState.JAVASCRIPT_ONLY),
        ]
        for html, state in cases:
            with self.subTest(state=state):
                c = EunaIonWaveConnector(
                    PISD, transport=FakeTransport([response(PISD.embed_list_url, html)])
                )
                with self.assertRaises(IonWaveAccessError) as caught:
                    [x async for x in c.discover(IonWaveQuery(include_details=False))]
                self.assertEqual(caught.exception.state, state)
        c = EunaIonWaveConnector(PISD, transport=FakeTransport([]))
        for url in (
            "http://pisd.ionwave.net",
            "https://evil.example/x",
            "https://127.0.0.1/x",
            "https://169.254.169.254/latest",
            "javascript:alert(1)",
        ):
            self.assertIsNone(c._safe_url(url))
        deceptive = replace(
            PISD,
            portal_hostname="pisd.ionwave.net.example.com",
            approved_hosts=("pisd.ionwave.net.example.com",),
        )
        self.assertFalse(
            EunaIonWaveConnector(deceptive, transport=FakeTransport([])).health.configuration_valid
        )
        self.assertEqual(
            IonWaveMigrationClassifier.classify("We migrated to OpenGov"), "opengov/procurement"
        )
        self.assertEqual(
            IonWaveMigrationClassifier.classify("Now hosted by Bonfire"), "euna/bonfire"
        )

    async def test_resilience_circuit_and_client_ownership(self):
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        portal = replace(PISD, retry_attempts=1)
        _, fake, items = await self.collect(
            [
                response(portal.embed_list_url, "busy", 429, headers={"Retry-After": "2"}),
                response(portal.embed_list_url, LISTING),
            ],
            IonWaveQuery(include_details=False),
            portal,
            sleep=sleep,
        )
        self.assertEqual((len(items), sleeps, len(fake.calls)), (1, [2.0], 2))
        clock = [datetime(2026, 7, 30, tzinfo=UTC)]
        broken = EunaIonWaveConnector(
            replace(
                PISD, retry_attempts=0, circuit_breaker_threshold=1, circuit_breaker_cooldown=10
            ),
            transport=FakeTransport([httpx.ConnectError("down")]),
            now=lambda: clock[0],
        )
        with self.assertRaises(IonWaveAvailabilityError):
            [x async for x in broken.discover(IonWaveQuery())]
        self.assertTrue(broken.health.circuit_open)
        clock[0] += timedelta(seconds=11)
        self.assertFalse(broken.health.circuit_open)
        injected = FakeTransport([])
        await EunaIonWaveConnector(PISD, transport=injected).aclose()
        self.assertFalse(injected.closed)

    async def test_invalid_configuration_and_variants(self):
        for portal in (
            replace(PISD, tenant_slug="bad/tenant"),
            replace(PISD, portal_hostname="evil.example"),
            replace(PISD, organization_type="corporation"),
            replace(PISD, platform_variant="invented"),
        ):
            self.assertFalse(
                EunaIonWaveConnector(portal, transport=FakeTransport([])).health.configuration_valid
            )
        with self.assertRaises(IonWaveAccessError):
            [
                x
                async for x in EunaIonWaveConnector(
                    replace(PISD, enabled=False), transport=FakeTransport([])
                ).discover(IonWaveQuery())
            ]
