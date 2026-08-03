import json
import tempfile
import unittest
from pathlib import Path

from sled_aggregator.validation.__main__ import main
from sled_aggregator.validation.toolkit import (
    CaptureConfig,
    Finding,
    analyze_har,
    approve_evidence,
    extract_fixture,
    ingest_evidence,
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


if __name__ == "__main__":
    unittest.main()
