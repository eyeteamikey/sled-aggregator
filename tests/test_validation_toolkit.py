import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sled_aggregator.validation.__main__ import main
from sled_aggregator.validation.toolkit import (
    BIDBUY_EMPTY_RESULTS,
    BIDBUY_RESULT_SELECTOR,
    BIDBUY_SPINNER_SELECTOR,
    CaptureConfig,
    Finding,
    analyze_har,
    approve_evidence,
    build_capture_summary,
    classify_request,
    close_capture_resources,
    evaluate_bidbuy_startup,
    extract_fixture,
    import_har,
    ingest_evidence,
    inspect_bidbuy_result_state,
    normalize_diagnostic,
    sanitize_diagnostic_message,
    sanitize_har,
    scan_artifact,
    validate_label,
    validate_public_url,
    write_capture_reports,
)


def har():
    return {
        "log": {
            "version": "1.2",
            "pages": [{"startedDateTime": "2026-08-03T00:00:00Z"}],
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://bids.example.gov/api/search?page=2&token=secret-value",
                        "headers": [
                            {"name": "Authorization", "value": "Bearer hidden-secret-value"}
                        ],
                        "cookies": [{"name": "sid", "value": "secret"}],
                        "postData": {"params": [{"name": "_afrLoop", "value": "123456"}]},
                    },
                    "response": {
                        "status": 200,
                        "headers": [{"name": "Set-Cookie", "value": "sid=secret"}],
                        "content": {
                            "mimeType": "application/json",
                            "text": '{"records": [], "page": 2}',
                        },
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://bids.example.gov/static/app.js",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {"mimeType": "application/javascript", "text": "x"},
                    },
                },
                {
                    "request": {
                        "method": "GET",
                        "url": "https://bids.example.gov/solicitation/42/attachments",
                        "headers": [],
                    },
                    "response": {
                        "status": 200,
                        "headers": [],
                        "content": {"mimeType": "application/json", "text": '{"attachments": []}'},
                    },
                },
            ],
        }
    }


