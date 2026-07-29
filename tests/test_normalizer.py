import unittest

from sled_aggregator.domain.models import RawOpportunity, SourceRef
from sled_aggregator.services.normalizer import OpportunityNormalizer


class OpportunityNormalizerTests(unittest.TestCase):
    def test_normalizes_text_categories_and_stable_key(self) -> None:
        raw = RawOpportunity(
            source=SourceRef(
                platform_family="WebProcure",
                jurisdiction="Missouri",
                source_id=" BID-123 ",
                opportunity_url="https://example.gov/opportunity/123",
            ),
            title="  Software   testing services ",
            agency=" Department   of Administration ",
            categories=["QA", "QA", " Automation "],
        )

        first = OpportunityNormalizer().normalize(raw)
        second = OpportunityNormalizer().normalize(raw)

        self.assertEqual(first.title, "Software testing services")
        self.assertEqual(first.agency, "Department of Administration")
        self.assertEqual(first.categories, ["Automation", "QA"])
        self.assertEqual(first.canonical_key, second.canonical_key)


if __name__ == "__main__":
    unittest.main()
