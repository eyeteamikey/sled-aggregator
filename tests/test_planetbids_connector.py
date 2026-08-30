import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from sled_aggregator.connectors.planetbids import (
    FIXTURE_PROFILE,
    LACOE_PROFILE,
    PLANETBIDS_PROFILES,
    STANISLAUS_COUNTY_PROFILE,
    PlanetBidsAccessError,
    PlanetBidsAccessState,
    PlanetBidsConnector,
    PlanetBidsError,
    PlanetBidsProfile,
    PlanetBidsQuery,
    detect_access_boundary,
    parse_page,
)
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "planetbids_listing.html").read_text()
DETAIL = (FIXTURES / "planetbids_detail.html").read_text()
RENDERED_LISTING = (FIXTURES / "planetbids_rendered_listing.html").read_text()


def response(url, text, status=200, headers=None):
    return httpx.Response(status, text=text, headers=headers, request=httpx.Request("GET", url))


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.calls, self.closed = list(replies), [], False

    async def get(self, url, *, params=None):
        self.calls.append((url, params))
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def aclose(self):
        self.closed = True


class PlanetBidsTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, profile=FIXTURE_PROFILE, **kwargs):
        transport = FakeTransport(replies)
        connector = PlanetBidsConnector(profile, transport=transport, **kwargs)
        items = [x async for x in connector.discover(query or PlanetBidsQuery())]
        return connector, transport, items

    def test_registry_aliases_and_product_separation(self):
        for alias in (
            "planetbids",
            "planet-bids",
            "planetbids-portal",
            "planetbids-vendor-portal",
            "pb-system",
            "pbsystem",
        ):
            self.assertIs(connector_registry.get(alias), PlanetBidsConnector)
        for ambiguous in ("planet", "vendor-portal", "procurement", "bids", "vendorline"):
            with self.assertRaises(KeyError):
                connector_registry.get(ambiguous)

    def test_profile_validation_and_states(self):
        self.assertTrue(
            PlanetBidsConnector(
                FIXTURE_PROFILE, transport=FakeTransport([])
            ).health.configuration_valid
        )
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, profile_status="invalid")
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, page_size=0)
        invalid = replace(FIXTURE_PROFILE, profile_key="Bad Key")
        self.assertFalse(
            PlanetBidsConnector(invalid, transport=FakeTransport([])).health.configuration_valid
        )
        for state in ("active", "configured_unverified", "legacy", "migrated", "unavailable"):
            self.assertIsInstance(replace(FIXTURE_PROFILE, profile_status=state), PlanetBidsProfile)

    def test_live_profile_resolution_preserves_portal_and_buyer_class(self):
        self.assertIs(PLANETBIDS_PROFILES["stanislaus-county-ca"], STANISLAUS_COUNTY_PROFILE)
        self.assertIs(PLANETBIDS_PROFILES["lacoe-ca"], LACOE_PROFILE)
        self.assertEqual(STANISLAUS_COUNTY_PROFILE.organization_id, "14599")
        self.assertEqual(STANISLAUS_COUNTY_PROFILE.government_level, "county")
        self.assertEqual(LACOE_PROFILE.organization_id, "61954")
        self.assertEqual(LACOE_PROFILE.government_level, "education")
        self.assertEqual(LACOE_PROFILE.agency_name, "Los Angeles County Office of Education")
        for profile in (STANISLAUS_COUNTY_PROFILE, LACOE_PROFILE):
            self.assertTrue(PlanetBidsConnector(profile, transport=FakeTransport([])).health.configuration_valid)
            self.assertIn(f"/portal/{profile.organization_id}/", profile.discovery_url)

    async def test_rendered_ember_listing_cross_tenant_identity_dates_and_dedup(self):
        profile = replace(STANISLAUS_COUNTY_PROFILE, maximum_pages=2)
        _, transport, items = await self.collect(
            [response(profile.discovery_url, RENDERED_LISTING), response(profile.discovery_url, RENDERED_LISTING)],
            PlanetBidsQuery(include_details=False, maximum_pages=2, maximum_results=10),
            profile=profile,
        )
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source.source_id, "planetbids:stanislaus-county-ca:144525")
        self.assertEqual(items[0].solicitation_number, "2026-260024")
        self.assertEqual(items[0].posted_at.tzinfo.key, "America/Los_Angeles")
        self.assertEqual(items[1].status.value, "awarded")

        _, _, number_match = await self.collect(
            [response(profile.discovery_url, RENDERED_LISTING)],
            PlanetBidsQuery(include_details=False, keywords=("1795-26/27",)),
            profile=profile,
        )
        self.assertEqual([item.solicitation_number for item in number_match], ["1795-26/27"])

    async def test_discovery_detail_identity_provenance_and_mixed_documents(self):
        c, _, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, LISTING),
                response(FIXTURE_PROFILE.detail_url("pb-1001"), DETAIL),
            ]
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source.source_id, "planetbids:fixture-county:pb-1001")
        self.assertEqual(item.solicitation_number, "RFP-26-20")
        self.assertIn("source_provenance", item.raw_payload)
        self.assertFalse(item.raw_payload["documents_complete"])
        docs = c.document_candidates(item)
        self.assertEqual(len(docs), 7)  # duplicate URL is suppressed
        self.assertEqual(docs[1].access_state, AccessState.LOGIN_REQUIRED)
        self.assertEqual(docs[2].access_state, AccessState.PROSPECTIVE_BIDDER_REQUIRED)
        self.assertFalse(docs[1].publicly_retrievable)
        self.assertTrue(docs[0].publicly_retrievable)
        self.assertEqual(
            {d.category for d in docs},
            {
                "solicitation",
                "other",
                "addendum",
                "questions_and_answers",
                "bid_tabulation",
                "award_notice",
            },
        )
        self.assertIn("publicQA", item.raw_payload)
        self.assertIn("award", item.raw_payload)

    async def test_filters_bounds_duplicates_empty_and_changed_markup(self):
        _, transport, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            PlanetBidsQuery(include_details=False, keywords=("water",), maximum_pages=5),
        )
        self.assertEqual((len(items), len(transport.calls)), (1, 1))
        _, _, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            PlanetBidsQuery(include_details=False, status="closed"),
        )
        self.assertEqual(items, [])
        empty = "<main data-planetbids-list>No open opportunities</main>"
        _, _, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, empty)], PlanetBidsQuery(include_details=False)
        )
        self.assertEqual(items, [])
        with self.assertRaises(PlanetBidsAccessError) as caught:
            await self.collect(
                [response(FIXTURE_PROFILE.discovery_url, '<div id="changed"></div>')],
                PlanetBidsQuery(include_details=False),
            )
        self.assertEqual(caught.exception.state, PlanetBidsAccessState.CHANGED_MARKUP)

    async def test_access_boundaries_do_not_retry(self):
        cases = (
            ("Registration required", PlanetBidsAccessState.REGISTRATION_REQUIRED),
            ("Sign in to continue", PlanetBidsAccessState.LOGIN_REQUIRED),
            ("Join the prospective bidder list", PlanetBidsAccessState.PROSPECTIVE_BIDDER_REQUIRED),
            ("By Invitation Only", PlanetBidsAccessState.INVITATION_ONLY),
            ("Access denied", PlanetBidsAccessState.RESTRICTED),
        )
        for text, state in cases:
            self.assertEqual(detect_access_boundary(text), state)
            with self.assertRaises(PlanetBidsAccessError):
                await self.collect(
                    [response(FIXTURE_PROFILE.discovery_url, text)],
                    PlanetBidsQuery(include_details=False),
                )

    async def test_url_safety_migration_and_lifecycle(self):
        c = PlanetBidsConnector(FIXTURE_PROFILE, transport=FakeTransport([]))
        for url in (
            "http://www.planetbids.com/x",
            "https://evil.example/x",
            "https://127.0.0.1/x",
            "https://169.254.169.254/x",
            "https://user:pass@www.planetbids.com/x",
        ):
            self.assertIsNone(c._safe_url(url))
        migrated = replace(
            FIXTURE_PROFILE,
            profile_status="migrated",
            replacement_platform="opengov",
            replacement_url="https://fixture.gov/bids",
        )
        with self.assertRaises(PlanetBidsAccessError):
            await self.collect([], profile=migrated)
        owned = PlanetBidsConnector(FIXTURE_PROFILE)
        await owned.aclose()
        self.assertTrue(owned._transport.is_closed)
        injected = FakeTransport([])
        external = PlanetBidsConnector(FIXTURE_PROFILE, transport=injected)
        await external.aclose()
        self.assertFalse(injected.closed)

    async def test_retry_circuit_health_and_recovery(self):
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        c, _, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, "busy", 503, {"retry-after": "2"}),
                response(FIXTURE_PROFILE.discovery_url, LISTING),
            ],
            PlanetBidsQuery(include_details=False),
            sleep=sleep,
        )
        self.assertEqual((len(items), sleeps, c.health.consecutive_failures), (1, [2.0], 0))
        profile = replace(FIXTURE_PROFILE, retries=0, circuit_threshold=1)
        c = PlanetBidsConnector(profile, transport=FakeTransport([httpx.ConnectError("offline")]))
        with self.assertRaises(PlanetBidsError):
            [x async for x in c.discover(PlanetBidsQuery(include_details=False))]
        self.assertTrue(c.health.circuit_open)

    def test_malformed_parser_fails_closed(self):
        items, links = parse_page(
            '<script type="application/json">{bad</script><a href="/next" data-document-type="next">next</a>'
        )
        self.assertEqual(items, [])
        self.assertEqual(len(links), 1)


if __name__ == "__main__":
    unittest.main()
