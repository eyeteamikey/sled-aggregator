import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from sled_aggregator.connectors.base import ConnectorQuery
from sled_aggregator.connectors.webprocure import (
    CONNECTICUT,
    MISSOURI,
    RHODE_ISLAND,
    WebProcureAvailabilityError,
    WebProcureConnector,
    WebProcureError,
)
from sled_aggregator.domain.enums import OpportunityStatus

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "webprocure_results.json").read_text())


class FakeTransport:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def get(self, url: str, *, params: dict[str, Any]) -> httpx.Response:
        self.calls.append({"url": url, "params": dict(params)})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, body, headers = response
        request = httpx.Request("GET", url)
        return httpx.Response(status, json=body, headers=headers, request=request)

    async def aclose(self) -> None:
        self.closed = True


def response(body: Any, status: int = 200, **headers: str) -> tuple[int, Any, dict[str, str]]:
    return status, body, {"content-type": "application/json", **headers}


async def collect(connector: WebProcureConnector, query: ConnectorQuery | None = None):
    return [item async for item in connector.discover(query or ConnectorQuery())]


class WebProcureConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_portal_presets_and_rhode_island_oid(self) -> None:
        self.assertEqual((CONNECTICUT.customer_id, MISSOURI.customer_id), (51, 38))
        self.assertEqual(CONNECTICUT.profile_key, "connecticut/ctsource")
        self.assertEqual(CONNECTICUT.jurisdiction_code, "CT")
        self.assertEqual(RHODE_ISLAND.customer_id, 46)
        self.assertEqual(RHODE_ISLAND.profile_key, "rhode-island/ocean-state-procures")
        self.assertEqual(RHODE_ISLAND.owner_oid, 120002)
        self.assertIn("oid=120002", RHODE_ISLAND.bid_board_url)

    async def test_keyword_parameters_and_normalization(self) -> None:
        transport = FakeTransport([response(FIXTURE)])
        items = await collect(
            WebProcureConnector(CONNECTICUT, transport=transport),
            ConnectorQuery(keywords=("cloud", "testing")),
        )
        params = transport.calls[0]["params"]
        self.assertEqual(params["q"], "cloud testing")
        self.assertEqual(params["customerid"], 51)
        self.assertEqual(params["from"], 0)
        self.assertEqual(params["sort"], "r")
        self.assertEqual(params["f"], "")
        self.assertEqual(params["oids"], -1)
        item = items[0]
        self.assertEqual(item.source.source_id, "CT-100")
        self.assertEqual(item.title, "Cloud testing services")
        self.assertEqual(item.agency, "Department of Administrative Services")
        self.assertEqual(item.solicitation_number, "RFP-2026-100")
        self.assertEqual(item.status, OpportunityStatus.OPEN)
        self.assertEqual(item.categories, ["IT Services"])
        self.assertEqual(item.due_at, datetime(2026, 8, 15, 16, tzinfo=UTC))
        self.assertEqual(item.raw_payload, FIXTURE["results"][0])
        self.assertIn("/CT-100", str(item.source.opportunity_url))

    async def test_wildcard_fallback_link_and_portal_jurisdiction(self) -> None:
        record = {"results": [{"id": "MO-1", "title": "Road work"}]}
        transport = FakeTransport([response(record)])
        items = await collect(WebProcureConnector(MISSOURI, transport=transport))
        self.assertEqual(transport.calls[0]["params"]["q"], "*")
        self.assertEqual(str(items[0].source.opportunity_url), MISSOURI.bid_board_url)
        self.assertEqual(items[0].source.jurisdiction, "Missouri")
        self.assertEqual(items[0].agency, MISSOURI.name)

    async def test_pagination_limit_and_duplicate_prevention(self) -> None:
        first = {"results": [{"id": "1", "title": "One"}, {"id": "2", "title": "Two"}]}
        second = {"results": [{"id": "2", "title": "Two"}, {"id": "3", "title": "Three"}]}
        transport = FakeTransport([response(first), response(second)])
        items = await collect(
            WebProcureConnector(CONNECTICUT, transport=transport, page_size=2, max_pages=4),
            ConnectorQuery(limit=3),
        )
        self.assertEqual([item.source.source_id for item in items], ["1", "2", "3"])
        self.assertEqual([call["params"]["from"] for call in transport.calls], [0, 2])

    async def test_jurisdiction_mismatch_makes_no_request(self) -> None:
        transport = FakeTransport([])
        items = await collect(
            WebProcureConnector(CONNECTICUT, transport=transport),
            ConnectorQuery(jurisdiction="Missouri"),
        )
        self.assertEqual(items, [])
        self.assertEqual(transport.calls, [])

    async def test_jurisdiction_code_routes_and_foreign_backlink_fails_closed(self) -> None:
        record = {
            "results": [
                {"id": "CT-1", "title": "Safe fallback", "url": "https://evil.example/bid"}
            ]
        }
        transport = FakeTransport([response(record)])
        items = await collect(
            WebProcureConnector(CONNECTICUT, transport=transport),
            ConnectorQuery(jurisdiction="CT"),
        )
        self.assertEqual(str(items[0].source.opportunity_url), CONNECTICUT.bid_board_url)

    async def test_missing_fields_and_malformed_shapes_are_rejected(self) -> None:
        for payload in ([{"id": "1"}], {"results": "bad"}, {"results": [{"id": "1"}]}):
            with self.subTest(payload=payload), self.assertRaises(WebProcureError):
                await collect(
                    WebProcureConnector(CONNECTICUT, transport=FakeTransport([response(payload)]))
                )

    async def test_retries_exponentially_after_502_and_503_then_recovers(self) -> None:
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)

        transport = FakeTransport([response({}, 502), response({}, 503), response(FIXTURE)])
        connector = WebProcureConnector(
            CONNECTICUT,
            transport=transport,
            max_retries=2,
            backoff_seconds=1,
            jitter_seconds=0,
            sleep=sleep,
        )
        self.assertEqual(len(await collect(connector)), 1)
        self.assertEqual(delays, [1, 2])
        self.assertTrue(connector.health.available)
        self.assertEqual(connector.health.consecutive_failures, 0)
        self.assertEqual(connector.health.last_status_code, 200)

    async def test_numeric_and_http_date_retry_after(self) -> None:
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)

        now = datetime(2026, 7, 28, tzinfo=UTC)
        date = "Tue, 28 Jul 2026 00:00:07 GMT"
        transport = FakeTransport(
            [
                response({}, 503, **{"retry-after": "5"}),
                response({}, 503, **{"retry-after": date}),
                response(FIXTURE),
            ]
        )
        await collect(
            WebProcureConnector(
                CONNECTICUT,
                transport=transport,
                max_retries=2,
                sleep=sleep,
                backoff_seconds=0,
                jitter_seconds=0,
                now=lambda: now,
            )
        )
        self.assertEqual(delays, [5, 7])

    async def test_circuit_breaker_and_health_reporting(self) -> None:
        now = datetime(2026, 7, 28, tzinfo=UTC)
        transport = FakeTransport([response({}, 503), response({}, 503)])
        connector = WebProcureConnector(
            CONNECTICUT,
            transport=transport,
            max_retries=0,
            circuit_breaker_threshold=2,
            now=lambda: now,
        )
        for _ in range(2):
            with self.assertRaises(WebProcureAvailabilityError):
                await collect(connector)
        health = connector.health
        self.assertFalse(health.available)
        self.assertTrue(health.circuit_open)
        self.assertEqual(health.consecutive_failures, 2)
        self.assertEqual(health.last_status_code, 503)
        self.assertEqual(health.last_failure_at, now)
        with self.assertRaises(WebProcureAvailabilityError):
            await collect(connector)
        self.assertEqual(len(transport.calls), 2)

    async def test_connection_failure_and_injected_transport_ownership(self) -> None:
        request = httpx.Request("GET", "https://example.test")
        transport = FakeTransport([httpx.ConnectError("down", request=request)])
        connector = WebProcureConnector(CONNECTICUT, transport=transport, max_retries=0)
        with self.assertRaises(WebProcureAvailabilityError):
            await collect(connector)
        await connector.aclose()
        self.assertFalse(transport.closed)

    async def test_non_json_and_malformed_json_are_rejected(self) -> None:
        class BadTransport(FakeTransport):
            async def get(self, url: str, *, params: dict[str, Any]) -> httpx.Response:
                self.calls.append({"url": url, "params": params})
                body, content_type = self.responses.pop(0)
                return httpx.Response(
                    200,
                    text=body,
                    headers={"content-type": content_type},
                    request=httpx.Request("GET", url),
                )

        for body, content_type in (
            ("<html>down</html>", "text/html"),
            ("{broken", "application/json"),
        ):
            with self.assertRaises(WebProcureError):
                await collect(
                    WebProcureConnector(CONNECTICUT, transport=BadTransport([(body, content_type)]))
                )


if __name__ == "__main__":
    unittest.main()
