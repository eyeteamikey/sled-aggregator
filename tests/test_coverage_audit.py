import csv
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from sled_aggregator.coverage.__main__ import main
from sled_aggregator.coverage.core import (
    JURISDICTIONS_PATH,
    SOURCES_PATH,
    build_report,
    connector_inventory,
    gaps_for,
    load,
    recommendations,
    render_csv,
    render_json,
    render_markdown,
    tier,
    validate,
)


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        self.jdata = load(JURISDICTIONS_PATH)
        self.sdata = load(SOURCES_PATH)

    def test_canonical_jurisdictions(self):
        rows = self.jdata["jurisdictions"]
        self.assertEqual(len(rows), 56)
        self.assertEqual(sum(x["type"] == "state" for x in rows), 50)
        self.assertEqual(sum(x["type"] == "district" for x in rows), 1)
        self.assertEqual(sum(x["inhabited_territory"] for x in rows), 5)
        self.assertEqual(len({x["code"] for x in rows}), 56)
        self.assertEqual(len({x["name"] for x in rows}), 56)
        self.assertEqual({x["type"] for x in rows}, {"state", "district", "territory"})

    def test_registry_is_valid(self):
        self.assertEqual(validate(self.jdata, self.sdata), [])

    def test_strict_schema_and_relationship_validation(self):
        cases = [
            ("verification_status", "typo"),
            ("jurisdiction_code", "XX"),
            ("official_url", "ftp://localhost/a"),
            ("official_url", "https://user:pass@example.com/a"),
            ("replacement_source", "absent"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = deepcopy(self.sdata)
                data["sources"][0][field] = value
                self.assertTrue(any(x.field == field for x in validate(self.jdata, data)))
        data = deepcopy(self.sdata)
        data["sources"][0]["misspelled_status"] = "active"
        self.assertTrue(any(x.field == "unknown_fields" for x in validate(self.jdata, data)))

    def test_duplicate_missing_connector_and_live_evidence(self):
        data = deepcopy(self.sdata)
        data["sources"].append(deepcopy(data["sources"][0]))
        self.assertTrue(any(x.field == "key" for x in validate(self.jdata, data)))
        data = deepcopy(self.sdata)
        data["sources"][0].update(connector_name="missing/family", connector_status="implemented")
        self.assertTrue(any(x.field == "connector_name" for x in validate(self.jdata, data)))
        data = deepcopy(self.sdata)
        data["sources"][0]["verification_status"] = "live_public_verified"
        self.assertTrue(any(x.field == "verification_status" for x in validate(self.jdata, data)))

    def test_inventory_is_canonical_and_aliases_unique(self):
        rows = connector_inventory(self.sdata["sources"])
        self.assertEqual(len(rows), 21)
        self.assertEqual(len({x["canonical_name"] for x in rows}), len(rows))
        aliases = [a for row in rows for a in row["aliases"]]
        self.assertEqual(len(aliases), len(set(aliases)))
        self.assertTrue(all(x["implementation_module"] and x["registry_presence"] for x in rows))
        self.assertIn("rhode-island/rivip-external", {x["canonical_name"] for x in rows})
        self.assertTrue(any(x["profile_count"] == 0 for x in rows))

    def test_tier_rules(self):
        inventory = {x["canonical_name"]: x for x in connector_inventory(self.sdata["sources"])}
        source = deepcopy(self.sdata["sources"][0])
        self.assertEqual(tier([], inventory), 0)
        missing = {**source, "connector_status": "missing"}
        self.assertEqual(tier([missing], inventory), 1)
        self.assertEqual(tier([source], inventory), 2)
        source.update(
            connector_status="implemented",
            document_access="unavailable",
            detail_access="metadata_only",
        )
        self.assertEqual(tier([source], inventory), 3)
        source.update(detail_access="public", document_access="mixed")
        self.assertEqual(tier([source], inventory), 4)
        inventory[source["connector_name"]]["document_pipeline_compatible"] = True
        source["document_access"] = "public"
        self.assertEqual(tier([source], inventory), 5)
        source["verification_status"] = "live_public_verified"
        self.assertEqual(tier([source], inventory), 6)
        source["verification_status"] = "changed_markup"
        self.assertEqual(tier([source], inventory), 2)
        source["verification_status"] = "migrated"
        self.assertEqual(tier([source], inventory), 2)
        source.update(verification_status="fixture_verified", document_access="login_required")
        self.assertEqual(tier([source], inventory), 3)

    def test_multiple_gaps_and_territory_gap(self):
        territory = next(x for x in self.jdata["jurisdictions"] if x["code"] == "AS")
        self.assertEqual(gaps_for(territory, []), ["no_source_identified", "territory_gap"])
        source = deepcopy(self.sdata["sources"][0])
        source.update(
            connector_status="missing",
            verification_status="captcha_required",
            document_access="registration_required",
        )
        gaps = gaps_for(territory, [source])
        self.assertIn("connector_missing", gaps)
        self.assertIn("documents_gated", gaps)
        self.assertIn("captcha_blocked", gaps)
        self.assertIn("incomplete_local_coverage", gaps)

    def test_recommendations_are_deterministic_and_transparent(self):
        first = recommendations(self.sdata["family_hypotheses"])
        self.assertEqual(first, recommendations(self.sdata["family_hypotheses"]))
        self.assertTrue(all(x["factors"] and isinstance(x["score"], int) for x in first))
        self.assertEqual(first, sorted(first, key=lambda x: (-x["score"], x["family"])))
        statuses = {x["family"]: x["evidence_status"] for x in first}
        self.assertEqual(statuses["Oracle Cloud Procurement"], "implemented_family")
        self.assertEqual(statuses["Tyler Munis/VSS public bid search"], "implemented_family")
        self.assertEqual(
            statuses["public CSV, RSS, XML, and JSON feeds"], "unsupported_candidate"
        )

    def test_reports_are_deterministic_and_parseable(self):
        report = build_report("2026-07-30", self.jdata, self.sdata)
        self.assertEqual(render_json(report), render_json(report))
        self.assertEqual(json.loads(render_json(report))["summary"]["jurisdiction_count"], 56)
        rows = list(csv.DictReader(io.StringIO(render_csv(report))))
        self.assertEqual(len(rows), 56)
        self.assertEqual(len({x["jurisdiction_code"] for x in rows}), 56)
        markdown = render_markdown(report)
        self.assertEqual(markdown, render_markdown(report))
        self.assertIn("Fixture verification is not live verification", markdown)
        self.assertEqual(report["as_of"], "2026-07-30")

    def test_cli_commands_and_output(self):
        self.assertEqual(main(["validate"]), 0)
        for command in ("gaps", "recommend"):
            self.assertEqual(main([command]), 0)
        with tempfile.TemporaryDirectory() as directory:
            for fmt in ("json", "csv", "markdown"):
                output = Path(directory) / f"report.{fmt}"
                self.assertEqual(
                    main(
                        [
                            "report",
                            "--format",
                            fmt,
                            "--output",
                            str(output),
                            "--as-of",
                            "2026-07-30",
                        ]
                    ),
                    0,
                )
                self.assertTrue(output.read_text())

    def test_cli_validation_failure_is_nonzero(self):
        with patch(
            "sled_aggregator.coverage.__main__.validate",
            return_value=[
                type("Issue", (), {"severity": "error", "as_dict": lambda self: {"field": "bad"}})()
            ],
        ):
            self.assertEqual(main(["validate"]), 1)


if __name__ == "__main__":
    unittest.main()
