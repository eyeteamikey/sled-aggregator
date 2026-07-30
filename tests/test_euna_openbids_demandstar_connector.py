import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from sled_aggregator.connectors.euna_bonfire import BonfireProcurementConnector
from sled_aggregator.connectors.euna_ionwave import EunaIonWaveConnector
from sled_aggregator.connectors.euna_openbids_demandstar import (
    FIXTURE_PROFILE,
    DemandStarAccessError,
    DemandStarAccessState,
    DemandStarError,
    DemandStarQuery,
    EunaOpenBidsDemandStarConnector,
    detect_access_boundary,
    parse_page,
)
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "demandstar_listing.html").read_text()
DETAIL = (FIXTURES / "demandstar_detail.html").read_text()


def response(url, text, status=200, headers=None):
    return httpx.Response(
        status,
        text=text,
        headers={"content-type": "text/html", **(headers or {})},
        request=httpx.Request("GET", url),
    )


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.closed = False

    async def get(self, url, *, params=None):
        self.calls.append((url, params))
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self):
        self.closed = True


class DemandStarTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, profile=FIXTURE_PROFILE, **kwargs):
        transport = FakeTransport(replies)
        connector = EunaOpenBidsDemandStarConnector(profile, transport=transport, **kwargs)
        return (
            connector,
            transport,
            [x async for x in connector.discover(query or DemandStarQuery())],
        )

    async def test_registry_aliases_are_unambiguous_and_separate(self):
        for alias in (
            "euna/openbids-demandstar",
            "demandstar",
            "demand-star",
            "euna-demandstar",
            "euna-openbids",
            "openbids",
            "euna/openbids",
            "euna-procurement-demandstar",
        ):
            self.assertIs(connector_registry.get(alias), EunaOpenBidsDemandStarConnector)
        self.assertIs(connector_registry.get("euna/bonfire"), BonfireProcurementConnector)
        self.assertIs(connector_registry.get("euna/ionwave"), EunaIonWaveConnector)
        for ambiguous in ("euna", "euna-procurement", "procurement"):
            with self.assertRaises(KeyError):
                connector_registry.get(ambiguous)

    async def test_discovery_detail_identity_provenance_and_documents(self):
        c, t, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, LISTING),
                response(
                    FIXTURE_PROFILE.detail_url("aabbccdd-0000-1111-2222-abcdef123456"), DETAIL
                ),
            ]
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(
            item.source.source_id,
            "euna/openbids-demandstar:fixture-county:aabbccdd-0000-1111-2222-abcdef123456",
        )
        self.assertEqual(item.solicitation_number, "RFP-26-19")
        self.assertIn("source_provenance", item.raw_payload)
        docs = c.document_candidates(item)
        self.assertEqual(len(docs), 6)
        self.assertEqual(
            [x.category for x in docs],
            [
                "solicitation",
                "addendum",
                "questions_and_answers",
                "other",
                "bid_tabulation",
                "award_notice",
            ],
        )
        self.assertEqual(docs[2].access_state, AccessState.REGISTRATION_REQUIRED)
        self.assertEqual(docs[3].access_state, AccessState.PAYMENT_REQUIRED)
        self.assertFalse(docs[2].publicly_retrievable)
        self.assertTrue(docs[0].publicly_retrievable)
        self.assertTrue(all(call[0].startswith("https://") for call in t.calls))

    async def test_bounds_filters_duplicates_empty_and_changed_markup(self):
        _, t, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, LISTING),
                response(FIXTURE_PROFILE.discovery_url, LISTING),
            ],
            DemandStarQuery(include_details=False, keywords=("radio",), maximum_pages=4),
        )
        self.assertEqual((len(items), len(t.calls)), (1, 1))
        _, _, filtered = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            DemandStarQuery(include_details=False, status="closed"),
        )
        self.assertEqual(filtered, [])
        empty = "<main data-openbids-list>No open opportunities</main>"
        _, _, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, empty)], DemandStarQuery(include_details=False)
        )
        self.assertEqual(items, [])
        with self.assertRaises(DemandStarAccessError) as caught:
            await self.collect(
                [response(FIXTURE_PROFILE.discovery_url, "<div>redesigned</div>")],
                DemandStarQuery(include_details=False),
            )
        self.assertEqual(caught.exception.state, DemandStarAccessState.CHANGED_MARKUP)

    async def test_access_boundaries_and_no_retry(self):
        cases = (
            ("Register to download", DemandStarAccessState.REGISTRATION_REQUIRED),
            ("Sign in to continue", DemandStarAccessState.LOGIN_REQUIRED),
            ("Purchase a subscription", DemandStarAccessState.SUBSCRIPTION_REQUIRED),
            ("Payment required: document fee", DemandStarAccessState.PAYMENT_REQUIRED),
            ("Access denied", DemandStarAccessState.RESTRICTED),
        )
        for text, state in cases:
            self.assertEqual(detect_access_boundary(text), state)
            with self.assertRaises(DemandStarAccessError):
                await self.collect(
                    [response(FIXTURE_PROFILE.discovery_url, text)],
                    DemandStarQuery(include_details=False),
                )

    async def test_profile_url_safety_migration_and_lifecycle(self):
        c = EunaOpenBidsDemandStarConnector(FIXTURE_PROFILE, transport=FakeTransport([]))
        self.assertTrue(c.health.configuration_valid)
        for url in (
            "http://www.demandstar.com/x",
            "https://evil.example/x",
            "https://127.0.0.1/x",
            "https://169.254.169.254/x",
        ):
            self.assertIsNone(c._safe_url(url))
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, page_size=0)
        migrated = replace(
            FIXTURE_PROFILE,
            profile_status="migrated",
            replacement_platform="opengov",
            replacement_url="https://fixture.gov/bids",
        )
        with self.assertRaises(DemandStarAccessError):
            await self.collect([], profile=migrated)
        owned = EunaOpenBidsDemandStarConnector(FIXTURE_PROFILE)
        await owned.aclose()
        self.assertTrue(owned._transport.is_closed)
        injected = FakeTransport([])
        external = EunaOpenBidsDemandStarConnector(FIXTURE_PROFILE, transport=injected)
        await external.aclose()
        self.assertFalse(injected.closed)

    async def test_retry_circuit_health_and_recovery(self):
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        c, t, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, "busy", 503, {"retry-after": "2"}),
                response(FIXTURE_PROFILE.discovery_url, LISTING),
            ],
            DemandStarQuery(include_details=False),
            sleep=sleep,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(c.health.consecutive_failures, 0)
        failing = replace(FIXTURE_PROFILE, retries=0, circuit_threshold=1)
        c = EunaOpenBidsDemandStarConnector(
            failing, transport=FakeTransport([httpx.ConnectError("offline")])
        )
        with self.assertRaises(DemandStarError):
            [x async for x in c.discover(DemandStarQuery(include_details=False))]
        self.assertTrue(c.health.circuit_open)
        self.assertIsNotNone(c.health.last_failure_time)

    def test_parser_malformed_embedded_json(self):
        items, links = parse_page(
            '<script type="application/json">{bad</script><a href="/next" data-document-type="next">next</a>'
        )
        self.assertEqual(items, [])
        self.assertEqual(len(links), 1)
