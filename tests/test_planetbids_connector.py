import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from sled_aggregator.connectors.planetbids import (
    FIXTURE_PROFILE,
    LOS_ANGELES_COUNTY_OFFICE_OF_EDUCATION,
    PLANETBIDS_PROFILES,
    STANISLAUS_COUNTY,
    PlanetBidsAccessError,
    PlanetBidsAccessState,
    PlanetBidsConnector,
    PlanetBidsError,
    PlanetBidsProfile,
    PlanetBidsQuery,
    detect_access_boundary,
    parse_api_response,
    parse_page,
)
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "planetbids_listing.html").read_text()
DETAIL = (FIXTURES / "planetbids_detail.html").read_text()
API_LISTING = (FIXTURES / "planetbids_api_listing.json").read_text()
API_DETAIL = (FIXTURES / "planetbids_api_detail.json").read_text()
API_DOCUMENTS = (FIXTURES / "planetbids_api_documents.json").read_text()
API_EMPTY = '{"data":[],"included":[],"meta":{"serverTime":"2026-09-23 00:00:00"}}'


def response(url, text, status=200, headers=None):
    return httpx.Response(status, text=text, headers=headers, request=httpx.Request("GET", url))


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.calls, self.closed = list(replies), [], False

    async def get(self, url, *, params=None, headers=None):
        self.calls.append((url, params, headers))
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

    def test_har_verified_tenant_profiles(self):
        self.assertEqual(STANISLAUS_COUNTY.organization_id, "14599")
        self.assertEqual(LOS_ANGELES_COUNTY_OFFICE_OF_EDUCATION.organization_id, "61954")
        self.assertEqual(
            set(PLANETBIDS_PROFILES),
            {
                "fixture-county",
                "ca-stanislaus-county",
                "ca-los-angeles-county-office-of-education",
            },
        )
        for profile in (STANISLAUS_COUNTY, LOS_ANGELES_COUNTY_OFFICE_OF_EDUCATION):
            self.assertEqual(profile.verification_status, "har_verified")
            self.assertTrue(
                PlanetBidsConnector(profile, transport=FakeTransport([])).health.configuration_valid
            )

    async def test_observed_json_api_contract_and_conservative_document_access(self):
        connector, transport, items = await self.collect(
            [
                response(STANISLAUS_COUNTY.discovery_url, API_LISTING),
                response(STANISLAUS_COUNTY.detail_url("145663"), API_DETAIL),
                response("https://api-external.prod.planetbids.com/papi/bid-downloadable-files", API_DOCUMENTS),
                response("https://api-external.prod.planetbids.com/papi/bid-addenda", API_EMPTY),
                response("https://api-external.prod.planetbids.com/papi/bid-q-and-a-items", API_EMPTY),
                response("https://api-external.prod.planetbids.com/papi/bid-email-history-items", API_EMPTY),
                response("https://api-external.prod.planetbids.com/papi/pre-bid-meetings", API_EMPTY),
            ],
            PlanetBidsQuery(maximum_pages=1, maximum_results=1),
            profile=STANISLAUS_COUNTY,
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source.source_id, "planetbids:ca-stanislaus-county:145663")
        self.assertEqual(item.solicitation_number, "RFP-26-20")
        self.assertEqual(item.raw_payload["contact_email"], "buyer@example.gov")
        self.assertEqual(len(item.raw_payload["documents"]), 1)
        documents = connector.document_candidates(item)
        self.assertEqual(documents[0].access_state, AccessState.PUBLIC_METADATA_ONLY)
        self.assertFalse(documents[0].publicly_retrievable)
        listing_call = transport.calls[0]
        self.assertEqual(listing_call[1]["cid"], "14599")
        self.assertEqual(listing_call[1]["per_page"], 30)
        self.assertEqual(listing_call[2]["company-id"], "14599")
        self.assertEqual(listing_call[2]["accept"], "application/vnd.api+json")

    def test_json_api_parser_flattens_observed_envelope(self):
        records, meta = parse_api_response(API_LISTING)
        self.assertEqual(records[0]["id"], "145663")
        self.assertEqual(records[0]["stageStr"], "Bidding")
        self.assertEqual(meta["totalPages"], 1)

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
            ("Verify you are human", PlanetBidsAccessState.CAPTCHA_REQUIRED),
            ("Access denied", PlanetBidsAccessState.RESTRICTED),
        )
        for text, state in cases:
            self.assertEqual(detect_access_boundary(text), state)
            with self.assertRaises(PlanetBidsAccessError):
                await self.collect(
                    [response(FIXTURE_PROFILE.discovery_url, text)],
                    PlanetBidsQuery(include_details=False),
                )

        with self.assertRaises(PlanetBidsAccessError) as caught:
            await self.collect(
                [response(FIXTURE_PROFILE.discovery_url, "security challenge", 403)],
                PlanetBidsQuery(include_details=False),
            )
        self.assertEqual(caught.exception.state, PlanetBidsAccessState.CAPTCHA_REQUIRED)

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
