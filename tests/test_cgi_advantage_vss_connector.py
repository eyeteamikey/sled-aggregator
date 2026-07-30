import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from sled_aggregator.connectors.cgi_advantage_vss import (
    CGI_ADVANTAGE_VSS_PORTALS,
    COLORADO_VSS,
    MAINE_VSS,
    MICHIGAN_SIGMA_VSS,
    CGIAdvantageVSSAccessError,
    CGIAdvantageVSSAccessState,
    CGIAdvantageVSSAvailabilityError,
    CGIAdvantageVSSConnector,
    CGIAdvantageVSSQuery,
    CGIAdvantageVSSVariant,
)
from sled_aggregator.connectors.registry import ConnectorRegistry, connector_registry
from sled_aggregator.domain.enums import OpportunityStatus

FIXTURES = Path(__file__).parent / "fixtures"
LANDING = (FIXTURES / "cgi_vss_maine_landing.html").read_text()
SEARCH = (FIXTURES / "cgi_vss_search.html").read_text()
DETAIL = (FIXTURES / "cgi_vss_detail.html").read_text()


def response(url, text, status=200, headers=None):
    return httpx.Response(
        status,
        text=text,
        headers=headers or {"content-type": "text/html"},
        request=httpx.Request("GET", url),
    )


class FakeTransport:
    def __init__(self, replies):
        self.replies, self.calls, self.closed = list(replies), [], False

    async def get(self, url, *, params=None):
        self.calls.append(("GET", url, dict(params or {})))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def post(self, url, *, data):
        self.calls.append(("POST", url, dict(data)))
        return self.replies.pop(0)

    async def aclose(self):
        self.closed = True


VERIFIED = replace(
    MAINE_VSS,
    public_search_verified=True,
    public_detail_verified=True,
    public_attachments_verified=True,
    public_awards_verified=True,
    public_contracts_verified=True,
)


class CGIAdvantageVSSConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, replies, query=None, portal=VERIFIED, **kwargs):
        fake = FakeTransport(replies)
        connector = CGIAdvantageVSSConnector(portal, transport=fake, **kwargs)
        items = [item async for item in connector.discover(query or CGIAdvantageVSSQuery())]
        return connector, fake, items

    async def test_guest_search_detail_normalization_and_provenance(self):
        detail_url = "https://mevss.hostams.com/PRDVSS1X1/Advantage4?solicitation_number=RFQ-HVS-260000000404-1"
        replies = [
            response(VERIFIED.landing_url, LANDING),
            response(
                "https://mevss.hostams.com/PRDVSS1X1/AltSelfService/Guest",
                "<html>Public guest home</html>",
            ),
            response(VERIFIED.search_url, SEARCH),
            response(detail_url, DETAIL),
            response(
                VERIFIED.search_url,
                DETAIL.replace("CGI-1001", "CGI-1002").replace(
                    "RFQ-HVS-260000000404-1", "RFP-171-260000002077-1"
                ),
            ),
        ]
        connector, fake, items = await self.collect(
            replies, CGIAdvantageVSSQuery(include_awards=True)
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.solicitation_number, "RFQ-HVS-260000000404-1")
        self.assertEqual(first.source.source_id, "maine/vss:id:CGI-1001")
        self.assertEqual(first.status, OpportunityStatus.OPEN)
        self.assertEqual(first.due_at.utcoffset(), timedelta(hours=-5))
        self.assertEqual(first.raw_payload["cgi_advantage_vss"]["round_or_version"], "1")
        self.assertEqual(len(first.raw_payload["commodity_lines"]), 1)
        self.assertEqual(len(first.raw_payload["attachments"]), 3)
        self.assertEqual(first.raw_payload["award_metadata"][0]["awardee"], "Example Supplier")
        self.assertTrue(first.raw_payload["contract_references"])
        self.assertNotIn("cookie", repr(first.raw_payload).casefold())
        self.assertEqual(connector.health.access_state, CGIAdvantageVSSAccessState.PUBLIC)
        self.assertEqual(fake.calls[2][2]["scope"], "open")

    async def test_query_filters_are_forwarded_and_bounded(self):
        query = CGIAdvantageVSSQuery(
            keyword="network",
            solicitation_number="00001",
            solicitation_type="RFQ",
            status="Open",
            department="IT",
            agency="Admin",
            buyer="Buyer",
            commodity_code="204",
            commodity_description="router",
            page_size=50,
            max_pages=1,
            include_details=False,
        )
        _, fake, _ = await self.collect(
            [
                response(VERIFIED.landing_url, LANDING),
                response(VERIFIED.landing_url, "<html>Public guest</html>"),
                response(VERIFIED.search_url, SEARCH),
            ],
            query,
        )
        params = fake.calls[-1][2]
        self.assertEqual(params["solicitation_number"], "00001")
        self.assertEqual(params["commodity_description"], "router")
        self.assertEqual(params["page_size"], "50")

    async def test_repeated_page_and_duplicate_records_terminate(self):
        portal = replace(VERIFIED, guest_bootstrap_required=False, anonymous_session_required=False)
        _, fake, items = await self.collect(
            [response(portal.search_url, SEARCH), response(portal.search_url, SEARCH)],
            CGIAdvantageVSSQuery(page_size=2, max_pages=10, include_details=False),
            portal,
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(len(fake.calls), 2)

    async def test_result_limit_and_empty_results(self):
        portal = replace(VERIFIED, guest_bootstrap_required=False, public_detail_verified=False)
        _, _, items = await self.collect(
            [response(portal.search_url, SEARCH)],
            CGIAdvantageVSSQuery(result_limit=1, limit=1, include_details=False),
            portal,
        )
        self.assertEqual(len(items), 1)
        _, _, empty = await self.collect(
            [response(portal.search_url, "<html>No matching records</html>")],
            CGIAdvantageVSSQuery(include_details=False),
            portal,
        )
        self.assertEqual(empty, [])

    async def test_configured_unverified_and_landing_only_fail_closed(self):
        for portal in (MICHIGAN_SIGMA_VSS, COLORADO_VSS):
            connector = CGIAdvantageVSSConnector(portal, transport=FakeTransport([]))
            with self.assertRaises(CGIAdvantageVSSAccessError) as caught:
                [item async for item in connector.discover(CGIAdvantageVSSQuery())]
            self.assertEqual(caught.exception.state, CGIAdvantageVSSAccessState.RESTRICTED)

    async def test_one_guest_refresh_only(self):
        expired = "<html>Your session has expired</html>"
        replies = [
            response(VERIFIED.landing_url, LANDING),
            response(VERIFIED.landing_url, "<html>Public</html>"),
            response(VERIFIED.search_url, expired),
            response(VERIFIED.landing_url, LANDING),
            response(VERIFIED.landing_url, "<html>Public</html>"),
            response(VERIFIED.search_url, SEARCH),
        ]
        _, fake, items = await self.collect(replies, CGIAdvantageVSSQuery(include_details=False))
        self.assertEqual(len(items), 2)
        self.assertEqual(sum(call[1] == VERIFIED.landing_url for call in fake.calls), 2)

    async def test_false_success_access_states(self):
        cases = {
            "<html>Vendor login: username and password</html>": (
                CGIAdvantageVSSAccessState.LOGIN_REQUIRED
            ),
            "<html>Create a vendor account</html>": (
                CGIAdvantageVSSAccessState.REGISTRATION_REQUIRED
            ),
            "<html>Enter verification code</html>": (
                CGIAdvantageVSSAccessState.VERIFICATION_REQUIRED
            ),
            "<html>reCAPTCHA</html>": CGIAdvantageVSSAccessState.CAPTCHA,
            "<html>Invited vendors only</html>": CGIAdvantageVSSAccessState.INVITED_VENDOR_ONLY,
            "<html>Scheduled maintenance</html>": CGIAdvantageVSSAccessState.MAINTENANCE,
            "<html>Outside normal operating hours</html>": (
                CGIAdvantageVSSAccessState.SCHEDULED_UNAVAILABLE
            ),
            "<app-root></app-root>": CGIAdvantageVSSAccessState.MALFORMED_RESPONSE,
        }
        portal = replace(VERIFIED, guest_bootstrap_required=False)
        for html, state in cases.items():
            with self.subTest(state=state):
                connector = CGIAdvantageVSSConnector(
                    portal, transport=FakeTransport([response(portal.search_url, html)])
                )
                with self.assertRaises(CGIAdvantageVSSAccessError) as caught:
                    [item async for item in connector.discover(CGIAdvantageVSSQuery())]
                self.assertEqual(caught.exception.state, state)

    async def test_stable_403_not_retried(self):
        portal = replace(VERIFIED, guest_bootstrap_required=False)
        fake = FakeTransport([response(portal.search_url, "Forbidden", 403)])
        connector = CGIAdvantageVSSConnector(portal, transport=fake, max_retries=5)
        with self.assertRaises(CGIAdvantageVSSAccessError):
            [item async for item in connector.discover(CGIAdvantageVSSQuery())]
        self.assertEqual(len(fake.calls), 1)

    async def test_transient_retry_after_and_recovery(self):
        portal = replace(VERIFIED, guest_bootstrap_required=False, public_detail_verified=False)
        sleeps = []

        async def sleep(value):
            sleeps.append(value)

        fake = FakeTransport(
            [
                response(
                    portal.search_url,
                    "busy",
                    429,
                    {"content-type": "text/html", "Retry-After": "2"},
                ),
                response(portal.search_url, SEARCH),
            ]
        )
        connector = CGIAdvantageVSSConnector(portal, transport=fake, sleep=sleep, jitter_seconds=0)
        items = [
            item async for item in connector.discover(CGIAdvantageVSSQuery(include_details=False))
        ]
        self.assertEqual(len(items), 2)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(connector.health.consecutive_failures, 0)

    async def test_retry_exhaustion_opens_only_tenant_circuit(self):
        now = datetime(2026, 7, 30, tzinfo=UTC)
        portal = replace(VERIFIED, guest_bootstrap_required=False)
        connector = CGIAdvantageVSSConnector(
            portal,
            transport=FakeTransport([response(portal.search_url, "busy", 503)] * 3),
            max_retries=0,
            circuit_breaker_threshold=3,
            now=lambda: now,
        )
        for _ in range(3):
            with self.assertRaises(CGIAdvantageVSSAvailabilityError):
                [item async for item in connector.discover(CGIAdvantageVSSQuery())]
        self.assertTrue(connector.health.circuit_open)
        other = CGIAdvantageVSSConnector(
            replace(portal, key="michigan/test"), transport=FakeTransport([])
        )
        self.assertFalse(other.health.circuit_open)

    async def test_connection_exception_retries(self):
        portal = replace(VERIFIED, guest_bootstrap_required=False, public_detail_verified=False)
        fake = FakeTransport([httpx.ConnectError("down"), response(portal.search_url, SEARCH)])
        connector = CGIAdvantageVSSConnector(portal, transport=fake, sleep=lambda _: _noop())
        items = [
            item async for item in connector.discover(CGIAdvantageVSSQuery(include_details=False))
        ]
        self.assertEqual(len(items), 2)

    def test_attachment_ssrf_and_document_classification(self):
        connector = CGIAdvantageVSSConnector(VERIFIED, transport=FakeTransport([]))
        for url in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "http://127.0.0.1/a",
            "http://169.254.169.254/latest",
            "https://example.com/a.pdf",
        ):
            self.assertIsNone(connector._safe_url(url, VERIFIED.base_url, attachment=True))
        self.assertEqual(connector._document_category("Statement of Work.pdf"), "sow")
        self.assertEqual(connector._document_category("PWS.docx"), "pws")
        self.assertEqual(
            connector._document_category("Questions and Answers.xlsx"), "questions_and_answers"
        )
        self.assertEqual(connector._document_category("Notice of Award.pdf"), "award_notice")

    def test_query_bounds(self):
        for kwargs in (
            {"max_pages": 0},
            {"max_pages": 21},
            {"page_size": 101},
            {"result_limit": 1001},
        ):
            with self.assertRaises(ValueError):
                CGIAdvantageVSSQuery(**kwargs)

    def test_datetime_dst_and_malformed_date(self):
        connector = CGIAdvantageVSSConnector(VERIFIED, transport=FakeTransport([]))
        self.assertEqual(
            connector._datetime("07/01/2026 09:30 AM").utcoffset(), timedelta(hours=-4)
        )
        self.assertEqual(
            connector._datetime("01/15/2026 10:00 AM").utcoffset(), timedelta(hours=-5)
        )
        self.assertIsNone(connector._datetime("02/31/2026", "10:00 AM"))
        self.assertIsNone(connector._datetime("07/01/2026"))

    def test_status_and_identity_are_conservative_and_namespaced(self):
        connector = CGIAdvantageVSSConnector(VERIFIED, transport=FakeTransport([]))
        self.assertEqual(connector._status("Published"), OpportunityStatus.OPEN)
        self.assertEqual(connector._status("Closed"), OpportunityStatus.CLOSED)
        self.assertEqual(connector._status("No Award"), OpportunityStatus.CLOSED)
        self.assertEqual(connector._status("Suspended"), OpportunityStatus.UNKNOWN)
        self.assertEqual(
            connector._identity({"solicitation_number": "00001-A"}),
            "maine/vss:solicitation:00001-A",
        )
        other = CGIAdvantageVSSConnector(
            replace(VERIFIED, key="other/vss"), transport=FakeTransport([])
        )
        self.assertNotEqual(
            connector._identity({"solicitation_number": "00001-A"}),
            other._identity({"solicitation_number": "00001-A"}),
        )

    def test_portal_presets_and_registry(self):
        self.assertEqual(
            set(CGI_ADVANTAGE_VSS_PORTALS), {"maine/vss", "michigan/sigma-vss", "colorado/vss"}
        )
        self.assertEqual(MAINE_VSS.variant, CGIAdvantageVSSVariant.ALT_SELF_SERVICE)
        self.assertEqual(MICHIGAN_SIGMA_VSS.timezone, "America/Detroit")
        self.assertEqual(COLORADO_VSS.timezone, "America/Denver")
        self.assertFalse(MICHIGAN_SIGMA_VSS.enabled)
        keys = (
            "cgi/advantage-vss",
            "cgi/vss",
            "cgi-advantage",
            "cgi-advantage-vss",
            "advantage-vss",
            "maine/vss",
            "michigan/sigma-vss",
            "colorado/vss",
        )
        for key in keys:
            self.assertIs(connector_registry.get(key), CGIAdvantageVSSConnector)
        for unsafe in ("vss", "sigma", "advantage", "vendor-portal", "supplier-portal"):
            with self.assertRaises(KeyError):
                connector_registry.get(unsafe)
        registry = ConnectorRegistry()
        registry.register(CGIAdvantageVSSConnector)
        with self.assertRaises(ValueError):
            registry.register_alias("cgi/advantage-vss", CGIAdvantageVSSConnector)

    async def test_transport_ownership(self):
        fake = FakeTransport([])
        connector = CGIAdvantageVSSConnector(VERIFIED, transport=fake)
        await connector.aclose()
        self.assertFalse(fake.closed)
        owned = CGIAdvantageVSSConnector(VERIFIED)
        transport = owned._transport
        await owned.aclose()
        self.assertTrue(transport.is_closed)


async def _noop():
    return None


if __name__ == "__main__":
    unittest.main()
