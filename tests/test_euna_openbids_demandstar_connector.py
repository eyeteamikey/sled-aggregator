import json
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx

from sled_aggregator.connectors.euna_bonfire import BonfireProcurementConnector
from sled_aggregator.connectors.euna_ionwave import EunaIonWaveConnector
from sled_aggregator.connectors.euna_openbids_demandstar import (
    BUTLER_COUNTY,
    FIXTURE_PROFILE,
    LYNN_HAVEN,
    RAMSEY_COUNTY,
    WILL_COUNTY,
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
API_SEARCH = (FIXTURES / "demandstar_api_search.json").read_text()
API_SUMMARY = (FIXTURES / "demandstar_api_summary.json").read_text()
API_DOCUMENTS = (FIXTURES / "demandstar_api_documents.json").read_text()
API_COMMODITIES = (FIXTURES / "demandstar_api_commodities.json").read_text()
API_PLANHOLDERS = (FIXTURES / "demandstar_api_planholders.json").read_text()
WILL_SHAPE = json.loads((FIXTURES / "demandstar_will_live_shape.json").read_text())
RAMSEY_SHAPE = json.loads(
    (FIXTURES / "demandstar_ramsey_live_shape.json").read_text()
)


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


class FakeAPITransport(FakeTransport):
    async def post(self, url, *, json):
        self.calls.append((url, dict(json)))
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


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

    async def test_live_profiles_and_anonymous_agency_api_contract(self):
        self.assertEqual(BUTLER_COUNTY.verification_status, "live_har_validated")
        self.assertEqual(LYNN_HAVEN.verification_status, "live_har_validated")
        self.assertIn("/app/limited/bids/{opportunity_id}/details", LYNN_HAVEN.detail_url_template)
        replies = [
            response(LYNN_HAVEN.discovery_url, API_SEARCH, headers={"content-type": "application/json"}),
            response(LYNN_HAVEN.discovery_url, API_SUMMARY, headers={"content-type": "application/json"}),
            response(LYNN_HAVEN.discovery_url, API_DOCUMENTS, headers={"content-type": "application/json"}),
            response(LYNN_HAVEN.discovery_url, API_COMMODITIES, headers={"content-type": "application/json"}),
            response(LYNN_HAVEN.discovery_url, API_PLANHOLDERS, headers={"content-type": "application/json"}),
        ]
        transport = FakeAPITransport(replies)
        connector = EunaOpenBidsDemandStarConnector(LYNN_HAVEN, transport=transport)
        items = [item async for item in connector.discover(DemandStarQuery())]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.solicitation_number, "RFP-26-42")
        self.assertEqual(item.source.source_id, "euna/openbids-demandstar:fl-lynn-haven:4242")
        self.assertEqual(item.categories, ["Fixture radio services"])
        self.assertEqual(len(item.raw_payload["public_planholders"]), 1)
        self.assertEqual(len(item.raw_payload["documents"]), 2)
        self.assertEqual(item.raw_payload["documents"][0]["accessState"], "registration_required")
        self.assertEqual(connector.document_candidates(item), [])
        self.assertEqual([call[0].rsplit("/", 1)[-1] for call in transport.calls], [
            "search", "summary", "documents", "commodityByType", "planholders"
        ])

    async def test_will_and_ramsey_profiles_replay_shared_live_shape(self):
        for profile, shape, expected_number, expected_category in (
            (WILL_COUNTY, WILL_SHAPE, "2026-80", "Roofing and Siding"),
            (RAMSEY_COUNTY, RAMSEY_SHAPE, "HSD0000002859", "Emergency Shelter Services"),
        ):
            self.assertEqual(profile.verification_status, "live_public_verified")
            self.assertIsInstance(profile.legacy_member_id, int)
            self.assertIn(profile.organization_id, profile.discovery_url)
            replies = [
                response(
                    profile.discovery_url,
                    json.dumps(shape[key]),
                    headers={"content-type": "application/json"},
                )
                for key in ("search", "summary", "documents", "commodities", "planholders", "legal")
            ]
            transport = FakeAPITransport(replies)
            connector = EunaOpenBidsDemandStarConnector(profile, transport=transport)
            items = [
                item
                async for item in connector.discover(
                    DemandStarQuery(maximum_results=1, include_details=True)
                )
            ]
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.solicitation_number, expected_number)
            self.assertEqual(item.status.value, "open")
            self.assertEqual(item.categories, [expected_category])
            self.assertEqual(item.posted_at.utcoffset(), timedelta(hours=-5))
            self.assertEqual(item.due_at.utcoffset(), timedelta(hours=-5))
            self.assertEqual(item.raw_payload["opportunityType"], "RFP - Request for Proposal")
            self.assertTrue(item.raw_payload["buyer_contact"]["name"].endswith("Buyer"))
            self.assertEqual(item.raw_payload["documents"][0]["accessState"], "registration_required")
            self.assertFalse(item.raw_payload["documents_complete"])
            self.assertEqual(connector.document_candidates(item), [])
            self.assertEqual(
                [call[0].rsplit("/", 1)[-1] for call in transport.calls],
                ["search", "summary", "documents", "commodityByType", "planholders", "legal"],
            )

    async def test_live_api_bounds_keyword_status_and_source_identity(self):
        shape = WILL_SHAPE
        transport = FakeAPITransport(
            [
                response(
                    WILL_COUNTY.discovery_url,
                    json.dumps(shape["search"]),
                    headers={"content-type": "application/json"},
                )
            ]
        )
        connector = EunaOpenBidsDemandStarConnector(WILL_COUNTY, transport=transport)
        items = [
            item
            async for item in connector.discover(
                DemandStarQuery(
                    include_details=False,
                    keywords=("testing",),
                    status="closed",
                    maximum_results=10,
                )
            )
        ]
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].source.source_id.endswith(":544920"))
        self.assertEqual(items[0].raw_payload["openbids_search"]["mi"], 122067)

    async def test_api_fails_closed_on_malformed_result(self):
        malformed = response(
            WILL_COUNTY.discovery_url,
            '{"result":{"unexpected":true}}',
            headers={"content-type": "application/json"},
        )
        connector = EunaOpenBidsDemandStarConnector(
            WILL_COUNTY, transport=FakeAPITransport([malformed])
        )
        with self.assertRaises(DemandStarAccessError) as caught:
            [item async for item in connector.discover(DemandStarQuery(include_details=False))]
        self.assertEqual(caught.exception.state, DemandStarAccessState.CHANGED_MARKUP)

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
