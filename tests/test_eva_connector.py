import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from sled_aggregator.connectors.eva import (
    EVAAccessError,
    EVAAccessState,
    EVAAvailabilityError,
    EVAConnector,
    EVANoticeType,
    EVAQuery,
)
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import AccessState

FIXTURES = Path(__file__).parent / "fixtures"
BOARD = (FIXTURES / "eva_board.html").read_text()
DETAIL = (FIXTURES / "eva_detail_v2.html").read_text()


def response(body: str, status: int = 200, **headers: str) -> tuple[int, str, dict[str, str]]:
    return status, body, headers


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
        status, body, headers = item
        return httpx.Response(
            status,
            text=body,
            headers={"content-type": "text/html", **headers},
            request=httpx.Request("GET", url, params=params),
        )

    async def aclose(self) -> None:
        self.closed = True


async def collect(connector: EVAConnector, query: EVAQuery | None = None):
    return [item async for item in connector.discover(query or EVAQuery())]


class EVAConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_urls_search_params_round_consolidation_and_documents(self) -> None:
        transport = FakeTransport([response(BOARD), response(DETAIL)])
        connector = EVAConnector(
            transport=transport, page_size=25, fetch_details=True, max_details=1
        )
        url = connector.board_url(status="Open", agency_name="County of Roanoke")
        self.assertEqual(parse_qs(urlparse(url).query)["agencyname"], ["County of Roanoke"])
        detail = connector.detail_url("LOT X", 2, "IVDetails.jsp")
        self.assertEqual(parse_qs(urlparse(detail).query)["rfp_id_lot"], ["LOT X"])
        items = await collect(
            connector, EVAQuery(keywords=("network",), agency_name="County of Roanoke", limit=1)
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source.source_id, "LOT-100")
        self.assertEqual(item.raw_payload["eva"]["round"], 1)
        self.assertEqual(item.raw_payload["eva"]["round_history"], [0, 1])
        self.assertEqual(item.due_at, datetime(2026, 8, 15, 14, tzinfo=UTC))
        docs = item.raw_payload["document_links"]
        self.assertEqual(
            [doc["document_category"] for doc in docs],
            ["solicitation", "amendment", "solicitation"],
        )
        self.assertEqual(docs[2]["access_state"], "free_account_required")
        candidates = connector.document_candidates(item)
        self.assertTrue(connector.document_pipeline_compatible)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(candidates[1].source_document_id, "D2")
        self.assertEqual(candidates[1].addendum_number, "1")
        self.assertEqual(candidates[2].access_state, AccessState.REGISTRATION_REQUIRED)
        self.assertFalse(candidates[2].publicly_retrievable)
        self.assertEqual(transport.calls[0]["params"]["agencyname"], "County of Roanoke")
        self.assertEqual(connector.health.active_detail_variant, "IVDetailsV2.jsp")

    async def test_limits_duplicates_missing_fields_and_fallback(self) -> None:
        invalid = '<tr class="opportunity-row" data-lot-id="X"><td class="agency">A</td></tr>'
        connector = EVAConnector(transport=FakeTransport([response(invalid)]), fetch_details=False)
        self.assertEqual(await collect(connector), [])
        self.assertEqual(connector.health.skipped_records, 1)
        connector = EVAConnector(
            transport=FakeTransport([response(BOARD)]), fetch_details=False, max_results=1
        )
        items = await collect(connector, EVAQuery(limit=20))
        self.assertEqual(len(items), 1)
        self.assertIn("rfp_id_lot=LOT-100", str(items[0].source.opportunity_url))

    async def test_access_pages_and_stable_403(self) -> None:
        cases = (
            ("Supplier Login Password", EVAAccessState.LOGIN_REQUIRED),
            ("Vendor Registration required", EVAAccessState.FREE_ACCOUNT_REQUIRED),
            ("Your session has expired", EVAAccessState.SESSION_EXPIRED),
            ("reCAPTCHA bot challenge", EVAAccessState.CAPTCHA_BLOCKED),
            ("Scheduled maintenance", EVAAccessState.MAINTENANCE),
        )
        for body, expected in cases:
            connector = EVAConnector(transport=FakeTransport([response(body)]), fetch_details=False)
            with self.assertRaises(EVAAccessError):
                await collect(connector)
            self.assertEqual(connector.health.access_state, expected)
        transport = FakeTransport([response("blocked", 403), response(BOARD)])
        connector = EVAConnector(transport=transport, max_retries=3, fetch_details=False)
        with self.assertRaises(EVAAccessError):
            await collect(connector)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(connector.health.last_status_code, 403)

    async def test_retry_after_connection_circuit_and_recovery(self) -> None:
        sleeps: list[float] = []

        async def sleep(delay: float) -> None:
            sleeps.append(delay)

        connector = EVAConnector(
            transport=FakeTransport(
                [response("busy", 429, **{"Retry-After": "2"}), response(BOARD)]
            ),
            max_retries=1,
            fetch_details=False,
            sleep=sleep,
            jitter_seconds=0,
        )
        self.assertEqual(len(await collect(connector, EVAQuery(limit=1))), 1)
        self.assertEqual(sleeps, [2])
        now = datetime(2026, 1, 1, tzinfo=UTC)
        connector = EVAConnector(
            transport=FakeTransport([ConnectionError(), response(BOARD)]),
            max_retries=0,
            circuit_breaker_threshold=1,
            circuit_breaker_cooldown=1,
            now=lambda: now,
            fetch_details=False,
        )
        with self.assertRaises(EVAAvailabilityError):
            await collect(connector)
        self.assertTrue(connector.health.circuit_open)
        now += timedelta(seconds=2)
        self.assertEqual(len(await collect(connector, EVAQuery(limit=1))), 1)

    async def test_registry_notice_mapping_and_injected_ownership(self) -> None:
        for alias in ("virginia/eva", "eva", "virginia-business-opportunities", "cgi/eva"):
            self.assertIs(connector_registry.get(alias), EVAConnector)
        self.assertEqual(EVAConnector._notice_type("Quick Quote"), EVANoticeType.QUICK_QUOTE)
        self.assertEqual(EVAConnector._notice_type("unfamiliar"), EVANoticeType.OTHER)
        transport = FakeTransport([response(BOARD)])
        connector = EVAConnector(transport=transport, fetch_details=False)
        await connector.aclose()
        self.assertFalse(transport.closed)
