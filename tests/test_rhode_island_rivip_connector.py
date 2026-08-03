import unittest
from dataclasses import replace
from pathlib import Path

import httpx

from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.connectors.rhode_island_rivip import (
    FIXTURE_PROFILE,
    PublicWebFormsNavigator,
    RIVIPAccessError,
    RIVIPError,
    RIVIPExternalConnector,
    RIVIPProfile,
    RIVIPQuery,
    detect_boundary,
)

FIXTURES = Path(__file__).parent / "fixtures"
INITIAL = (FIXTURES / "rivip_external_initial.html").read_text()
RESULTS = (FIXTURES / "rivip_external_results.html").read_text()
DETAIL = (FIXTURES / "rivip_external_detail.html").read_text()
MIGRATED = (FIXTURES / "rivip_external_migrated_detail.html").read_text()


def response(url, text):
    return httpx.Response(200, text=text, request=httpx.Request("GET", url))


class FakeTransport:
    def __init__(self, gets=(), posts=()):
        self.gets, self.posts = list(gets), list(posts)
        self.get_calls, self.post_calls, self.closed = [], [], False

    async def get(self, url):
        self.get_calls.append(url)
        return response(url, self.gets.pop(0))

    async def post(self, url, *, data):
        self.post_calls.append((url, data))
        return response(url, self.posts.pop(0))

    async def aclose(self):
        self.closed = True


class RIVIPTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_aliases_and_separation(self):
        for name in (
            "rhode-island/rivip-external",
            "ri-rivip-external",
            "rhode-island-rivip",
            "rivip-external",
            "ri-external-solicitations",
            "rhode-island-external-solicitations",
        ):
            self.assertIs(connector_registry.get(name), RIVIPExternalConnector)
        for broad in ("rivip", "rhode-island", "ri", "external", "aspnet", "webforms"):
            with self.assertRaises(KeyError):
                connector_registry.get(broad)
        self.assertIsNot(connector_registry.get("webprocure/proactis"), RIVIPExternalConnector)
        self.assertIsNot(connector_registry.get("bidnet-direct"), RIVIPExternalConnector)

    def test_profiles_validate_current_legacy_migration_and_hosts(self):
        for state in (
            "active",
            "legacy",
            "migrated",
            "dual_published",
            "configured_unverified",
            "unavailable",
        ):
            self.assertIsInstance(replace(FIXTURE_PROFILE, source_state=state), RIVIPProfile)
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, maximum_pages=0)
        with self.assertRaises(ValueError):
            replace(FIXTURE_PROFILE, search_url="https://evil.example/search")

    async def test_end_to_end_discovery_identity_documents_and_migration(self):
        transport = FakeTransport(gets=[INITIAL, DETAIL, MIGRATED], posts=[RESULTS])
        connector = RIVIPExternalConnector(transport=transport)
        items = [item async for item in connector.discover(RIVIPQuery(keyword="water"))]
        self.assertEqual(len(items), 2)
        current = items[0]
        self.assertEqual(
            current.source.source_id, "rhode-island/rivip-external:city-of-providence:1001"
        )
        self.assertEqual(current.solicitation_number, "PVD-26-01")
        self.assertEqual(current.raw_payload["entity_type"], "city")
        docs = connector.document_candidates(current)
        self.assertTrue(connector.document_pipeline_compatible)
        self.assertEqual(
            [d.category for d in docs], ["solicitation", "addendum", "public_bid_response"]
        )
        self.assertTrue(docs[0].publicly_retrievable)
        self.assertEqual(docs[1].addendum_number, "1")
        self.assertFalse(docs[2].publicly_retrievable)
        self.assertNotIn("href", docs[0].raw_metadata)
        self.assertEqual(items[1].raw_payload["source_state"], "migrated")
        self.assertEqual(items[1].raw_payload["replacement_platform"], "RhodyBuy/JAGGAER")
        self.assertEqual(len(transport.post_calls), 1)
        posted = transport.post_calls[0][1]
        self.assertEqual(posted["__VIEWSTATE"], "SANITIZED-STATE-1")
        self.assertNotIn("SANITIZED-STATE-1", repr(current.raw_payload))

    async def test_webforms_allowlist_state_refresh_and_bounds(self):
        transport = FakeTransport(gets=[INITIAL], posts=[RESULTS])
        nav = PublicWebFormsNavigator(FIXTURE_PROFILE, transport)
        await nav.initialize()
        page = await nav.submit({"keyword": "roads", "search": "Search"})
        self.assertEqual(nav.state["__VIEWSTATE"], "SANITIZED-STATE-2")
        self.assertEqual(len(page.rows), 2)
        with self.assertRaises(RIVIPError):
            await nav.submit({"agencyLogin": "Login"})
        with self.assertRaises(RIVIPError):
            await nav.submit({}, event_target="admin$delete")

    def test_missing_state_boundaries_and_changed_markup_fail_closed(self):
        nav = PublicWebFormsNavigator(FIXTURE_PROFILE, FakeTransport())
        for html in ("<main id='rivip-external-results'></main>", "<malformed>"):
            with self.assertRaises(RIVIPAccessError):
                nav.refresh(html)
        cases = {
            "CAPTCHA challenge": "captcha_required",
            "Agency Login password": "login_required",
            "Validation of viewstate MAC failed": "expired_view_state",
            "Invalid postback or callback argument": "invalid_event_validation",
            "Session has expired": "unavailable",
        }
        for html, expected in cases.items():
            self.assertEqual(detect_boundary(html), expected)

    async def test_empty_duplicates_result_bounds_and_lifecycle(self):
        empty = INITIAL.replace("</form>", "</form><section id='rivip-external-results'></section>")
        transport = FakeTransport(gets=[INITIAL], posts=[empty])
        items = [
            x
            async for x in RIVIPExternalConnector(transport=transport).discover(
                RIVIPQuery(keyword="none")
            )
        ]
        self.assertEqual(items, [])
        transport = FakeTransport(gets=[INITIAL], posts=[RESULTS])
        items = [
            x
            async for x in RIVIPExternalConnector(transport=transport).discover(
                RIVIPQuery(keyword="x", include_details=False, maximum_results=1)
            )
        ]
        self.assertEqual(len(items), 1)
        injected = FakeTransport()
        await RIVIPExternalConnector(transport=injected).aclose()
        self.assertFalse(injected.closed)

    async def test_migrated_and_unavailable_profiles_do_not_collect(self):
        for state in ("migrated", "unavailable"):
            with self.assertRaises(RIVIPAccessError):
                [
                    x
                    async for x in RIVIPExternalConnector(
                        replace(FIXTURE_PROFILE, source_state=state), transport=FakeTransport()
                    ).discover(RIVIPQuery(keyword="x"))
                ]


if __name__ == "__main__":
    unittest.main()
