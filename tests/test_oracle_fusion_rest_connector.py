import json
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx

from sled_aggregator.connectors.oracle_fusion_rest import (
    DETROIT,
    OracleFusionAccessError,
    OracleFusionError,
    OracleFusionQuery,
    OracleFusionRestConnector,
)
from sled_aggregator.connectors.peoplesoft import PeopleSoftSourcingConnector
from sled_aggregator.connectors.registry import connector_registry
from sled_aggregator.domain.enums import OpportunityStatus

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.closed = False

    async def get(self, url, *, params=None):
        self.calls.append(("GET", url, dict(params or {})))
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        status, payload, headers = value
        request = httpx.Request("GET", url, params=params)
        if isinstance(payload, (dict, list)):
            return httpx.Response(status, json=payload, headers=headers, request=request)
        return httpx.Response(status, text=payload, headers=headers, request=request)

    async def aclose(self):
        self.closed = True


def reply(payload, status=200, headers=None):
    return status, payload, headers or {"content-type": "application/json"}


class OracleFusionTests(unittest.IsolatedAsyncioTestCase):
    def test_registry_and_separation(self):
        cls = connector_registry.get("oracle/fusion-rest")
        for alias in (
            "oracle-fusion-rest",
            "oracle-cloud-procurement",
            "oracle-fusion-procurement",
            "oracle-supplier-negotiations",
        ):
            self.assertIs(connector_registry.get(alias), cls)
        self.assertIsNot(cls, PeopleSoftSourcingConnector)
        self.assertIs(
            connector_registry.get("oracle/peoplesoft-sourcing"), PeopleSoftSourcingConnector
        )
        for ambiguous in ("oracle", "fusion", "procurement", "supplier-portal"):
            with self.assertRaises(KeyError):
                connector_registry.get(ambiguous)

    def test_profile_validation_and_ssrf(self):
        with self.assertRaises(ValueError):
            replace(DETROIT, page_size=0)
        with self.assertRaises(ValueError):
            replace(DETROIT, rest_resource_root="http://ebkk.fa.us8.oraclecloud.com/x")
        with self.assertRaises(ValueError):
            replace(
                DETROIT,
                api_host="127.0.0.1",
                approved_api_hosts=frozenset({"127.0.0.1"}),
                rest_resource_root="https://127.0.0.1/supplierNegotiationAbstracts",
            )

    def test_query_safety_dates_status_sort(self):
        c = OracleFusionRestConnector(transport=FakeTransport([]))
        p = c.query_params(
            OracleFusionQuery(
                keywords=("builder's",),
                status="active",
                posted_from=date(2026, 1, 1),
                posted_to=date(2026, 2, 1),
                open_from=date(2025, 1, 1),
                negotiation_number="RFP-1",
                limit=25,
            ),
            offset=25,
        )
        self.assertIn("builder''s", p["q"])
        self.assertIn("NegotiationStatusCode='ACTIVE'", p["q"])
        self.assertIn("PostingDate>='2026-01-01'", p["q"])
        self.assertEqual(p["offset"], 25)
        for query in (
            OracleFusionQuery(keywords=("bad\nvalue",)),
            OracleFusionQuery(status="x"),
            OracleFusionQuery(sort_field="Synopsis"),
            OracleFusionQuery(keywords=("x",) * 6),
        ):
            with self.assertRaises(ValueError):
                c.query_params(query)
        with self.assertRaises(ValueError):
            c.query_params(OracleFusionQuery(), offset=-1)

    async def test_pagination_normalization_dedup_and_get_only(self):
        first = fixture("oracle_fusion_rest_listing_page_1.json")
        second = fixture("oracle_fusion_rest_listing_page_2.json")
        first["items"].append(first["items"][0].copy())
        transport = FakeTransport([reply(first), reply(second)])
        c = OracleFusionRestConnector(transport=transport)
        found = [x async for x in c.discover(OracleFusionQuery(limit=50))]
        self.assertEqual([x.solicitation_number for x in found], ["RFP-2026-001", "RFQ-2026-002"])
        self.assertEqual(
            found[0].source.source_id, "oracle/fusion-rest:mi-detroit-oracle-fusion:1001"
        )
        self.assertEqual(found[0].status, OpportunityStatus.OPEN)
        self.assertEqual([x[2]["offset"] for x in transport.calls], [0, 25])
        self.assertTrue(all(x[0] == "GET" for x in transport.calls))
        self.assertFalse(hasattr(transport, "post"))

    async def test_bounds_empty_hasmore_and_business_unit(self):
        wrong = fixture("oracle_fusion_rest_listing_page_1.json")
        wrong["items"][0]["ProcurementBUId"] = "999"
        c = OracleFusionRestConnector(transport=FakeTransport([reply(wrong)]))
        self.assertEqual([x async for x in c.discover(OracleFusionQuery(limit=20))], [])
        c = OracleFusionRestConnector(
            transport=FakeTransport([reply(fixture("oracle_fusion_rest_listing_empty.json"))])
        )
        self.assertEqual([x async for x in c.discover(OracleFusionQuery(limit=20))], [])
        profile = replace(DETROIT, maximum_pages=1, maximum_results=1)
        c = OracleFusionRestConnector(
            profile, FakeTransport([reply(fixture("oracle_fusion_rest_listing_page_1.json"))])
        )
        self.assertEqual(len([x async for x in c.discover(OracleFusionQuery(limit=99))]), 1)

    async def test_repeated_page_protection(self):
        page = fixture("oracle_fusion_rest_listing_page_1.json")
        c = OracleFusionRestConnector(transport=FakeTransport([reply(page), reply(page)]))
        with self.assertRaises(OracleFusionError):
            [x async for x in c.discover(OracleFusionQuery(limit=50))]

    async def test_attachments_signed_url_and_amendments(self):
        item = fixture("oracle_fusion_rest_listing_page_1.json")["items"][0]
        opportunity = OracleFusionRestConnector(transport=FakeTransport([])).normalize(item)
        attachment = fixture("oracle_fusion_rest_attachments.json")
        attachment["items"][0]["FileUrl"] = "/content?XFND_SIGNATURE=secret"
        transport = FakeTransport(
            [reply(attachment), reply(fixture("oracle_fusion_rest_amendments.json"))]
        )
        c = OracleFusionRestConnector(transport=transport)
        docs = await c.attachments(opportunity)
        self.assertTrue(str(docs[0].source_document_url).endswith("/501/enclosure/FileContents"))
        self.assertEqual(docs[0].category, "sow")
        self.assertNotIn("FileUrl", docs[0].raw_metadata)
        self.assertEqual(docs[0].mime_type, "application/octet-stream")
        amendments = await c.amendments(opportunity)
        self.assertEqual(amendments[0]["amendment_number"], "1")
        self.assertEqual(amendments[0]["parent_auction_header_id"], "1001")

    async def test_fail_closed_non_json_malformed_shape_login_captcha_redirect(self):
        cases = [
            reply("not json", headers={"content-type": "text/plain"}),
            reply("{bad", headers={"content-type": "application/json"}),
            reply({"unexpected": []}),
            reply("<html>login</html>", headers={"content-type": "text/html"}),
            reply({"message": "captcha required"}),
            reply(
                "",
                status=302,
                headers={"location": "http://127.0.0.1/login", "content-type": "text/plain"},
            ),
        ]
        for response in cases:
            c = OracleFusionRestConnector(transport=FakeTransport([response]))
            with self.assertRaises(OracleFusionAccessError):
                [x async for x in c.discover(OracleFusionQuery(limit=1))]

    async def test_retries_connection_health_circuit_and_recovery(self):
        profile = replace(
            DETROIT,
            retry_count=1,
            backoff_seconds=0,
            jitter_seconds=0,
            circuit_breaker_threshold=2,
            circuit_breaker_cooldown=0,
        )
        request = httpx.Request("GET", DETROIT.rest_resource_root)
        for status in (429, 502, 503, 504):
            c = OracleFusionRestConnector(
                profile,
                FakeTransport(
                    [reply({}, status), reply(fixture("oracle_fusion_rest_listing_empty.json"))]
                ),
            )
            self.assertEqual([x async for x in c.discover(OracleFusionQuery(limit=1))], [])
            self.assertEqual(c.health_snapshot().consecutive_failures, 0)
        c = OracleFusionRestConnector(
            profile,
            FakeTransport(
                [
                    httpx.ConnectError("no", request=request),
                    reply(fixture("oracle_fusion_rest_listing_empty.json")),
                ]
            ),
        )
        self.assertEqual([x async for x in c.discover(OracleFusionQuery(limit=1))], [])
        # Numeric and HTTP-date Retry-After are both parsed and bounded.
        self.assertEqual(c._retry_delay(httpx.Response(429, headers={"Retry-After": "2"}), 0), 2)
        self.assertGreaterEqual(
            c._retry_delay(
                httpx.Response(429, headers={"Retry-After": "Wed, 31 Dec 2099 23:59:59 GMT"}), 0
            ),
            0,
        )

    async def test_client_ownership(self):
        injected = FakeTransport([])
        c = OracleFusionRestConnector(transport=injected)
        await c.aclose()
        self.assertFalse(injected.closed)
        owned = OracleFusionRestConnector()
        await owned.aclose()
        self.assertTrue(owned._client.is_closed)

    def test_fixture_inventory_is_sanitized(self):
        names = {p.name for p in FIXTURES.glob("oracle_fusion_rest*")}
        self.assertEqual(len(names), 7)
        for path in FIXTURES.glob("oracle_fusion_rest*"):
            text = path.read_text().lower()
            for secret in ("xfnd_signature", "xsrf", "authorization", "cookie"):
                self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
