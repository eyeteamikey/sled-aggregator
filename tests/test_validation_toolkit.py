import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sled_aggregator.validation.__main__ import main
from sled_aggregator.validation.toolkit import (
    CaptureConfig,
    Finding,
    analyze_har,
    approve_evidence,
    classify_request,
    evaluate_bidbuy_startup,
    extract_fixture,
    import_har,
    ingest_evidence,
    sanitize_diagnostic_message,
    sanitize_har,
    scan_artifact,
    validate_label,
    validate_public_url,
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
