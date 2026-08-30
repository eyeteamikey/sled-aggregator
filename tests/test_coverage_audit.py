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
    closeout_plan,
    connector_inventory,
    gaps_for,
    generated_reports,
    load,
    render_csv,
    render_json,
    render_markdown,
    report_drift,
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

    def test_pipeline_count_is_derived_from_connector_capabilities(self):
        report = build_report(jdata=self.jdata, sdata=self.sdata)
        self.assertEqual(report["summary"]["public_document_pipeline_count"], 10)

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
        source = deepcopy(
            next(x for x in self.sdata["sources"] if x["source_id"] == "ca-cal-eprocure")
        )
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
        first = build_report(jdata=self.jdata, sdata=self.sdata)["prioritized_recommendations"]
        self.assertEqual(
            first, build_report(jdata=self.jdata, sdata=self.sdata)["prioritized_recommendations"]
        )
        self.assertTrue(all(x["source_ids"] and x["jurisdiction_ids"] for x in first))
        self.assertFalse(any("hypothetical" in str(x).lower() for x in first))
        capture = [x for x in first if x["task_type"] == "public_contract_capture"]
        self.assertEqual(
            [x["source_ids"] for x in capture], [["al-alabamabuys"], ["oh-ohiobuys"]]
        )
        self.assertTrue(all(x["score"] == 20 for x in capture))

    def test_breadth_closeout_is_complete_and_machine_executable(self):
        plan = closeout_plan(build_report(jdata=self.jdata, sdata=self.sdata))
        self.assertTrue(plan["breadth_complete"])
        self.assertEqual(
            plan["breadth_totals"],
            {
                "target_jurisdictions": 56,
                "primary_sources_identified": 20,
                "platform_families_identified": 18,
                "registered_connector_profiles": 18,
                "fixture_verified": 18,
                "discovery_capable": 18,
                "detail_capable": 16,
                "attachment_capable": 16,
                "document_pipeline_compatible": 6,
                "live_verified": 0,
                "production_monitored": 0,
                "tier_0_remaining": 36,
                "blocked_jurisdictions": 15,
            },
        )
        self.assertEqual(len(plan["unidentified_primary_sources"]), 36)
        self.assertEqual(
            plan["unclassified_primary_sources"], ["al-alabamabuys", "oh-ohiobuys"]
        )
        self.assertEqual(plan["platform_identified_connector_missing"], [])
        self.assertEqual(len(plan["validation_tasks"]), 18)
        self.assertEqual(
            [task["order"] for task in plan["validation_tasks"]], list(range(1, 19))
        )
        method_policies = {
            task["source_id"]: task["method_policy"] for task in plan["validation_tasks"]
        }
        self.assertEqual(method_policies["il-bidbuy"], ["GET", "POST"])
        post_sources = {
            "al-opelika-tyler-munis-vss",
            "ia-impacs",
            "il-bidbuy",
            "ma-commbuys",
            "ut-u3p",
        }
        self.assertTrue(
            all(
                methods == (["GET", "POST"] if source_id in post_sources else ["GET"])
                for source_id, methods in method_policies.items()
            )
        )

    def test_authoritative_control_plane_and_local_regressions(self):
        report = build_report(jdata=self.jdata, sdata=self.sdata)
        records = {row["code"]: row for row in report["jurisdiction_records"]}
        self.assertEqual(report["summary"]["jurisdiction_count"], 56)
        self.assertEqual(report["summary"]["baseline_operational_count"], 18)
        for code, source_id in (("AL", "al-alabamabuys"), ("OH", "oh-ohiobuys")):
            self.assertFalse(records[code]["local_evidence_only"])
            self.assertEqual(records[code]["primary_source_id"], source_id)
            self.assertFalse(records[code]["baseline_operational"])
            self.assertEqual(records[code]["coverage_tier"], 1)
        self.assertTrue(records["RI"]["baseline_operational"])
        self.assertEqual(records["RI"]["primary_source_id"], "ri-ocean-state-procures")
        self.assertEqual(records["RI"]["supplemental_source_ids"], ["ri-rivip-external"])
        self.assertTrue(
            all(
                "jurisdiction_id" in row and "primary_source_id" in row
                for row in report["jurisdiction_records"]
            )
        )

        maine = records["ME"]
        self.assertEqual(maine["primary_source_id"], "me-vss")
        self.assertEqual(maine["platform_family"], "cgi/advantage-vss")
        self.assertTrue(maine["fixture_verified"])
        self.assertTrue(maine["baseline_operational"])
        self.assertTrue(maine["attachment_capable"])
        self.assertFalse(maine["document_pipeline_capable"])

        michigan = records["MI"]
        self.assertEqual(michigan["primary_source_id"], "mi-sigma-vss")
        self.assertEqual(michigan["supplemental_source_ids"], ["mi-detroit-oracle-fusion"])
        self.assertTrue(michigan["baseline_operational"])
        self.assertTrue(michigan["attachment_capable"])
        self.assertFalse(michigan["document_pipeline_capable"])

    def test_jaggaer_statewide_profiles_have_reviewed_contract_evidence(self):
        report = build_report(jdata=self.jdata, sdata=self.sdata)
        records = {row["code"]: row for row in report["jurisdiction_records"]}
        for code, source_id, profile in (
            ("IA", "ia-impacs", "iowa/impacs"),
            ("UT", "ut-u3p", "utah/u3p"),
        ):
            source = next(x for x in self.sdata["sources"] if x["source_id"] == source_id)
            evidence = [x for x in self.sdata["evidence"] if x["source_id"] == source_id]
            self.assertEqual(records[code]["primary_source_id"], source_id)
            self.assertTrue(records[code]["baseline_operational"])
            self.assertTrue(records[code]["attachment_capable"])
            self.assertFalse(records[code]["document_pipeline_capable"])
            self.assertEqual(source["portal_profile_key"], profile)
            self.assertEqual(source["verification_status"], "fixture_verified")
            self.assertEqual(source["last_verified_date"], "2026-08-13")
            self.assertEqual(source["document_pipeline_classification"], "manifest_only")
            self.assertTrue(any(x["evidence_type"] == "official_public_landing_page" for x in evidence))
            self.assertTrue(any(x["evidence_type"] == "sanitized_fixture" for x in evidence))
            self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_periscope_statewide_profiles_are_fixture_not_live_verified(self):
        report = build_report(jdata=self.jdata, sdata=self.sdata)
        records = {row["code"]: row for row in report["jurisdiction_records"]}
        expected = {
            "IL": ("il-bidbuy", "illinois/bidbuy"),
            "MA": ("ma-commbuys", "massachusetts/commbuys"),
            "NV": ("nv-nevadaepro", "nevada/nevadaepro"),
            "NJ": ("nj-njstart", "new-jersey/njstart"),
            "OR": ("or-oregonbuys", "oregon/oregonbuys"),
            "VI": ("vi-gvibuy", "us-virgin-islands/gvibuy"),
        }
        for code, (source_id, profile) in expected.items():
            source = next(x for x in self.sdata["sources"] if x["source_id"] == source_id)
            evidence = [x for x in self.sdata["evidence"] if x["source_id"] == source_id]
            self.assertEqual(records[code]["primary_source_id"], source_id)
            self.assertTrue(records[code]["baseline_operational"])
            self.assertTrue(records[code]["attachment_capable"])
            self.assertFalse(records[code]["document_pipeline_capable"])
            self.assertEqual(source["portal_profile_key"], profile)
            self.assertEqual(source["verification_status"], "fixture_verified")
            if source_id == "il-bidbuy":
                self.assertEqual(source["last_verified_date"], "2026-08-12")
                self.assertEqual(source["allowed_http_methods"], ["GET", "POST"])
            elif source_id == "ma-commbuys":
                self.assertEqual(source["last_verified_date"], "2026-08-13")
                self.assertEqual(source["allowed_http_methods"], ["GET", "POST"])
            else:
                self.assertIsNone(source["last_verified_date"])
            self.assertEqual(source["document_pipeline_classification"], "manifest_only")
            self.assertTrue(any(x["evidence_type"] == "official_public_landing_page" for x in evidence))
            self.assertTrue(any(x["evidence_type"] == "sanitized_fixture" for x in evidence))
            self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_webprocure_statewide_profiles_are_discovery_only_and_not_live_verified(self):
        report = build_report(jdata=self.jdata, sdata=self.sdata)
        records = {row["code"]: row for row in report["jurisdiction_records"]}
        expected = {
            "CT": ("ct-ctsource", "connecticut/ctsource"),
            "RI": ("ri-ocean-state-procures", "rhode-island/ocean-state-procures"),
        }
        for code, (source_id, profile) in expected.items():
            source = next(x for x in self.sdata["sources"] if x["source_id"] == source_id)
            evidence = [x for x in self.sdata["evidence"] if x["source_id"] == source_id]
            self.assertEqual(records[code]["primary_source_id"], source_id)
            self.assertTrue(records[code]["baseline_operational"])
            self.assertTrue(records[code]["discovery_capable"])
            self.assertFalse(records[code]["detail_capable"])
            self.assertFalse(records[code]["attachment_capable"])
            self.assertEqual(source["portal_profile_key"], profile)
            self.assertEqual(source["verification_status"], "fixture_verified")
            self.assertEqual(source["last_verified_date"], "2026-08-13")
            self.assertEqual(source["captcha_classification"], "captcha_present")
            self.assertEqual(source["document_pipeline_classification"], "unknown")
            self.assertTrue(any(x["evidence_type"] == "official_public_landing_page" for x in evidence))
            self.assertTrue(any(x["evidence_type"] == "sanitized_fixture" for x in evidence))
            self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_maine_fixture_evidence_is_not_live_verification(self):
        source = next(x for x in self.sdata["sources"] if x["source_id"] == "me-vss")
        evidence = [x for x in self.sdata["evidence"] if x["source_id"] == "me-vss"]
        self.assertEqual(source["verification_status"], "fixture_verified")
        self.assertEqual(source["last_verified_date"], "2026-08-13")
        self.assertIn("404/403", source["blocker_reason"])
        self.assertEqual(source["document_pipeline_classification"], "manifest_only")
        self.assertTrue(any(x["evidence_type"] == "official_public_landing_page" for x in evidence))
        self.assertTrue(any(x["evidence_type"] == "sanitized_fixture" for x in evidence))
        self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_michigan_sigma_fixture_evidence_is_not_live_verification(self):
        source = next(x for x in self.sdata["sources"] if x["source_id"] == "mi-sigma-vss")
        evidence = [x for x in self.sdata["evidence"] if x["source_id"] == "mi-sigma-vss"]
        self.assertEqual(source["portal_profile_key"], "michigan/sigma-vss")
        self.assertEqual(source["verification_status"], "fixture_verified")
        self.assertEqual(source["last_verified_date"], "2026-08-13")
        self.assertIn("HTTP 404", source["blocker_reason"])
        self.assertEqual(source["document_pipeline_classification"], "manifest_only")
        self.assertTrue(any(x["evidence_type"] == "official_public_landing_page" for x in evidence))
        self.assertTrue(any(x["evidence_type"] == "sanitized_fixture" for x in evidence))
        self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_affirmative_claims_require_evidence_and_valid_pipeline_adapter(self):
        data = deepcopy(self.sdata)
        data["evidence"] = [e for e in data["evidence"] if e["source_id"] != "ca-cal-eprocure"]
        self.assertTrue(any(x.field == "evidence" for x in validate(self.jdata, data)))
        data = deepcopy(self.sdata)
        source = next(x for x in data["sources"] if x["source_id"] == "ca-cal-eprocure")
        source["connector_name"] = "webprocure/proactis"
        self.assertTrue(
            any(x.field == "document_pipeline_classification" for x in validate(self.jdata, data))
        )

    def test_california_official_evidence_does_not_overstate_live_validation(self):
        source = next(x for x in self.sdata["sources"] if x["source_id"] == "ca-cal-eprocure")
        evidence = [
            x for x in self.sdata["evidence"] if x["source_id"] == "ca-cal-eprocure"
        ]
        self.assertEqual(source["verification_status"], "fixture_verified")
        self.assertIsNone(source["last_verified_date"])
        self.assertIn("www.dgs.ca.gov", source["evidence_url"])
        self.assertTrue(
            any(x["evidence_type"] == "official_public_landing_page" for x in evidence)
        )
        self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_georgia_official_evidence_does_not_overstate_live_validation(self):
        source = next(x for x in self.sdata["sources"] if x["source_id"] == "ga-gpr")
        evidence = [x for x in self.sdata["evidence"] if x["source_id"] == "ga-gpr"]
        self.assertEqual(source["verification_status"], "fixture_verified")
        self.assertIsNone(source["last_verified_date"])
        self.assertIn("doas.ga.gov", source["evidence_url"])
        self.assertTrue(
            any(x["evidence_type"] == "official_public_landing_page" for x in evidence)
        )
        self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_maryland_official_evidence_does_not_overstate_live_validation(self):
        source = next(x for x in self.sdata["sources"] if x["source_id"] == "md-emma")
        evidence = [x for x in self.sdata["evidence"] if x["source_id"] == "md-emma"]
        self.assertEqual(source["verification_status"], "fixture_verified")
        self.assertIsNone(source["last_verified_date"])
        self.assertIn("procurement.maryland.gov", source["evidence_url"])
        self.assertTrue(
            any(x["evidence_type"] == "official_public_landing_page" for x in evidence)
        )
        self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_pennsylvania_official_evidence_does_not_overstate_live_validation(self):
        source = next(x for x in self.sdata["sources"] if x["source_id"] == "pa-emarketplace")
        evidence = [x for x in self.sdata["evidence"] if x["source_id"] == "pa-emarketplace"]
        self.assertEqual(source["verification_status"], "fixture_verified")
        self.assertIsNone(source["last_verified_date"])
        self.assertIn("emarketplace.state.pa.us", source["evidence_url"])
        self.assertTrue(any(x["evidence_type"] == "official_public_portal" for x in evidence))
        self.assertFalse(any("live" in x["capabilities"] for x in evidence))

    def test_generated_report_set_is_deterministic_and_consistent(self):
        report = build_report(jdata=self.jdata, sdata=self.sdata)
        first = generated_reports(report)
        self.assertEqual(first, generated_reports(report))
        self.assertEqual(
            set(first),
            {
                "coverage-summary.json",
                "capability-matrix.md",
                "connector-family-reuse.md",
                "missing-coverage.md",
                "blocked-sources.md",
                "document-pipeline-readiness.md",
                "next-pr-queue.json",
                "live-validation-tasks.json",
                "breadth-closeout.json",
                "manual-capture-instructions.md",
                "pr50-milestone.json",
                "pr50-milestone.md",
            },
        )
        milestone = json.loads(first["pr50-milestone.json"])
        self.assertEqual(milestone["coverage_totals"]["total_jurisdictions"], 56)
        self.assertEqual(len(milestone["capability_matrix"]), 56)
        self.assertFalse(milestone["definition_of_done"]["all_live_verified"])
        self.assertEqual(first["pr50-milestone.md"], first["pr50-milestone.md"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for name, content in first.items():
                (path / name).write_text(content)
            with patch("sled_aggregator.coverage.core.build_report", return_value=report):
                self.assertEqual(report_drift(path), [])

    def test_reports_are_deterministic_and_parseable(self):
        report = build_report("2026-07-30", self.jdata, self.sdata)
        self.assertEqual(render_json(report), render_json(report))
        self.assertEqual(json.loads(render_json(report))["summary"]["jurisdiction_count"], 56)
        rows = list(csv.DictReader(io.StringIO(render_csv(report))))
        # Rhode Island and Michigan retain separate supplemental sources; New
        # Jersey and California include validated local OpenGov sources; the
        # local DemandStar inventory now also includes Will and Ramsey counties.
        self.assertEqual(len(rows), 63)
        self.assertEqual(len({x["jurisdiction_code"] for x in rows}), 56)
        markdown = render_markdown(report)
        self.assertEqual(markdown, render_markdown(report))
        self.assertIn("Fixture verification is not live verification", markdown)
        self.assertEqual(report["as_of"], "2026-07-30")

    def test_cli_commands_and_output(self):
        self.assertEqual(main(["validate"]), 0)
        for command in (
            "gaps",
            "recommend",
            "status",
            "matrix",
            "missing",
            "blocked",
            "documents",
            "queue",
            "closeout",
            "validation-tasks",
        ):
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
