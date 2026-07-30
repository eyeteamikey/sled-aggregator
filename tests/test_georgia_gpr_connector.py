import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from sled_aggregator.connectors.georgia_gpr import (
    FIXTURE_PROFILE,
    GeorgiaGPRAccessError,
    GeorgiaGPRAccessState,
    GeorgiaGPRConnector,
    GeorgiaGPRError,
    GeorgiaGPRProfile,
    GeorgiaGPRQuery,
    detect_access_boundary,
    external_platform,
    parse_page,
)
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import AccessState, OpportunityStatus

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "georgia_gpr_listing.html").read_text()
DETAIL = (FIXTURES / "georgia_gpr_detail.html").read_text()


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


class GeorgiaGPRTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, profile=FIXTURE_PROFILE, **kwargs):
        transport = FakeTransport(replies)
        connector = GeorgiaGPRConnector(profile, transport=transport, **kwargs)
        items = [x async for x in connector.discover(query or GeorgiaGPRQuery())]
        return connector, transport, items

    def test_registry_canonical_aliases_broad_rejection_and_separation(self):
        for alias in (
            "georgia/gpr",
            "georgia-gpr",
            "ga-gpr",
            "georgia-procurement-registry",
            "ga-procurement-registry",
            "gpr-georgia",
        ):
            self.assertIs(connector_registry.get(alias), GeorgiaGPRConnector)
        for broad in ("gpr", "georgia", "registry", "ga", "gawork", "marketplace"):
            with self.assertRaises(KeyError):
                connector_registry.get(broad)
        for adjacent in ("peoplesoft", "jaggaer", "bidx"):
            self.assertIsNot(connector_registry.get(adjacent), GeorgiaGPRConnector)
        self.assertTrue(GeorgiaGPRConnector.public_read_only)

    def test_profile_validation_transition_and_replacement_metadata(self):
        self.assertTrue(
            GeorgiaGPRConnector(
                FIXTURE_PROFILE, transport=FakeTransport([])
            ).health.configuration_valid
        )
        for state in ("active", "legacy", "migrated", "configured_unverified", "unavailable"):
            profile = replace(
                FIXTURE_PROFILE,
                profile_status=state,
                replacement_platform="GA@WORK",
                replacement_url="https://doas.ga.gov/state-purchasing",
            )
            self.assertIsInstance(profile, GeorgiaGPRProfile)
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, page_size=0)
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, profile_status="invalid")
        unsafe = replace(FIXTURE_PROFILE, discovery_url="https://127.0.0.1/private")
        self.assertFalse(
            GeorgiaGPRConnector(unsafe, transport=FakeTransport([])).health.configuration_valid
        )

    def test_source_system_classification(self):
        cases = {
            "https://ssl.doas.state.ga.us/gpr/event": "gpr_direct",
            "https://sourcing.gawork.com/event/1": "gawork_marketplace",
            "https://teamgeorgia.example/tgm/1": "team_georgia_marketplace",
            "https://example.com/psp/event": "peoplesoft",
            "https://example.com/esource/event": "esource",
            "https://solutions.sciquest.com/event": "jaggaer_sourcing_director",
            "https://bidexpress.com/event": "bid_express",
            "https://procurement.example.gov/event": "agency_hosted",
            "https://vendor.example/event": "external_portal",
        }
        for url, expected in cases.items():
            self.assertEqual(external_platform(url), expected)

    async def test_discovery_detail_identity_provenance_and_transition(self):
        c, _, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, LISTING),
                response(
                    FIXTURE_PROFILE.detail_url("ga-003"), DETAIL.replace('"GA-001"', '"GA-003"')
                ),
                response(
                    FIXTURE_PROFILE.detail_url("ga-002"), DETAIL.replace('"GA-001"', '"GA-002"')
                ),
                response(FIXTURE_PROFILE.detail_url("ga-001"), DETAIL),
            ]
        )
        self.assertEqual(len(items), 3)
        item = next(x for x in items if x.source.source_id.endswith(":ga-001"))
        self.assertEqual(item.source.platform_family, "georgia/gpr")
        self.assertEqual(item.raw_payload["upstream_sourcing_system"], "gawork_marketplace")
        self.assertEqual(item.raw_payload["transition_state"], "dual_published")
        self.assertEqual(item.raw_payload["nigp_codes"], ["20464"])
        self.assertIn("source_provenance", item.raw_payload)
        self.assertEqual(item.raw_payload["access_state"], "external_response_system")
        docs = c.document_candidates(item)
        self.assertEqual(len(docs), 3)
        self.assertEqual(docs[1].filename, "Addendum_1.pdf")
        self.assertEqual(sum(d.publicly_retrievable for d in docs), 2)
        self.assertEqual(docs[-1].access_state, AccessState.LOGIN_REQUIRED)

    async def test_statuses_and_fixture_verified_filters(self):
        _, _, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            GeorgiaGPRQuery(include_details=False),
        )
        self.assertEqual(
            {x.status for x in items},
            {OpportunityStatus.OPEN, OpportunityStatus.CLOSED, OpportunityStatus.AWARDED},
        )
        queries = (
            GeorgiaGPRQuery(
                include_details=False,
                keywords=("network",),
                title="Statewide",
                description="managed",
                response_type="RFP",
                government_type="State",
                entity="Administrative",
                nigp="20464",
            ),
            GeorgiaGPRQuery(include_details=False, status="awarded", awarded_from=date(2026, 7, 1)),
            GeorgiaGPRQuery(
                include_details=False,
                solicitation_number="IFB-77",
                agency="County",
                posted_from=date(2026, 6, 1),
                due_to=date(2026, 7, 31),
            ),
        )
        for query in queries:
            _, _, filtered = await self.collect(
                [response(FIXTURE_PROFILE.discovery_url, LISTING)], query
            )
            self.assertEqual(len(filtered), 1)

    async def test_empty_malformed_changed_markup_and_walls_fail_closed(self):
        empty = (FIXTURES / "georgia_gpr_empty.html").read_text()
        _, _, items = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, empty)], GeorgiaGPRQuery(include_details=False)
        )
        self.assertEqual(items, [])
        for text, state in (
            ("Sign in to continue", GeorgiaGPRAccessState.LOGIN_REQUIRED),
            ("Registration required", GeorgiaGPRAccessState.REGISTRATION_REQUIRED),
            ("access denied", GeorgiaGPRAccessState.RESTRICTED),
        ):
            self.assertEqual(detect_access_boundary(text), state)
            with self.assertRaises(GeorgiaGPRAccessError):
                await self.collect(
                    [response(FIXTURE_PROFILE.discovery_url, text)],
                    GeorgiaGPRQuery(include_details=False),
                )
        changed = (FIXTURES / "georgia_gpr_changed_markup.html").read_text()
        with self.assertRaises(GeorgiaGPRAccessError) as caught:
            await self.collect(
                [response(FIXTURE_PROFILE.discovery_url, changed)],
                GeorgiaGPRQuery(include_details=False),
            )
        self.assertEqual(caught.exception.state, GeorgiaGPRAccessState.CHANGED_MARKUP)
        self.assertEqual(parse_page('<script type="application/json">{bad</script>')[0], [])

    async def test_duplicate_suppression_repeated_page_and_result_bound(self):
        paged = LISTING.replace(
            "</main>", '<a href="?page=2" data-document-type="next">Next</a></main>'
        )
        _, transport, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, paged),
                response(FIXTURE_PROFILE.discovery_url, paged),
            ],
            GeorgiaGPRQuery(include_details=False, maximum_results=2),
        )
        self.assertEqual((len(items), len(transport.calls)), (2, 1))
        _, _, one = await self.collect(
            [response(FIXTURE_PROFILE.discovery_url, LISTING)],
            GeorgiaGPRQuery(include_details=False, maximum_results=1),
        )
        self.assertEqual(len(one), 1)

    async def test_retry_after_health_circuit_and_no_permanent_retry(self):
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        c, transport, items = await self.collect(
            [
                response(FIXTURE_PROFILE.discovery_url, "busy", 503, {"retry-after": "2"}),
                response(FIXTURE_PROFILE.discovery_url, LISTING),
            ],
            GeorgiaGPRQuery(include_details=False),
            sleep=sleep,
        )
        self.assertEqual((len(items), sleeps, c.health.consecutive_failures), (3, [2.0], 0))
        for status in (401, 403):
            transport = FakeTransport([response(FIXTURE_PROFILE.discovery_url, "wall", status)])
            with self.assertRaises(GeorgiaGPRAccessError):
                [
                    x
                    async for x in GeorgiaGPRConnector(
                        FIXTURE_PROFILE, transport=transport
                    ).discover(GeorgiaGPRQuery(include_details=False))
                ]
            self.assertEqual(len(transport.calls), 1)
        profile = replace(FIXTURE_PROFILE, retries=0, circuit_threshold=1)
        c = GeorgiaGPRConnector(
            profile,
            transport=FakeTransport([httpx.ConnectError("offline")]),
            now=lambda: datetime.now(UTC),
        )
        with self.assertRaises(GeorgiaGPRError):
            [x async for x in c.discover(GeorgiaGPRQuery(include_details=False))]
        self.assertTrue(c.health.circuit_open)

    async def test_client_lifecycle_and_inactive_profiles(self):
        owned = GeorgiaGPRConnector(FIXTURE_PROFILE)
        await owned.aclose()
        self.assertTrue(owned._transport.is_closed)
        injected = FakeTransport([])
        await GeorgiaGPRConnector(FIXTURE_PROFILE, transport=injected).aclose()
        self.assertFalse(injected.closed)
        for state in ("legacy", "migrated", "unavailable"):
            with self.assertRaises(GeorgiaGPRAccessError):
                await self.collect([], profile=replace(FIXTURE_PROFILE, profile_status=state))


if __name__ == "__main__":
    unittest.main()
