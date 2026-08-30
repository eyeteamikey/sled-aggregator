import unittest
from copy import deepcopy

from sled_aggregator.coverage.core import SOURCES_PATH, load, validate
from sled_aggregator.coverage.validation_metrics import (
    CAPABILITIES,
    EVIDENCE_TIERS,
    METRICS_PATH,
    NEXT_WAVE_PATH,
    derive_metrics,
)


class SledValidationMetricsTests(unittest.TestCase):
    def setUp(self):
        self.sources = load(SOURCES_PATH)

    def test_committed_metrics_are_deterministically_derived(self):
        self.assertEqual(load(METRICS_PATH), derive_metrics(self.sources))
        self.assertEqual(derive_metrics(self.sources), derive_metrics(deepcopy(self.sources)))

    def test_every_record_has_exactly_one_tier_and_complete_capability_matrix(self):
        self.assertTrue(
            all(row["evidence_tier"] in EVIDENCE_TIERS for row in self.sources["sources"])
        )
        self.assertTrue(
            all(set(row["capabilities"]) == set(CAPABILITIES) for row in self.sources["sources"])
        )
        self.assertEqual(validate(sdata=self.sources), [])

    def test_six_reconciled_families_have_two_distinct_tenants(self):
        expected = {
            "public-purchase",
            "euna/openbids-demandstar",
            "cgi/advantage-vss",
            "bidnet-direct",
            "euna/bonfire",
            "planetbids",
        }
        for family in expected:
            tenants = {
                row["tenant_id"]
                for row in self.sources["sources"]
                if row.get("connector_name") == family and row["last_verified_date"] == "2026-08-30"
            }
            self.assertGreaterEqual(len(tenants), 2, family)

    def test_download_requires_explicit_live_download_evidence(self):
        metrics = derive_metrics(self.sources)
        expected = sum(
            row["capabilities"]["anonymous_document_download"] == "live_verified"
            for row in self.sources["sources"]
        )
        self.assertEqual(metrics["counts"]["anonymous_document_downloads_verified"], expected)
        self.assertEqual(expected, 0)

    def test_funnel_denominators_are_explicit_and_arithmetically_sound(self):
        for stage in derive_metrics(self.sources)["coverage_funnel"]:
            self.assertEqual(stage["completed"] + stage["remaining"], stage["denominator"])
            self.assertAlmostEqual(
                stage["percentage"], round(stage["completed"] * 100 / stage["denominator"], 4)
            )

    def test_next_wave_has_six_deepening_and_four_new_family_tasks(self):
        targets = load(NEXT_WAVE_PATH)["targets"]
        self.assertEqual(len(targets), 10)
        self.assertEqual(sum(row["task_type"] == "deepening" for row in targets), 6)
        self.assertEqual(sum(row["task_type"] == "new_family_validation" for row in targets), 4)
        self.assertEqual(len({row["codex_task_identifier"] for row in targets}), 10)
        self.assertTrue(
            all(len(row["primary_tenants"]) == 2 and row["fallback_tenant"] for row in targets)
        )


if __name__ == "__main__":
    unittest.main()
