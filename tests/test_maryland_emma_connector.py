import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from sled_aggregator.connectors.maryland_emma import (
    FIXTURE_PROFILE,
    MarylandEMMAAccessError,
    MarylandEMMAAccessState,
    MarylandEMMAConnector,
    MarylandEMMAError,
    MarylandEMMAProfile,
    MarylandEMMAQuery,
    detect_access_boundary,
    external_platform,
    parse_aspnet_state,
    parse_page,
)
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "maryland_emma_listing.html").read_text()
DETAIL = (FIXTURES / "maryland_emma_detail.html").read_text()
NOTICE = (FIXTURES / "maryland_emma_notice.html").read_text()


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


class MarylandEMMATests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, profile=FIXTURE_PROFILE, **kwargs):
        transport = FakeTransport(replies)
        connector = MarylandEMMAConnector(profile, transport=transport, **kwargs)
        items = [x async for x in connector.discover(query or MarylandEMMAQuery())]
        return connector, transport, items

    def test_registry_identity_aliases_and_separation(self):
        for alias in (
            "maryland/emma",
            "maryland-emma",
            "emma-maryland",
            "emaryland-marketplace",
            "emaryland-marketplace-advantage",
            "md-emma",
        ):
            self.assertIs(connector_registry.get(alias), MarylandEMMAConnector)
        for ambiguous in ("emma", "marketplace", "maryland", "page-aspx", "aspnet"):
            with self.assertRaises(KeyError):
                connector_registry.get(ambiguous)
        self.assertIsNot(connector_registry.get("bidx"), MarylandEMMAConnector)
        self.assertIsNot(connector_registry.get("bonfire"), MarylandEMMAConnector)

    def test_profile_validation_state_and_url_safety(self):
        self.assertTrue(
            MarylandEMMAConnector(
                FIXTURE_PROFILE, transport=FakeTransport([])
            ).health.configuration_valid
        )
        for state in ("active", "configured_unverified", "legacy", "migrated", "unavailable"):
            self.assertIsInstance(
                replace(FIXTURE_PROFILE, profile_status=state), MarylandEMMAProfile
            )
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, page_size=0)
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, profile_status="bad")
        bad = replace(FIXTURE_PROFILE, discovery_url="https://evil.example/search")
        self.assertFalse(
            MarylandEMMAConnector(bad, transport=FakeTransport([])).health.configuration_valid
        )

    def test_page_aspx_state_and_external_platform_helpers(self):
        self.assertEqual(parse_aspnet_state(LISTING)["__VIEWSTATEGENERATOR"], "A1B2")
        self.assertEqual(external_platform("https://bidexpress.com/x"), "bidx")
        self.assertEqual(external_platform("https://x.bonfirehub.com/x"), "bonfire")
        self.assertEqual(external_platform("https://bidlocker.us/x"), "bid-locker")

    async def test_discovery_detail_normalization_provenance_and_documents(self):
        c, _, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, LISTING),
                response(FIXTURE_PROFILE.detail_url("n-2026-002"), NOTICE),
                response(FIXTURE_PROFILE.detail_url("p-2026-001"), DETAIL),
            ]
        )
        self.assertEqual(len(items), 2)
        item = next(x for x in items if x.solicitation_number == "MDH-26-100")
        self.assertEqual(item.source.source_id, "maryland/emma:maryland-statewide:p-2026-001")
        self.assertEqual(item.raw_payload["unspsc_codes"], ["77121700"])
        self.assertIn("source_provenance", item.raw_payload)
        docs = c.document_candidates(item)
        self.assertTrue(c.document_pipeline_compatible)
        self.assertEqual(len(docs), 6)
        self.assertEqual(docs[0].filename, "RFP_26_100.pdf")
        self.assertEqual(docs[-1].access_state, AccessState.VENDOR_PROFILE_REQUIRED)
        self.assertFalse(docs[-1].publicly_retrievable)
        self.assertEqual(
            {d.category for d in docs},
            {
                "solicitation",
                "addendum",
                "questions_and_answers",
                "bid_tabulation",
                "award_notice",
                "other",
            },
        )

    async def test_filters_duplicates_stable_order_empty_and_bounds(self):
        q = MarylandEMMAQuery(
            include_details=False,
            agency="Health",
            unspsc="77121700",
            certification="SBR",
            solicitation_number="MDH-26-100",
            project_number="BPM-001",
        )
        _, transport, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)], q
        )
        self.assertEqual((len(items), len(transport.calls)), (1, 1))
        _, _, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            MarylandEMMAQuery(include_details=False, maximum_results=1),
        )
        self.assertEqual(len(items), 1)
        empty = (FIXTURES / "maryland_emma_empty.html").read_text()
        _, _, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, empty)],
            MarylandEMMAQuery(include_details=False),
        )
        self.assertEqual(items, [])

    async def test_changed_markup_and_access_boundaries_fail_closed_without_retry(self):
        changed = (FIXTURES / "maryland_emma_changed_markup.html").read_text()
        with self.assertRaises(MarylandEMMAAccessError) as caught:
            await self.collect(
                [response(FIXTURE_PROFILE.discovery_url, changed)],
                MarylandEMMAQuery(include_details=False),
            )
        self.assertEqual(caught.exception.state, MarylandEMMAAccessState.CHANGED_MARKUP)
        cases = (
            ("CAPTCHA challenge", MarylandEMMAAccessState.CAPTCHA_REQUIRED),
            ("Sign in to continue", MarylandEMMAAccessState.LOGIN_REQUIRED),
            ("Registration required", MarylandEMMAAccessState.REGISTRATION_REQUIRED),
            ("Add to My Solicitations", MarylandEMMAAccessState.VENDOR_PROFILE_REQUIRED),
        )
        for text, state in cases:
            self.assertEqual(detect_access_boundary(text), state)
            transport = FakeTransport([response(FIXTURE_PROFILE.discovery_url, text)])
            with self.assertRaises(MarylandEMMAAccessError):
                [
                    x
                    async for x in MarylandEMMAConnector(
                        FIXTURE_PROFILE, transport=transport
                    ).discover(MarylandEMMAQuery(include_details=False))
                ]
            self.assertEqual(len(transport.calls), 1)

    async def test_retry_health_circuit_and_lifecycle(self):
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        c, _, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, "busy", 503, {"retry-after": "2"}),
                response(FIXTURE_PROFILE.discovery_url, LISTING),
            ],
            MarylandEMMAQuery(include_details=False),
            sleep=sleep,
        )
        self.assertEqual((len(items), sleeps, c.health.consecutive_failures), (2, [2.0], 0))
        profile = replace(FIXTURE_PROFILE, retries=0, circuit_threshold=1)
        c = MarylandEMMAConnector(profile, transport=FakeTransport([httpx.ConnectError("offline")]))
        with self.assertRaises(MarylandEMMAError):
            [x async for x in c.discover(MarylandEMMAQuery(include_details=False))]
        self.assertTrue(c.health.circuit_open)
        owned = MarylandEMMAConnector(FIXTURE_PROFILE)
        await owned.aclose()
        self.assertTrue(owned._transport.is_closed)
        injected = FakeTransport([])
        external = MarylandEMMAConnector(FIXTURE_PROFILE, transport=injected)
        await external.aclose()
        self.assertFalse(injected.closed)

    async def test_migrated_and_unavailable_profiles_do_not_collect(self):
        for state in ("migrated", "unavailable"):
            with self.assertRaises(MarylandEMMAAccessError):
                await self.collect([], profile=replace(FIXTURE_PROFILE, profile_status=state))

    def test_malformed_embedded_json_is_not_treated_as_data(self):
        items, links = parse_page('<script type="application/json">{bad</script>')
        self.assertEqual((items, links), ([], []))


if __name__ == "__main__":
    unittest.main()
