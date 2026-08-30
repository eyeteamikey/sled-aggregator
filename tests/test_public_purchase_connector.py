import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from sled_aggregator.connectors.public_purchase import (
    FIXTURE_PROFILE,
    FRESNO_COUNTY_PROFILE,
    KERN_COUNTY_PROFILE,
    PUBLIC_PURCHASE_PROFILES,
    PublicPurchaseAccessError,
    PublicPurchaseAccessState,
    PublicPurchaseConnector,
    PublicPurchaseError,
    PublicPurchaseQuery,
    detect_access_boundary,
    parse_page,
)
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "public_purchase_listing.html").read_text()
DETAIL = (FIXTURES / "public_purchase_detail.html").read_text()


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


class PublicPurchaseTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, profile=FIXTURE_PROFILE, **kwargs):
        transport = FakeTransport(replies)
        connector = PublicPurchaseConnector(profile, transport=transport, **kwargs)
        items = [x async for x in connector.discover(query or PublicPurchaseQuery())]
        return connector, transport, items

    def test_registry_aliases_and_product_separation(self):
        for alias in (
            "public-purchase",
            "publicpurchase",
            "public-purchase-portal",
            "public-purchase-gems",
            "the-public-group-public-purchase",
        ):
            self.assertIs(connector_registry.get(alias), PublicPurchaseConnector)
        for ambiguous in ("public", "purchase", "bid-board", "gems", "procurement"):
            with self.assertRaises(KeyError):
                connector_registry.get(ambiguous)
        self.assertIsNot(connector_registry.get("bidx"), PublicPurchaseConnector)
        self.assertIsNot(connector_registry.get("demandstar"), PublicPurchaseConnector)
        self.assertIsNot(connector_registry.get("planetbids"), PublicPurchaseConnector)
        self.assertIsNot(connector_registry.get("bidnet-direct"), PublicPurchaseConnector)

    def test_profile_validation_and_explicit_hosts(self):
        connector = PublicPurchaseConnector(FIXTURE_PROFILE, transport=FakeTransport([]))
        self.assertTrue(connector.health.configuration_valid)
        for unsafe in (
            "http://www.publicpurchase.com/x",
            "https://evil-bidnet.example/x",
            "https://127.0.0.1/x",
            "https://169.254.1.1/x",
            "https://user:pass@www.publicpurchase.com/x",
        ):
            self.assertIsNone(connector._safe_url(unsafe))
        self.assertIsNotNone(connector._safe_url("https://docs.fixture.gov/a.pdf", document=True))
        self.assertIsNone(connector._safe_url("https://docs.fixture.gov/a.pdf"))
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, maximum_pages=0)
        self.assertFalse(
            PublicPurchaseConnector(
                replace(FIXTURE_PROFILE, profile_key="Bad Key"), transport=FakeTransport([])
            ).health.configuration_valid
        )

    def test_live_verified_fresno_and_kern_profiles_are_explicit(self):
        self.assertEqual(
            set(PUBLIC_PURCHASE_PROFILES),
            {"fixture-agency-profile", "ca-fresno-county", "ca-kern-county"},
        )
        for profile in (FRESNO_COUNTY_PROFILE, KERN_COUNTY_PROFILE):
            self.assertEqual(profile.verification_status, "live_public_verified")
            self.assertEqual(profile.expected_access_model, "anonymous_listing_login_detail")
            self.assertTrue(profile.discovery_url.endswith("/buyer/public/publicInfo"))
            self.assertTrue(profile.closed_discovery_url.endswith("/publicClosedBidsInfo"))
            self.assertTrue(
                PublicPurchaseConnector(profile, transport=FakeTransport([])).health.configuration_valid
            )

    def test_observed_gems_open_and_closed_tables(self):
        open_html = (FIXTURES / "public_purchase_gems_open_table.html").read_text()
        closed_html = (FIXTURES / "public_purchase_gems_closed_table.html").read_text()
        opened, _ = parse_page(open_html)
        closed, links = parse_page(closed_html)
        self.assertEqual(opened[0]["id"], "123456")
        self.assertEqual(opened[0]["solicitationNumber"], "27-005")
        self.assertEqual(opened[0]["title"], "Snow Services")
        self.assertEqual(opened[0]["status"], "Open")
        self.assertEqual(opened[0]["accessState"], "public_metadata_only")
        self.assertFalse(opened[0]["documentsComplete"])
        self.assertEqual(closed[0]["status"], "FINALIZED")
        self.assertEqual(closed[0]["solicitationNumber"], "PA-1686")
        self.assertTrue(any(href == "#" for href, *_ in links))

    async def test_observed_table_normalization_and_detail_login_boundary(self):
        listing = (FIXTURES / "public_purchase_gems_open_table.html").read_text()
        login = (FIXTURES / "public_purchase_gems_login_detail.html").read_text()
        connector, _, items = await self.collect(
            [
                response(FRESNO_COUNTY_PROFILE.discovery_url, listing),
                response(FRESNO_COUNTY_PROFILE.detail_url("123456"), login),
            ],
            profile=FRESNO_COUNTY_PROFILE,
        )
        item = items[0]
        self.assertEqual(item.source.source_id, "public-purchase:ca-fresno-county:123456")
        self.assertEqual(item.solicitation_number, "27-005")
        self.assertEqual(item.posted_at.isoformat(), "2026-08-17T13:07:58-07:00")
        self.assertEqual(item.raw_payload["detail_access_state"], "login_required")
        self.assertFalse(item.raw_payload["documents_complete"])
        self.assertEqual(connector.document_candidates(item), [])

    async def test_discovery_normalization_provenance_documents_and_filters(self):
        c, _, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, LISTING),
                response(FIXTURE_PROFILE.detail_url("pp-1001"), DETAIL),
            ]
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source.source_id, "public-purchase:fixture-agency-profile:pp-1001")
        self.assertEqual(item.raw_payload["source_classification"], "public_purchase_member_agency")
        self.assertEqual(item.raw_payload["displayed_source_id"], "PP-1001")
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
            PublicPurchaseQuery(
                include_details=False,
                solicitation_number="26-23",
                agency="Fixture",
                status="open",
            ),
        )
        self.assertEqual(len(filtered), 1)

    async def test_bounds_repeated_empty_changed_and_malformed(self):
        _, transport, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            PublicPurchaseQuery(include_details=False, maximum_pages=10, maximum_results=1),
        )
        self.assertEqual((len(items), len(transport.calls)), (1, 1))
        _, _, empty = await self.collect(
            [
                response(
                    FIXTURE_PROFILE.discovery_url,
                    "<main data-public-purchase-list>No open opportunities</main>",
                )
            ],
            PublicPurchaseQuery(include_details=False),
        )
        self.assertEqual(empty, [])
        for markup in ('<div id="changed"></div>', '<script type="application/json">{bad</script>'):
            with self.assertRaises(PublicPurchaseAccessError) as caught:
                await self.collect(
                    [response(FIXTURE_PROFILE.discovery_url, markup)],
                    PublicPurchaseQuery(include_details=False),
                )
            self.assertEqual(caught.exception.state, PublicPurchaseAccessState.CHANGED_MARKUP)

    async def test_all_policy_boundaries_are_terminal(self):
        cases = (
            ("Registration required", "registration_required"),
            ("Enroll with this agency", "agency_enrollment_required"),
            ("Sign in to continue", "login_required"),
            ("Subscription required", "subscription_required"),
            ("Paid Bid Syndication for non-member agencies", "paid_syndication_required"),
            ("Join the bidders list", "bid_participation_required"),
            ("Disallowed by robots policy", "robots_policy_blocked"),
            ("Automated access blocked", "automated_access_blocked"),
            ("CAPTCHA", "captcha_required"),
            ("Access denied", "restricted"),
        )
        for text, expected in cases:
            self.assertEqual(detect_access_boundary(text).value, expected)
            transport = FakeTransport([response(FIXTURE_PROFILE.discovery_url, text)])
            with self.assertRaises(PublicPurchaseAccessError):
                [
                    x
                    async for x in PublicPurchaseConnector(
                        FIXTURE_PROFILE, transport=transport
                    ).discover(PublicPurchaseQuery(include_details=False))
                ]
            self.assertEqual(len(transport.calls), 1)

    def test_redirect_validation_and_access_states(self):
        c = PublicPurchaseConnector(FIXTURE_PROFILE, transport=FakeTransport([]))
        source = FIXTURE_PROFILE.detail_url("pp-1001")
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
            "agency_enrollment_required",
            "login_required",
            "subscription_required",
            "paid_syndication_required",
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
            PublicPurchaseQuery(include_details=False),
            sleep=sleep,
        )
        self.assertEqual((len(items), sleeps, c.health.consecutive_failures), (1, [2.0], 0))
        self.assertIsNotNone(c.health.last_success_time)
        failed = PublicPurchaseConnector(
            replace(FIXTURE_PROFILE, retries=0, circuit_threshold=1),
            transport=FakeTransport([httpx.ConnectError("offline")]),
        )
        with self.assertRaises(PublicPurchaseError):
            [x async for x in failed.discover(PublicPurchaseQuery(include_details=False))]
        self.assertTrue(failed.health.circuit_open)
        owned = PublicPurchaseConnector(FIXTURE_PROFILE)
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
            "agency_enrollment",
            "bid_syndication",
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
            path = FIXTURES / f"public_purchase_{name}.html"
            self.assertTrue(path.exists(), name)
            text = path.read_text().casefold()
            for secret in ("authorization: bearer", "session cookie", "credit card"):
                self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
