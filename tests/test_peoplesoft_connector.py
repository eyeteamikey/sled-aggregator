import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from sled_aggregator.connectors.base import ConnectorQuery
from sled_aggregator.connectors.peoplesoft import (
    CAL_EPROCURE,
    PeopleSoftAccessError,
    PeopleSoftAccessState,
    PeopleSoftAvailabilityError,
    PeopleSoftQuery,
    PeopleSoftSessionState,
    PeopleSoftSourcingConnector,
    PeopleSoftSourcingPortal,
)

FIXTURES = Path(__file__).parent / "fixtures"
LANDING = (FIXTURES / "peoplesoft_landing.html").read_text()
RESULTS = (FIXTURES / "peoplesoft_results.html").read_text()
DETAIL = (FIXTURES / "peoplesoft_detail.html").read_text()
PARTIAL = (FIXTURES / "peoplesoft_partial.html").read_text()


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
        if content_type == "application/json":
            return httpx.Response(status, json=body, headers=headers, request=request)
        return httpx.Response(
            status, text=body, headers={"content-type": content_type, **headers}, request=request
        )

    async def aclose(self) -> None:
        self.closed = True


def response(body: Any, status: int = 200, content_type: str = "text/html", **headers: str):
    return status, body, content_type, headers


def portal(strategy: str = "html", **changes: Any) -> PeopleSoftSourcingPortal:
    values = dict(
        jurisdiction="California",
        jurisdiction_code="CA",
        name="Fixture PeopleSoft",
        public_system="Fixture Register",
        platform="Oracle PeopleSoft",
        base_url="https://example.test/",
        search_url="https://example.test/search",
        fallback_url="https://example.test/events",
        landing_url="https://example.test/landing",
        response_strategy=strategy,
    )
    values.update(changes)
    return PeopleSoftSourcingPortal(**values)


async def collect(connector: PeopleSoftSourcingConnector, query: ConnectorQuery | None = None):
    return [item async for item in connector.discover(query or ConnectorQuery())]


class PeopleSoftConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_california_preset_is_authoritative_and_configurable(self) -> None:
        self.assertEqual(CAL_EPROCURE.jurisdiction, "California")
        self.assertEqual(CAL_EPROCURE.public_system, "California State Contracts Register")
        self.assertTrue(CAL_EPROCURE.fallback_url.startswith("https://"))
        self.assertIsNone(CAL_EPROCURE.component_id)

    async def test_session_search_detail_normalization_identity_and_documents(self) -> None:
        transport = FakeTransport([response(LANDING), response(RESULTS), response(DETAIL)])
        connector = PeopleSoftSourcingConnector(portal(), transport=transport, fetch_details=True)
        query = PeopleSoftQuery(
            keywords=("network",), event_id="00001234", business_unit="DGS", county="Alameda"
        )
        items = await collect(connector, query)
        item = items[0]
        self.assertEqual(item.source.source_id, "CA:DGS:00001234")
        self.assertEqual(item.title, "Network modernization services")
        self.assertEqual(item.solicitation_number, "00001234")
        self.assertEqual(item.categories, ["43222600", "81111800"])
        self.assertEqual(item.due_at, datetime(2026, 8, 20, 14, tzinfo=UTC))
        self.assertEqual(transport.calls[1]["params"]["event_id"], "00001234")
        self.assertNotIn("ICStateNum", item.raw_payload)
        docs = item.raw_payload["document_links"]
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0]["attachment_identifier"], "A2")
        self.assertEqual(docs[0]["access_state"], "anonymous-session-required")
        self.assertEqual(docs[1]["access_state"], "restricted")
        self.assertEqual(connector.health.session_state, PeopleSoftSessionState.FORM_READY)

    async def test_partial_page_fallback_url_missing_fields_empty_and_duplicates(self) -> None:
        transport = FakeTransport([response(LANDING), response(PARTIAL), response(PARTIAL)])
        connector = PeopleSoftSourcingConnector(
            portal(), transport=transport, page_size=1, max_pages=4, fetch_details=False
        )
        items = await collect(connector)
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0].source.opportunity_url), "https://example.test/events")
        self.assertEqual(len(transport.calls), 3)
        bad = (
            '<div class="event" data-event-id="1"></div>'
            '<div class="event"><span data-field="title">Missing</span></div>'
        )
        connector = PeopleSoftSourcingConnector(
            portal(),
            transport=FakeTransport([response(LANDING), response(bad)]),
            fetch_details=False,
        )
        self.assertEqual(await collect(connector), [])
        self.assertEqual(connector.health.skipped_records, 2)

    async def test_json_csv_xml_strategies(self) -> None:
        cases = [
            (
                "json",
                response(
                    {"events": [{"eventId": "J1", "eventName": "JSON"}]},
                    content_type="application/json",
                ),
            ),
            (
                "csv",
                response(
                    "event_id,event_name,business_unit\nC1,CSV,DGS\n", content_type="text/csv"
                ),
            ),
            (
                "xml",
                response(
                    "<events><event><event_id>X1</event_id><event_name>XML</event_name></event></events>",
                    content_type="application/xml",
                ),
            ),
        ]
        for strategy, payload in cases:
            with self.subTest(strategy=strategy):
                connector = PeopleSoftSourcingConnector(
                    portal(strategy, landing_url=None),
                    transport=FakeTransport([payload]),
                    fetch_details=False,
                )
                self.assertEqual(len(await collect(connector)), 1)

    async def test_access_pages_and_forbidden_fail_closed(self) -> None:
        pages = {
            PeopleSoftAccessState.LOGIN_REQUIRED: "Sign in to PeopleSoft User ID Password",
            PeopleSoftAccessState.REGISTRATION_REQUIRED: "Supplier registration required",
            PeopleSoftAccessState.CAPTCHA_BLOCKED: "reCAPTCHA",
            PeopleSoftAccessState.MAINTENANCE: "Scheduled maintenance",
            PeopleSoftAccessState.SESSION_EXPIRED: "Your PeopleSoft connection has expired",
        }
        for expected, body in pages.items():
            with self.subTest(state=expected):
                connector = PeopleSoftSourcingConnector(
                    portal(landing_url=None), transport=FakeTransport([response(body)])
                )
                with self.assertRaises(PeopleSoftAccessError):
                    await collect(connector)
                self.assertEqual(connector.health.access_state, expected)
        connector = PeopleSoftSourcingConnector(
            portal(landing_url=None), transport=FakeTransport([response("no", 403)])
        )
        with self.assertRaises(PeopleSoftAccessError):
            await collect(connector)
        self.assertEqual(connector.health.access_state, PeopleSoftAccessState.FORBIDDEN)

    async def test_retry_after_transients_connection_and_circuit_recovery(self) -> None:
        sleeps: list[float] = []
        transport = FakeTransport(
            [response("busy", 429, **{"Retry-After": "2"}), response(RESULTS)]
        )
        connector = PeopleSoftSourcingConnector(
            portal(landing_url=None),
            transport=transport,
            max_retries=1,
            fetch_details=False,
            jitter_seconds=0,
            sleep=lambda delay: self._sleep(sleeps, delay),
        )
        self.assertEqual(len(await collect(connector)), 1)
        self.assertEqual(sleeps, [2])
        for code in (502, 503, 504):
            connector = PeopleSoftSourcingConnector(
                portal(landing_url=None),
                transport=FakeTransport([response("bad", code)]),
                max_retries=0,
                circuit_breaker_threshold=1,
            )
            with self.assertRaises(PeopleSoftAvailabilityError):
                await collect(connector)
            self.assertTrue(connector.health.circuit_open)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        connector = PeopleSoftSourcingConnector(
            portal(landing_url=None),
            transport=FakeTransport([ConnectionError(), response(RESULTS)]),
            max_retries=0,
            circuit_breaker_threshold=1,
            circuit_breaker_cooldown=1,
            now=lambda: now,
            fetch_details=False,
        )
        with self.assertRaises(PeopleSoftAvailabilityError):
            await collect(connector)
        now += timedelta(seconds=2)
        self.assertEqual(len(await collect(connector)), 1)
        self.assertFalse(connector.health.circuit_open)

    async def _sleep(self, target: list[float], delay: float) -> None:
        target.append(delay)

    async def test_transport_ownership(self) -> None:
        injected = FakeTransport([])
        await PeopleSoftSourcingConnector(portal(), transport=injected).aclose()
        self.assertFalse(injected.closed)
        owned = FakeTransport([])
        with patch("sled_aggregator.connectors.peoplesoft.httpx.AsyncClient", return_value=owned):
            connector = PeopleSoftSourcingConnector(portal())
            await connector.aclose()
        self.assertTrue(owned.closed)