class ToolkitTests(unittest.TestCase):
    class FakeLocator:
        def __init__(self, value=0, error=None):
            self.value = value
            self.error = error

        def count(self):
            if self.error:
                raise self.error
            return self.value

    class FakePage:
        def __init__(self, *, css=None, text=0, closed=False, error=None):
            self.css = css or {}
            self.text = text
            self.closed = closed
            self.error = error
            self.locator_calls = []
            self.text_calls = []
            self.context = type("Context", (), {"pages": []})()

        def is_closed(self):
            return self.closed

        def locator(self, selector):
            self.locator_calls.append(selector)
            if self.error and selector == BIDBUY_RESULT_SELECTOR:
                return ToolkitTests.FakeLocator(error=self.error)
            return ToolkitTests.FakeLocator(self.css.get(selector, 0))

        def get_by_text(self, pattern):
            self.text_calls.append(pattern)
            return ToolkitTests.FakeLocator(self.text)

    def bidbuy_config(self):
        import json

        source = next(
            x
            for x in json.loads(Path("data/coverage/sources.json").read_text())["sources"]
            if x["source_id"] == "il-bidbuy"
        )
        return CaptureConfig.from_registry(source, "safe")

    def test_request_policy_safe_methods_and_default_denies(self):
        config = self.bidbuy_config()
        for method in ("GET", "HEAD", "OPTIONS"):
            self.assertTrue(classify_request(config, method, config.starting_url).allowed)
        for method in ("PUT", "PATCH", "DELETE", "CONNECT", "TRACE"):
            self.assertFalse(classify_request(config, method, config.starting_url).allowed)
        self.assertFalse(
            classify_request(config, "POST", "https://www.bidbuy.illinois.gov/arbitrary").allowed
        )

    def test_bidbuy_posts_are_host_and_path_bound(self):
        config = self.bidbuy_config()
        headers = {"content-type": "application/x-www-form-urlencoded"}
        for path in (
            "/bso/view/search/external/advancedSearchBid.xhtml",
            "/bso/external/bidDetail.sda",
        ):
            result = classify_request(
                config,
                "POST",
                "https://www.bidbuy.illinois.gov" + path,
                headers=headers,
                field_names=("javax.faces.ViewState",),
            )
            self.assertTrue(result.allowed)
            self.assertEqual(result.classification, "conditional_read_only_post")
            self.assertFalse(
                classify_request(
                    config, "POST", "https://evil.example" + path, headers=headers
                ).allowed
            )
        for path in ("/login", "/register", "/proposal/submit", "/upload"):
            self.assertFalse(
                classify_request(
                    config, "POST", "https://www.bidbuy.illinois.gov" + path, headers=headers
                ).allowed
            )

    def test_jsf_and_session_values_are_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp) / "raw.har", Path(tmp) / "clean.har"
            value = har()
            value["log"]["entries"][0]["request"]["postData"]["params"] += [
                {"name": "javax.faces.ViewState", "value": "live-jsf-secret"},
                {"name": "JSESSIONID", "value": "live-session-secret"},
            ]
            raw.write_text(json.dumps(value))
            sanitize_har(raw, out, source_id="il-bidbuy")
            clean = out.read_text()
            self.assertNotIn("live-jsf-secret", clean)
            self.assertNotIn("live-session-secret", clean)

    def test_manual_import_preserves_original_and_inventories_risk(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            # Repository-local destinations other than .sled-validation are rejected.
            source = Path(tmp) / "input.har"
            source.write_text(json.dumps(har()))
            original = source.read_bytes()
            workspace = Path(".sled-validation") / Path(tmp).name
            try:
                result = import_har(source, workspace, "il-bidbuy", Path.cwd())
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(result["capture_mode"], "manual-browser")
                self.assertTrue(result["raw_risk_inventory"]["cookies_present"])
            finally:
                shutil.rmtree(workspace, ignore_errors=True)

    def test_label_url_and_config_safety(self):
        for label in ("", "../raw", "a/b", "C:evil", "NUL"):
            with self.assertRaises(ValueError):
                validate_label(label)
        self.assertEqual(validate_label("Safe-01"), "safe-01")
        for url in ("file:///tmp/x", "http://127.0.0.1/x", "https://user:pw@bids.example.gov"):
            with self.assertRaises(ValueError):
                validate_public_url(url, {"bids.example.gov", "127.0.0.1"})
        cfg = CaptureConfig(
            "x",
            "X",
            "https://bids.example.gov",
            ("bids.example.gov",),
            "safe",
            Path(".sled-validation"),
        )
        cfg.validate(Path.cwd())
        with self.assertRaises(ValueError):
            CaptureConfig("x", "X", "https://evil.test", ("bids.example.gov",), "safe").validate(
                Path.cwd()
            )

    def test_sanitize_scan_determinism_and_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, one, two = Path(tmp) / "raw.har", Path(tmp) / "one.har", Path(tmp) / "two.har"
            raw.write_text(json.dumps(har()))
            kwargs = dict(
                source_id="test",
                captured_at="2026-08-03T00:00:00Z",
                sanitized_at="2026-08-03T01:00:00Z",
            )
            report = sanitize_har(raw, one, **kwargs)
            sanitize_har(raw, two, **kwargs)
            clean = one.read_text()
            self.assertNotIn("hidden-secret", clean)
            self.assertNotIn("secret-value", clean)
            self.assertNotIn("Set-Cookie", clean)
            self.assertNotIn('"cookies"', clean)
            self.assertIn("%5BREDACTED%5D", clean)
            self.assertGreater(report["action_count"], 3)
            # Input filename is intentionally excluded, so canonical artifacts match.
            self.assertEqual(one.read_text(), two.read_text())
            self.assertFalse(scan_artifact(one))
            analysis = analyze_har(one)
            self.assertEqual(analysis["access_classification"], "public_anonymous")
            self.assertTrue(analysis["capabilities"]["discovery"])
            self.assertEqual(len(analysis["contracts"]), 2)

    def test_body_binary_and_secret_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = Path(tmp) / "raw.har", Path(tmp) / "clean.har"
            value = har()
            value["log"]["entries"][0]["response"]["content"] = {
                "mimeType": "application/pdf",
                "encoding": "base64",
                "text": "A" * 100,
            }
            raw.write_text(json.dumps(value))
            sanitize_har(raw, out, source_id="x")
            self.assertTrue(
                json.loads(out.read_text())["log"]["entries"][0]["response"]["content"][
                    "_sledBodyRemoved"
                ]
            )
            suspect = Path(tmp) / "suspect"
            suspect.write_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456")
            self.assertTrue(any(x.severity == "high" for x in scan_artifact(suspect)))

    def test_review_fixture_and_ingestion_gates(self):
        records = [
            {
                "evidence_id": "e1",
                "source_id": "s1",
                "capability": "discovery",
                "classification": "public_anonymous",
                "evidence_type": "sanitized_har_contract",
                "sanitized_artifact_path": "reports/e.json",
                "verification_timestamp": "2026-08-03T00:00:00Z",
                "limitations": [],
                "output_hash": "abc",
                "reviewer_status": "unreviewed",
                "sanitization_status": "pending",
            }
        ]
        with self.assertRaises(ValueError):
            approve_evidence(
                records, "reviewer", {"discovery"}, [Finding("jwt", "x", "high", "abc")]
            )
        approval = approve_evidence(records, "reviewer", {"discovery"}, [])
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "sources.json"
            registry.write_text('{"sources": [], "evidence": []}')
            with self.assertRaises(ValueError):
                ingest_evidence(approval, registry, confirm=False)
            result = ingest_evidence(approval, registry, confirm=True, dry_run=True)
            self.assertEqual(result["records_added"], 1)
            self.assertFalse(result["live_verification_promoted"])
            artifact = Path(tmp) / "x.har"
            artifact.write_text(json.dumps(har()))
            with self.assertRaises(ValueError):
                extract_fixture(artifact, Path(tmp) / "fixture.json", approved=False)
            fixture = extract_fixture(artifact, Path(tmp) / "fixture.json", approved=True)
            self.assertFalse(fixture["live_verification"])

    def test_cli_help_and_capture_dry_run(self):
        with self.assertRaises(SystemExit) as caught:
            main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(
            main(["capture", "--source", "al-alabamabuys", "--label", "safe", "--dry-run"]), 0
        )
        self.assertEqual(
            main(["capture", "--source", "missing", "--label", "safe", "--dry-run"]), 2
        )

    @staticmethod
    def bidbuy_startup_diagnostics(*, post=True, response=True, script=True):
        rows = [
            {
                "event": "response",
                "status": 200,
                "resource_type": "document",
                "first_party": True,
                "path": "/bso/view/search/external/advancedSearchBid.xhtml",
            }
        ]
        if script:
            rows.append(
                {
                    "event": "response",
                    "status": 200,
                    "resource_type": "script",
                    "first_party": True,
                    "path": "/bso/javax.faces.resource/primefaces.js",
                }
            )
        if post:
            rows.append(
                {
                    "event": "request",
                    "method": "POST",
                    "path": "/bso/view/search/external/advancedSearchBid.xhtml",
                }
            )
        if response:
            rows.append(
                {
                    "event": "response",
                    "status": 200,
                    "request_method": "POST",
                    "path": "/bso/view/search/external/advancedSearchBid.xhtml",
                }
            )
        return rows

    def test_bidbuy_shell_without_initial_post_fails(self):
        result = evaluate_bidbuy_startup(
            self.bidbuy_startup_diagnostics(post=False, response=False),
            overlay_visible=True,
            results_state_visible=False,
        )
        self.assertEqual(result["capture_outcome"], "initialization_failed")
        self.assertEqual(result["suspected_spinner_reason"], "expected_request_not_observed")
        self.assertFalse(result["startup_succeeded"])

    def test_bidbuy_response_with_spinner_fails(self):
        result = evaluate_bidbuy_startup(
            self.bidbuy_startup_diagnostics(),
            overlay_visible=True,
            results_state_visible=True,
        )
        self.assertEqual(
            result["suspected_spinner_reason"], "response_received_spinner_remained"
        )
        self.assertIsNotNone(result["suspected_spinner_reason"])

    def test_bidbuy_expected_post_and_cleared_spinner_succeeds(self):
        result = evaluate_bidbuy_startup(
            self.bidbuy_startup_diagnostics(),
            overlay_visible=False,
            results_state_visible=True,
        )
        self.assertEqual(result["capture_outcome"], "capture_succeeded")
        self.assertTrue(result["startup_succeeded"])

    def test_bidbuy_result_and_empty_selectors_execute_independently(self):
        page = self.FakePage(css={BIDBUY_RESULT_SELECTOR: 1})
        inspection = inspect_bidbuy_result_state(page)
        self.assertEqual(inspection["result_state"], "results_observed")
        self.assertEqual(page.locator_calls, [BIDBUY_SPINNER_SELECTOR, BIDBUY_RESULT_SELECTOR])
        self.assertEqual(page.text_calls, [BIDBUY_EMPTY_RESULTS])
        self.assertNotIn("text=", BIDBUY_RESULT_SELECTOR)
        self.assertNotIn("xpath=", BIDBUY_RESULT_SELECTOR)
        self.assertIsInstance(BIDBUY_EMPTY_RESULTS, type(__import__("re").compile("")))

        empty_page = self.FakePage(text=1)
        empty = inspect_bidbuy_result_state(empty_page)
        self.assertEqual(empty["result_state"], "empty_results_observed")
        self.assertTrue(BIDBUY_EMPTY_RESULTS.search("No records found"))

    def test_bidbuy_persistent_spinner_is_initialization_failed(self):
        page = self.FakePage(css={BIDBUY_SPINNER_SELECTOR: 1})
        inspection = inspect_bidbuy_result_state(page)
        result = evaluate_bidbuy_startup(
            self.bidbuy_startup_diagnostics(),
            overlay_visible=inspection["overlay_visible"],
            results_state_visible=False,
            result_state=inspection["result_state"],
        )
        self.assertEqual(inspection["result_state"], "initialization_failed")
        self.assertEqual(result["capture_outcome"], "initialization_failed")

    def test_bidbuy_locator_failure_is_sanitized_partial_failure(self):
        page = self.FakePage(
            error=RuntimeError(
                "detached frame at https://example.gov/search?token=secret "
                "Cookie=session-secret"
            )
        )
        inspection = inspect_bidbuy_result_state(page)
        result = evaluate_bidbuy_startup(
            self.bidbuy_startup_diagnostics(),
            overlay_visible=inspection["overlay_visible"],
            results_state_visible=False,
            diagnostic_probe_failed=inspection["diagnostic_probe_failed"],
            result_state=inspection["result_state"],
        )
        self.assertEqual(result["capture_outcome"], "capture_partially_succeeded")
        self.assertFalse(result["startup_succeeded"])
        diagnostic = inspection["diagnostics"][0]["sanitized_message"]
        self.assertNotIn("secret", diagnostic)
        self.assertIn("https://example.gov/search", diagnostic)

    def test_bidbuy_closed_page_is_safe_and_preserves_raw_har(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "partial.har"
            raw.write_bytes(b"partial capture")
            inspection = inspect_bidbuy_result_state(self.FakePage(closed=True))
            self.assertTrue(inspection["diagnostic_probe_failed"])
            self.assertEqual(inspection["result_state"], "unknown")
            self.assertEqual(raw.read_bytes(), b"partial capture")

    def test_mixed_diagnostic_schema_and_request_counters_are_safe(self):
        diagnostics = [
            {
                "event_type": "request_blocked",
                "host": "www.google-analytics.com",
                "method": "GET",
            },
            {
                "event_type": "request_blocked",
                "host": "www.bidbuy.illinois.gov",
                "method": "POST",
                "essential": True,
            },
            {"event_type": "spinner_state", "classification": "spinner_visible"},
            {"event_type": "console_error", "sanitized_message": "example"},
            {"event_type": "page_error", "sanitized_message": "example"},
            {"event_type": "startup_state", "classification": "unknown"},
            {
                "event_type": "request_failed",
                "host": "www.bidbuy.illinois.gov",
                "reason": "timeout",
            },
            {"sanitized_message": "missing type"},
        ]
        normalized, summary = build_capture_summary(
            self.bidbuy_config(),
            diagnostics,
            {"allowed": {}, "blocked": {"GET": 1, "POST": 1}},
            {"capture_outcome": "capture_partially_succeeded"},
            {},
        )
        self.assertEqual(summary["blocked_first_party_requests"], 1)
        self.assertEqual(summary["blocked_third_party_requests"], 1)
        self.assertTrue(summary["essential_first_party_request_blocked"])
        self.assertEqual(summary["diagnostic_schema_errors"], 1)
        self.assertEqual(normalized[-1]["event_type"], "diagnostic_schema_error")
        self.assertTrue(
            all(row["diagnostic_schema_version"] == 1 for row in normalized)
        )

    def test_diagnostic_normalization_sanitizes_sensitive_values(self):
        diagnostic = normalize_diagnostic(
            {
                "event_type": "console_error",
                "sanitized_message": (
                    "https://example.gov/path?token=hidden Cookie=session-secret"
                ),
            }
        )
        serialized = json.dumps(diagnostic)
        self.assertNotIn("hidden", serialized)
        self.assertNotIn("session-secret", serialized)

    def test_reporting_failure_preserves_har_and_writes_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = CaptureConfig(
                **{
                    **vars(self.bidbuy_config()),
                    "output_directory": Path(tmp),
                }
            )
            raw = Path(tmp) / "raw" / "safe.har"
            raw.parent.mkdir()
            raw.write_bytes(b"partial capture")

            def fail_summary(*args):
                raise KeyError("host token=secret-value")

            artifacts = write_capture_reports(
                config=config,
                raw=raw,
                diagnostics=[{"event_type": "console_error"}],
                counts={"allowed": {}, "blocked": {}},
                startup={"capture_outcome": "capture_partially_succeeded"},
                browser_info={},
                summary_builder=fail_summary,
            )
            self.assertTrue(artifacts["reporting_failed"])
            self.assertEqual(artifacts["raw_har"], str(raw))
            self.assertEqual(raw.read_bytes(), b"partial capture")
            summary = json.loads(Path(artifacts["summary"]).read_text())
            self.assertEqual(summary["capture_outcome"], "diagnostic_summary_failed")
            self.assertNotIn("secret-value", json.dumps(summary))
            self.assertTrue(Path(artifacts["diagnostic_report"]).exists())
            self.assertTrue(Path(artifacts["capture_manifest"]).exists())

    def test_capture_resources_close_even_when_reporting_would_fail(self):
        closed = []

        class Resource:
            def __init__(self, name):
                self.name = name

            def close(self):
                closed.append(self.name)

        close_capture_resources(Resource("context"), Resource("browser"), lambda *a, **k: None)
        self.assertEqual(closed, ["context", "browser"])

    def test_bidbuy_javascript_and_request_failures_are_distinguished(self):
        diagnostics = self.bidbuy_startup_diagnostics(post=False, response=False)
        diagnostics.append({"event": "pageerror", "message": "PrimeFaces is undefined"})
        result = evaluate_bidbuy_startup(
            diagnostics, overlay_visible=True, results_state_visible=False
        )
        self.assertEqual(result["suspected_spinner_reason"], "javascript_exception")
        diagnostics[-1] = {"event": "requestfailed", "first_party": True}
        result = evaluate_bidbuy_startup(
            diagnostics, overlay_visible=True, results_state_visible=False
        )
        self.assertEqual(result["suspected_spinner_reason"], "request_failed")

    def test_telemetry_failure_does_not_fail_successful_startup(self):
        diagnostics = self.bidbuy_startup_diagnostics()
        diagnostics.append(
            {"event": "requestfailed", "first_party": False, "host": "google-analytics.com"}
        )
        result = evaluate_bidbuy_startup(
            diagnostics, overlay_visible=False, results_state_visible=True
        )
        self.assertTrue(result["startup_succeeded"])

    def test_evidence_supported_blocked_dependency_is_correlated(self):
        diagnostics = self.bidbuy_startup_diagnostics(post=False, response=False)
        diagnostics.append({"event": "policy", "likely_essential": True})
        result = evaluate_bidbuy_startup(
            diagnostics, overlay_visible=True, results_state_visible=False
        )
        self.assertEqual(result["suspected_spinner_reason"], "blocked_dependency")

    def test_diagnostics_redact_values_and_sensitive_urls(self):
        message = sanitize_diagnostic_message(
            "Failed https://example.gov/a?token=abc&email=person@example.com "
            "javax.faces.ViewState=secret Cookie:session-value"
        )
        for secret in ("abc", "person@example.com", "secret", "session-value"):
            self.assertNotIn(secret, message)
        self.assertIn("https://example.gov/a", message)

    def test_browser_and_request_policy_options_validate(self):
        for browser in ("chromium", "chrome", "msedge"):
            config = self.bidbuy_config()
            config = CaptureConfig(**{**vars(config), "browser": browser})
            config.validate(Path.cwd())
        config = self.bidbuy_config()
        with self.assertRaisesRegex(ValueError, "unsupported browser channel"):
            CaptureConfig(**{**vars(config), "browser": "firefox"}).validate(Path.cwd())
        with self.assertRaisesRegex(ValueError, "request policy"):
            CaptureConfig(**{**vars(config), "request_policy_mode": "unsafe"}).validate(
                Path.cwd()
            )


if __name__ == "__main__":
    unittest.main()
