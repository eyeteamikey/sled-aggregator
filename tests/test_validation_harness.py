import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import httpx

from sled_aggregator.validation.__main__ import main
from sled_aggregator.validation.harness import (
    HarnessConfig,
    ValidationHarness,
    redact_url,
    render_json,
    render_markdown,
)

SOURCE = {
    "source_id": "il-bidbuy",
    "jurisdiction_id": "IL",
    "platform_family": "periscope/buyspeed",
    "public_search_url": "https://example.test/search?customer=IL&token=private",
    "public_bid_board_url": "https://example.test/",
}
NOW = datetime(2026, 8, 3, 12, tzinfo=UTC)


class ValidationHarnessTests(unittest.TestCase):
    def harness(self, handler, **kwargs):
        return ValidationHarness(
            HarnessConfig(rate_limit_seconds=0, **kwargs),
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
            clock=lambda: NOW,
        )

    def test_success_records_sanitized_shape_without_overclaiming_capabilities(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertIn("SLED-Aggregator", request.headers["user-agent"])
            return httpx.Response(200, json={"results": [{"id": 1}], "page": 1})

        result = self.harness(handler).validate(SOURCE)
        self.assertFalse(result.promotion_eligible)
        self.assertEqual(result.requests_used, 1)
        self.assertEqual(result.capabilities["search_access"], "live_verified")
        self.assertEqual(result.capabilities["detail_access"], "not_observed")
        self.assertNotIn("private", json.dumps(result.as_dict()))
        self.assertEqual(len(result.observations[0].response_shape), 16)

    def test_promotion_requires_an_expected_response_fingerprint(self):
        harness = self.harness(lambda _: httpx.Response(200, json={"results": []}))
        first = harness.validate(SOURCE)
        registered = dict(
            SOURCE,
            validation_response_fingerprints=[first.observations[0].response_shape],
        )
        self.assertTrue(harness.validate(registered).promotion_eligible)

    def test_budget_and_retry_limit_rate_limited_requests(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(429, text="slow down")

        result = self.harness(handler, request_budget=2, retries=9).validate(SOURCE)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.capabilities["rate_limiting"], "rate_limited")
        self.assertFalse(result.promotion_eligible)

    def test_timeout_is_network_blocked_and_never_promoted(self):
        def handler(request):
            raise httpx.ReadTimeout("bounded timeout", request=request)

        result = self.harness(handler, retries=0).validate(SOURCE)
        self.assertEqual(result.observations[0].classification, "network_blocked")
        self.assertEqual(result.observations[0].error, "ReadTimeout")
        self.assertFalse(result.promotion_eligible)

    def test_authentication_and_captcha_are_distinct(self):
        auth = self.harness(lambda _: httpx.Response(403, text="Forbidden")).validate(SOURCE)
        captcha = self.harness(lambda _: httpx.Response(200, text="<div>hCaptcha</div>")).validate(SOURCE)
        self.assertEqual(auth.capabilities["authentication"], "authentication_required")
        self.assertEqual(captcha.capabilities["captcha"], "captcha_blocked")
        self.assertFalse(auth.promotion_eligible)
        self.assertFalse(captcha.promotion_eligible)

    def test_dry_run_makes_no_request(self):
        def forbidden(_):
            self.fail("dry run performed a request")

        result = self.harness(forbidden, dry_run=True).validate(SOURCE)
        self.assertEqual(result.requests_used, 0)
        self.assertEqual(result.environment, "dry-run")

    def test_redaction_removes_fragment_and_sensitive_values(self):
        value = redact_url("https://host/path?customer=51&session=abc&key=xyz#route")
        self.assertEqual(value, "https://host/path?customer=51&session=%5BREDACTED%5D&key=%5BREDACTED%5D")

    def test_reports_are_deterministic(self):
        one = self.harness(lambda _: httpx.Response(200, json={"b": 1, "a": 2})).validate(SOURCE)
        two_source = dict(SOURCE, source_id="ma-commbuys", jurisdiction_id="MA")
        two = self.harness(lambda _: httpx.Response(404, text="gone")).validate(two_source)
        self.assertEqual(render_json([two, one]), render_json([one, two]))
        self.assertEqual(render_markdown([two, one]), render_markdown([one, two]))

    def test_cli_writes_both_formats_in_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "sources.json"
            registry.write_text(json.dumps({"sources": [SOURCE]}))
            json_output, md_output = root / "result.json", root / "result.md"
            status = main(["--source", "il-bidbuy", "--registry", str(registry), "--dry-run",
                           "--json-output", str(json_output), "--markdown-output", str(md_output)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(json_output.read_text())[0]["requests_used"], 0)
            self.assertIn("| `il-bidbuy` |", md_output.read_text())

    def test_invalid_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            HarnessConfig(request_budget=0)


if __name__ == "__main__":
    unittest.main()
