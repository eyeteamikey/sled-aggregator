import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from sled_aggregator.connectors.base import ConnectorQuery
from sled_aggregator.connectors.periscope import (
    ILLINOIS,
    MASSACHUSETTS,
    NEVADA,
    NEW_JERSEY,
    OREGON,
    PORTALS,
    US_VIRGIN_ISLANDS,
    PeriscopeAvailabilityError,
    PeriscopeBuySpeedConnector,
    PeriscopeError,
    PeriscopePortal,
    PeriscopeRestrictedError,
)

FIXTURES = Path(__file__).parent / "fixtures"
JSON_RESULTS = json.loads((FIXTURES / "periscope_results.json").read_text())
HTML_RESULTS = (FIXTURES / "periscope_board.html").read_text()


class FakeTransport:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def get(self, url: str, *, params: dict[str, Any]) -> httpx.Response:
        self.calls.append({"url": url, "params": dict(params)})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body, content_type, headers = item
        request = httpx.Request("GET", url, params=params)
        if content_type == "application/json" and not isinstance(body, str):
            return httpx.Response(
                status,
                json=body,
                headers={"content-type": content_type, **headers},
                request=request,
            )
        return httpx.Response(
            status, text=body, headers={"content-type": content_type, **headers}, request=request
        )

    async def aclose(self) -> None:
        self.closed = True


def response(body: Any, status: int = 200, content_type: str = "application/json", **headers: str):
    return status, body, content_type, headers


def portal(strategy: str = "json", **changes: Any) -> PeriscopePortal:
    values = dict(
        jurisdiction="Illinois",
        jurisdiction_code="IL",
        name="Fixture BuySpeed",
        base_url="https://example.test/",
        search_url="https://example.test/search",
        platform_variant="fixture",
        response_strategy=strategy,
    )
    values.update(changes)
    return PeriscopePortal(**values)


async def collect(connector: PeriscopeBuySpeedConnector, query: ConnectorQuery | None = None):
    return [item async for item in connector.discover(query or ConnectorQuery())]


class PeriscopeConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_six_safe_public_portal_presets(self) -> None:
        self.assertEqual(
            PORTALS, (ILLINOIS, MASSACHUSETTS, NEVADA, NEW_JERSEY, OREGON, US_VIRGIN_ISLANDS)
        )
        self.assertEqual(
            {item.jurisdiction_code for item in PORTALS}, {"IL", "MA", "NV", "NJ", "OR", "VI"}
        )
        self.assertTrue(all(item.search_url.startswith("https://") for item in PORTALS))
        self.assertEqual(len({item.profile_key for item in PORTALS}), len(PORTALS))
        self.assertTrue(all(item.profile_key for item in PORTALS))
        self.assertTrue(all(not item.production_verified for item in PORTALS))

    async def test_statewide_profiles_normalize_the_shared_fixture_contract(self) -> None:
        for configured_portal in PORTALS:
            with self.subTest(profile=configured_portal.profile_key):
                transport = FakeTransport([response(HTML_RESULTS, content_type="text/html")])
                items = await collect(
                    PeriscopeBuySpeedConnector(
                        configured_portal, transport=transport, fetch_details=False
                    )
                )
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0].source.jurisdiction, configured_portal.jurisdiction)
                self.assertEqual(transport.calls[0]["url"], configured_portal.search_url)
                self.assertEqual(len(items[0].raw_payload["document_links"]), 1)

    async def test_json_keyword_normalization_provenance_and_document_links(self) -> None:
        transport = FakeTransport([response(JSON_RESULTS)])
        connector = PeriscopeBuySpeedConnector(portal(), transport=transport, fetch_details=False)
        items = await collect(connector, ConnectorQuery(keywords=("network", "services")))
        item = items[0]
        self.assertEqual(transport.calls[0]["params"]["q"], "network services")
        self.assertEqual(item.source.source_id, "IL-100")
        self.assertEqual(item.solicitation_number, "RFP-2026-100")
        self.assertEqual(item.categories, ["920-00"])
        self.assertEqual(item.due_at, datetime(2026, 8, 15, 16, tzinfo=UTC))
        self.assertEqual(item.raw_payload["unfamiliarSourceField"], "preserved")
        self.assertEqual(item.raw_payload["document_links"][0]["access_state"], "public")
        self.assertIn("spec.pdf", item.raw_payload["document_links"][0]["url"])
        self.assertEqual(connector.health.last_success_at is not None, True)

    async def test_html_board_and_fallback_url(self) -> None:
        transport = FakeTransport([response(HTML_RESULTS, content_type="text/html")])
        items = await collect(
            PeriscopeBuySpeedConnector(portal("html"), transport=transport, fetch_details=False)
        )
        self.assertEqual(items[0].source.source_id, "OR-42")
        self.assertIn("/bids/OR-42", str(items[0].source.opportunity_url))
        self.assertEqual(items[0].raw_payload["document_links"][0]["access_state"], "public")

    async def test_pagination_duplicates_repeat_stop_and_limits(self) -> None:
        page1 = {"results": [{"id": "1", "title": "One"}, {"id": "2", "title": "Two"}]}
        page2 = {"results": [{"id": "2", "title": "Two"}, {"id": "3", "title": "Three"}]}
        transport = FakeTransport([response(page1), response(page2), response(page2)])
        items = await collect(
            PeriscopeBuySpeedConnector(
                portal(),
                transport=transport,
                page_size=2,
                max_pages=8,
                max_results=3,
                fetch_details=False,
            ),
            ConnectorQuery(limit=20),
        )
        self.assertEqual([item.source.source_id for item in items], ["1", "2", "3"])
        self.assertEqual([call["params"]["page"] for call in transport.calls], [1, 2])

    async def test_public_detail_page_enriches_sparse_list_record(self) -> None:
        listing = {"results": [{"id": "D-1", "title": "Sparse", "url": "/D-1"}]}
        detail = """<article class="opportunity" data-id="D-1">
        <span data-field="title">Sparse</span><span data-field="description">Detail text</span>
        <a href="/docs/D-1-rfp.pdf">RFP document</a></article>"""
        transport = FakeTransport([response(listing), response(detail, content_type="text/html")])
        items = await collect(PeriscopeBuySpeedConnector(portal(), transport=transport))
        self.assertEqual(items[0].description, "Detail text")
        self.assertEqual(len(transport.calls), 2)

    async def test_empty_missing_fields_malformed_and_unexpected_json(self) -> None:
        self.assertEqual(
            await collect(
                PeriscopeBuySpeedConnector(
                    portal(), transport=FakeTransport([response({"results": []})])
                )
            ),
            [],
        )
        connector = PeriscopeBuySpeedConnector(
            portal(),
            transport=FakeTransport([response({"results": [{"id": "1"}, {"title": "No ID"}]})]),
        )
        self.assertEqual(await collect(connector), [])
        self.assertEqual(connector.health.skipped_records, 2)
        for body in ("{broken", {"wrong": []}):
            content_type = "application/json"
            with self.subTest(body=body), self.assertRaises(PeriscopeError):
                await collect(
                    PeriscopeBuySpeedConnector(
                        portal(),
                        transport=FakeTransport([response(body, content_type=content_type)]),
                    )
                )

    async def test_login_captcha_403_are_restricted_not_empty(self) -> None:
        for item in (
            response("<html>Vendor Login</html>", content_type="text/html"),
            response("<html>reCAPTCHA challenge</html>", content_type="text/html"),
            response("forbidden", 403, "text/plain"),
        ):
            connector = PeriscopeBuySpeedConnector(portal("html"), transport=FakeTransport([item]))
            with self.subTest(item=item), self.assertRaises(PeriscopeRestrictedError):
                await collect(connector)
            self.assertEqual(connector.health.access_state, "restricted")

    async def test_retries_retry_after_and_recovery(self) -> None:
        delays = []

        async def sleep(delay: float) -> None:
            delays.append(delay)

        now = datetime(2026, 7, 29, tzinfo=UTC)
        later = email_date = "Wed, 29 Jul 2026 00:00:07 GMT"
        transport = FakeTransport(
            [
                response({}, 429, **{"retry-after": "5"}),
                response({}, 503, **{"retry-after": later}),
                response(JSON_RESULTS),
            ]
        )
        connector = PeriscopeBuySpeedConnector(
            portal(),
            transport=transport,
            max_retries=2,
            backoff_seconds=0,
            jitter_seconds=0,
            sleep=sleep,
            now=lambda: now,
            fetch_details=False,
        )
        self.assertEqual(len(await collect(connector)), 1)
        self.assertEqual(delays, [5, 7])
        self.assertTrue(connector.health.available)
        self.assertEqual(email_date, later)

    async def test_all_transient_codes_connection_failure_and_circuit_recovery(self) -> None:
        clock = [datetime(2026, 7, 29, tzinfo=UTC)]
        request = httpx.Request("GET", "https://example.test")
        failures = [response({}, code) for code in (502, 503, 504)] + [
            httpx.ConnectError("down", request=request)
        ]
        connector = PeriscopeBuySpeedConnector(
            portal(),
            transport=FakeTransport(failures),
            max_retries=0,
            circuit_breaker_threshold=10,
            circuit_breaker_cooldown=10,
            now=lambda: clock[0],
            fetch_details=False,
        )
        for _ in range(4):
            with self.assertRaises(PeriscopeAvailabilityError):
                await collect(connector)
        self.assertEqual(connector.health.consecutive_failures, 4)

        recovery = PeriscopeBuySpeedConnector(
            portal(),
            transport=FakeTransport([response({}, 503), response({}, 503), response(JSON_RESULTS)]),
            max_retries=0,
            circuit_breaker_threshold=2,
            circuit_breaker_cooldown=10,
            now=lambda: clock[0],
            fetch_details=False,
        )
        for _ in range(2):
            with self.assertRaises(PeriscopeAvailabilityError):
                await collect(recovery)
        self.assertTrue(recovery.health.circuit_open)
        clock[0] += timedelta(seconds=11)
        self.assertEqual(len(await collect(recovery)), 1)
        self.assertEqual(recovery.health.consecutive_failures, 0)

    async def test_jurisdiction_fallback_and_transport_ownership(self) -> None:
        fallback = PeriscopeBuySpeedConnector(portal("fallback"), transport=FakeTransport([]))
        self.assertEqual(await collect(fallback), [])
        self.assertEqual(fallback.health.access_state, "unsupported")
        injected = FakeTransport([])
        await PeriscopeBuySpeedConnector(portal(), transport=injected).aclose()
        self.assertFalse(injected.closed)
        owned = FakeTransport([])
        with patch("sled_aggregator.connectors.periscope.httpx.AsyncClient", return_value=owned):
            connector = PeriscopeBuySpeedConnector(portal())
            await connector.aclose()
        self.assertTrue(owned.closed)


if __name__ == "__main__":
    unittest.main()
