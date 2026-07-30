import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from sled_aggregator.connectors.bidnet_direct import (
    FIXTURE_PROFILE,
    BidNetDirectAccessError,
    BidNetDirectAccessState,
    BidNetDirectConnector,
    BidNetDirectError,
    BidNetDirectQuery,
    detect_access_boundary,
)
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "bidnet_direct_listing.html").read_text()
DETAIL = (FIXTURES / "bidnet_direct_detail.html").read_text()


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


class BidNetDirectTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, profile=FIXTURE_PROFILE, **kwargs):
        transport = FakeTransport(replies)
        connector = BidNetDirectConnector(profile, transport=transport, **kwargs)
        items = [x async for x in connector.discover(query or BidNetDirectQuery())]
        return connector, transport, items

    def test_registry_aliases_and_product_separation(self):
        for alias in (
            "bidnet-direct",
            "bidnet",
            "bid-net-direct",
            "bidnetdirect",
            "bidnet-regional-purchasing-group",
        ):
            self.assertIs(connector_registry.get(alias), BidNetDirectConnector)
        for ambiguous in ("direct", "regional-bids", "purchasing-group", "network"):
            with self.assertRaises(KeyError):
                connector_registry.get(ambiguous)
        self.assertIsNot(connector_registry.get("bidx"), BidNetDirectConnector)
        self.assertIsNot(connector_registry.get("demandstar"), BidNetDirectConnector)
        self.assertIsNot(connector_registry.get("planetbids"), BidNetDirectConnector)

    def test_profile_validation_and_explicit_hosts(self):
        connector = BidNetDirectConnector(FIXTURE_PROFILE, transport=FakeTransport([]))
        self.assertTrue(connector.health.configuration_valid)
        for unsafe in (
            "http://www.bidnetdirect.com/x",
            "https://evil-bidnet.example/x",
            "https://127.0.0.1/x",
            "https://169.254.1.1/x",
            "https://user:pass@www.bidnetdirect.com/x",
        ):
            self.assertIsNone(connector._safe_url(unsafe))
        self.assertIsNotNone(connector._safe_url("https://docs.fixture.gov/a.pdf", document=True))
        self.assertIsNone(connector._safe_url("https://docs.fixture.gov/a.pdf"))
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, maximum_pages=0)
        self.assertFalse(
            BidNetDirectConnector(
                replace(FIXTURE_PROFILE, profile_key="Bad Key"), transport=FakeTransport([])
            ).health.configuration_valid
        )

    async def test_discovery_normalization_provenance_documents_and_filters(self):
        c, _, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, LISTING),
                response(FIXTURE_PROFILE.detail_url("bn-1001"), DETAIL),
            ]
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source.source_id, "bidnet-direct:fixture-regional-group:bn-1001")
        self.assertEqual(item.raw_payload["source_classification"], "member_agency_original")
        self.assertEqual(item.raw_payload["displayed_source_id"], "BN-1001")
        self.assertFalse(item.raw_payload["documents_complete"])
        docs = c.document_candidates(item)
        self.assertEqual(len(docs), 6)
        gated = next(d for d in docs if d.access_state is AccessState.REGISTRATION_REQUIRED)
        public = next(d for d in docs if d.filename == "RFP-26-23.pdf")
        self.assertFalse(gated.publicly_retrievable)
        self.assertTrue(public.publicly_retrievable)
        self.assertEqual(
            {d.category for d in docs},
            {"solicitation", "addendum", "questions_and_answers", "award_notice"},
        )
        _, _, filtered = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            BidNetDirectQuery(
                include_details=False,
                solicitation_number="26-23",
                agency="Fixture",
                purchasing_group="Regional",
                status="open",
            ),
        )
        self.assertEqual(len(filtered), 1)

    async def test_bounds_repeated_empty_changed_and_malformed(self):
        _, transport, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            BidNetDirectQuery(include_details=False, maximum_pages=10, maximum_results=1),
        )
        self.assertEqual((len(items), len(transport.calls)), (1, 1))
        _, _, empty = await self.collect(
            [
                response(
                    FIXTURE_PROFILE.discovery_url,
                    "<main data-bidnet-list>No open opportunities</main>",
                )
            ],
            BidNetDirectQuery(include_details=False),
        )
        self.assertEqual(empty, [])
        for markup in ('<div id="changed"></div>', '<script type="application/json">{bad</script>'):
            with self.assertRaises(BidNetDirectAccessError) as caught:
                await self.collect(
                    [response(FIXTURE_PROFILE.discovery_url, markup)],
                    BidNetDirectQuery(include_details=False),
                )
            self.assertEqual(caught.exception.state, BidNetDirectAccessState.CHANGED_MARKUP)

    async def test_all_policy_boundaries_are_terminal(self):
        cases = (
            ("Registration required", "registration_required"),
            ("Sign in to continue", "login_required"),
            ("Subscription required", "subscription_required"),
            ("Premium aggregation nationwide package", "premium_aggregation_required"),
            ("Join the bidders list", "bid_participation_required"),
            ("Disallowed by robots policy", "robots_policy_blocked"),
            ("Automated access blocked", "automated_access_blocked"),
            ("CAPTCHA", "captcha_required"),
            ("Access denied", "restricted"),
        )
        for text, expected in cases:
            self.assertEqual(detect_access_boundary(text).value, expected)
            transport = FakeTransport([response(FIXTURE_PROFILE.discovery_url, text)])
            with self.assertRaises(BidNetDirectAccessError):
                [
                    x
                    async for x in BidNetDirectConnector(
                        FIXTURE_PROFILE, transport=transport
                    ).discover(BidNetDirectQuery(include_details=False))
                ]
            self.assertEqual(len(transport.calls), 1)

    def test_redirect_validation_and_access_states(self):
        c = BidNetDirectConnector(FIXTURE_PROFILE, transport=FakeTransport([]))
        source = FIXTURE_PROFILE.detail_url("bn-1001")
        self.assertEqual(
            c.validate_redirect(source, "https://docs.fixture.gov/a.pdf", document=True),
            "https://docs.fixture.gov/a.pdf",
        )
        self.assertIsNone(c.validate_redirect(source, "https://evil.example/a.pdf", document=True))
        self.assertIsNone(c.validate_redirect(source, "https://10.0.0.1/a.pdf", document=True))
        for state in (
            "public",
            "public_metadata_only",
            "registration_required",
            "login_required",
            "subscription_required",
            "premium_aggregation_required",
            "bid_participation_required",
            "external_public_source",
            "robots_policy_blocked",
            "automated_access_blocked",
            "captcha_required",
            "restricted",
            "unavailable",
            "unknown",
        ):
            self.assertEqual(c._access_state(state).value, state)

    async def test_retry_circuit_health_recovery_and_ownership(self):
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        c, _, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, "busy", 503, {"retry-after": "2"}),
                response(FIXTURE_PROFILE.discovery_url, LISTING),
            ],
            BidNetDirectQuery(include_details=False),
            sleep=sleep,
        )
        self.assertEqual((len(items), sleeps, c.health.consecutive_failures), (1, [2.0], 0))
        self.assertIsNotNone(c.health.last_success_time)
        failed = BidNetDirectConnector(
            replace(FIXTURE_PROFILE, retries=0, circuit_threshold=1),
            transport=FakeTransport([httpx.ConnectError("offline")]),
        )
        with self.assertRaises(BidNetDirectError):
            [x async for x in failed.discover(BidNetDirectQuery(include_details=False))]
        self.assertTrue(failed.health.circuit_open)
        owned = BidNetDirectConnector(FIXTURE_PROFILE)
        await owned.aclose()
        self.assertTrue(owned._transport.is_closed)

    def test_fixture_inventory_is_sanitized_and_complete(self):
        names = [
            "regional_listing",
            "agency_listing",
            "detail",
            "metadata_only",
            "registration_documents",
            "login_page",
            "subscription_page",
            "premium_notice",
            "agency_alternative",
            "public_agency_document",
            "addenda",
            "qa",
            "results",
            "award",
            "bid_intent",
            "submission",
            "duplicate_routes",
            "duplicate_attachments",
            "external_record",
            "member_original",
            "robots_block",
            "automated_block",
            "captcha",
            "changed_markup",
            "malformed",
            "empty",
            "pagination_cycle",
            "repeated_page",
            "safe_redirect",
            "unsafe_redirect",
            "file_html",
            "replacement_addendum",
        ]
        for name in names:
            path = FIXTURES / f"bidnet_direct_{name}.html"
            self.assertTrue(path.exists(), name)
            text = path.read_text().casefold()
            for secret in ("authorization: bearer", "session cookie", "credit card"):
                self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
