import unittest

from sled_aggregator.db.memory import InMemoryOpportunityRepository
from sled_aggregator.domain.models import RawOpportunity, SourceRef
from sled_aggregator.services.opportunity_service import OpportunityService


def raw(title: str = "Testing services") -> RawOpportunity:
    return RawOpportunity(
        source=SourceRef(
            platform_family="webprocure",
            jurisdiction="Connecticut",
            source_id="bid-123",
            opportunity_url="https://example.gov/opportunities/123",
        ),
        title=title,
        agency="Department of Administrative Services",
        raw_payload={"bidid": "bid-123"},
    )


class OpportunityServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryOpportunityRepository()
        self.service = OpportunityService(self.repository)

    def test_ingest_creates_then_updates_by_source_identity(self) -> None:
        first = self.service.ingest(raw())
        second = self.service.ingest(raw("Updated testing services"))

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(len(self.service.list()), 1)
        self.assertEqual(self.service.list()[0].title, "Updated testing services")
        self.assertEqual(self.service.list()[0].raw_payload["bidid"], "bid-123")

    def test_repository_returns_copies(self) -> None:
        self.service.ingest(raw())
        result = self.service.list()
        result[0].title = "Mutated outside repository"
        self.assertEqual(self.service.list()[0].title, "Testing services")


if __name__ == "__main__":
    unittest.main()
