import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from sled_aggregator.connectors.base import ConnectorQuery
from sled_aggregator.connectors.infotech import (
    BIDX_AGENCIES,
    InfotechAvailabilityError,
    InfotechBidExpressConnector,
    InfotechBidExpressPortal,
    InfotechError,
    InfotechPlatformVariant,
    InfotechRestrictedError,
)

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS = json.loads((FIXTURES / "infotech_results.json").read_text())


class Transport:
    def __init__(self, responses: list[Any]):
        self.responses, self.calls, self.closed = responses, [], False

    async def get(self, url: str, *, params: dict[str, Any]) -> httpx.Response:
        self.calls.append((url, dict(params)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body, kind, headers = item
        request = httpx.Request("GET", url, params=params)
        if kind == "application/json" and not isinstance(body, str):
            return httpx.Response(
                status, json=body, headers={"content-type": kind, **headers}, request=request
            )
        return httpx.Response(
            status, text=body, headers={"content-type": kind, **headers}, request=request
        )

    async def aclose(self):
        self.closed = True


def response(body: Any, status=200, kind="application/json", **headers: str):
    return status, body, kind, headers


def portal(strategy="json", **changes):
    values = dict(
        agency_name="Fixture DOT",
        jurisdiction="Example",
        agency_identifier="EX",
        platform_variant=InfotechPlatformVariant.BIDX_MODERN,
        public_base_url="https://example.test",
        listing_url="https://example.test/search",
        response_strategy=strategy,
        fetch_details=False,
        verification_status="fixture-tested",
    )
    values.update(changes)
    return InfotechBidExpressPortal(**values)


async def collect(connector, query=None):
    return [x async for x in connector.discover(query or ConnectorQuery())]


class InfotechTests(unittest.IsolatedAsyncioTestCase):
    def test_variants_and_configured_directory_coverage(self):
        self.assertEqual(len(InfotechPlatformVariant), 5)
        self.assertEqual(len(BIDX_AGENCIES), 43)
        self.assertTrue(all(x.verification_status == "configured-only" for x in BIDX_AGENCIES))
        self.assertTrue(all(x.agency_identifier is None for x in BIDX_AGENCIES))
        self.assertIn("New Jersey", {x.jurisdiction for x in BIDX_AGENCIES})

    async def test_json_normalization_identity_documents_and_payload(self):
        items = await collect(
            InfotechBidExpressConnector(portal(), transport=Transport([response(RESULTS)]))
        )
        item = items[0]
        self.assertEqual(item.source.source_id, "EX:P-100")
        self.assertEqual(item.solicitation_number, "DOT-24-10")
        self.assertEqual(item.raw_payload["route"], "US 1")
        docs = item.raw_payload["document_links"]
        self.assertEqual(
            [x["access_state"] for x in docs], ["public", "public", "subscription-required"]
        )
        self.assertEqual(docs[1]["apparent_file_type"], "csv")

    async def test_csv_xml_and_html_table_strategies(self):
        cases = [
            ("csv", "id,title,agency\nC-1,CSV road,County\n", "text/csv"),
            (
                "xml",
                "<root><proposal><id>X-1</id><title>XML bridge</title></proposal></root>",
                "application/xml",
            ),
            ("html", (FIXTURES / "infotech_lettings.html").read_text(), "text/html"),
        ]
        for strategy, body, kind in cases:
            with self.subTest(strategy=strategy):
                items = await collect(
                    InfotechBidExpressConnector(
                        portal(strategy), transport=Transport([response(body, kind=kind)])
                    )
                )
                self.assertEqual(len(items), 1)

    async def test_pagination_duplicates_repeated_page_and_limit(self):
        page = {"results": [{"id": str(i), "title": f"Job {i}"} for i in range(2)]}
        transport = Transport([response(page), response(page)])
        items = await collect(
            InfotechBidExpressConnector(portal(), transport=transport, page_size=2, max_pages=5),
            ConnectorQuery(limit=10),
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(len(transport.calls), 2)

    async def test_empty_bad_shape_malformed_and_missing_fields(self):
        connector = InfotechBidExpressConnector(
            portal(), transport=Transport([response({"results": []})])
        )
        self.assertEqual(await collect(connector), [])
        connector = InfotechBidExpressConnector(
            portal(), transport=Transport([response({"results": [{"id": "1"}, {"title": "x"}]})])
        )
        self.assertEqual(await collect(connector), [])
        self.assertEqual(connector.health.skipped_records, 2)
        for body in ("{bad", {"wrong": []}):
            with self.assertRaises(InfotechError):
                await collect(
                    InfotechBidExpressConnector(portal(), transport=Transport([response(body)]))
                )

    async def test_access_boundaries_are_not_empty_results(self):
        cases = [
            ("Vendor Login", "login-required"),
            ("Create an account", "registration-required"),
            ("Subscription required", "subscription-required"),
            ("Payment required", "payment-required"),
            ("Digital ID required", "digital-id-required"),
            ("reCAPTCHA", "captcha-blocked"),
        ]
        for body, state in cases:
            connector = InfotechBidExpressConnector(
                portal("html"), transport=Transport([response(body, kind="text/html")])
            )
            with self.subTest(state=state), self.assertRaises(InfotechRestrictedError):
                await collect(connector)
            self.assertEqual(connector.health.access_state, state)
        connector = InfotechBidExpressConnector(
            portal(), transport=Transport([response("no", 403, "text/plain")])
        )
        with self.assertRaises(InfotechRestrictedError):
            await collect(connector)
        self.assertEqual(connector.health.access_state, "forbidden")

    async def test_retries_circuit_recovery_and_ownership(self):
        delays = []

        async def sleep(value):
            delays.append(value)

        now = [datetime(2026, 7, 29, tzinfo=UTC)]
        connector = InfotechBidExpressConnector(
            portal(),
            transport=Transport(
                [response({}, 429, **{"retry-after": "2"}), response({}, 503), response(RESULTS)]
            ),
            max_retries=2,
            sleep=sleep,
            backoff_seconds=0,
            jitter_seconds=0,
            now=lambda: now[0],
        )
        self.assertEqual(len(await collect(connector)), 1)
        self.assertEqual(delays, [2, 0])
        recovery = InfotechBidExpressConnector(
            portal(),
            transport=Transport([response({}, 502), response({}, 504), response(RESULTS)]),
            max_retries=0,
            circuit_breaker_threshold=2,
            circuit_breaker_cooldown=5,
            now=lambda: now[0],
        )
        for _ in range(2):
            with self.assertRaises(InfotechAvailabilityError):
                await collect(recovery)
        self.assertTrue(recovery.health.circuit_open)
        now[0] += timedelta(seconds=6)
        self.assertEqual(len(await collect(recovery)), 1)
        injected = Transport([])
        await InfotechBidExpressConnector(portal(), transport=injected).aclose()
        self.assertFalse(injected.closed)
        owned = Transport([])
        with patch("sled_aggregator.connectors.infotech.httpx.AsyncClient", return_value=owned):
            item = InfotechBidExpressConnector(portal())
            await item.aclose()
        self.assertTrue(owned.closed)

    async def test_link_only_fallback_and_jurisdiction_filter(self):
        configured = BIDX_AGENCIES[0]
        connector = InfotechBidExpressConnector(configured, transport=Transport([]))
        self.assertEqual(await collect(connector), [])
        self.assertEqual(configured.public_listing_or_fallback_url, configured.directory_url)
        self.assertEqual(
            await collect(
                InfotechBidExpressConnector(portal(), transport=Transport([])),
                ConnectorQuery(jurisdiction="Elsewhere"),
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
