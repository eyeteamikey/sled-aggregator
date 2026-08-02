import unittest

from sled_aggregator.db.memory import InMemoryOpportunityRepository
from sled_aggregator.domain.enums import AccessState
from sled_aggregator.domain.models import DocumentCandidate, RawOpportunity, SourceRef
from sled_aggregator.services.document_orchestration import candidates_from_payload
from sled_aggregator.services.normalizer import OpportunityNormalizer
from sled_aggregator.services.opportunity_service import OpportunityService


class _CapturingIngestor:
    def __init__(self):
        self.calls = []

    def ingest(self, opportunity, candidates):
        self.calls.append((opportunity, list(candidates)))


class CollectionDocumentIntegrationTests(unittest.TestCase):
    def test_collection_persists_before_nonblocking_document_handoff(self):
        ingestor = _CapturingIngestor()
        service = OpportunityService(InMemoryOpportunityRepository(), document_ingestor=ingestor)
        raw = RawOpportunity(
            source=SourceRef(
                platform_family="oracle/fusion-rest",
                jurisdiction="Michigan",
                source_id="auction-1",
                opportunity_url="https://oracle.example.gov/opportunity/1",
            ),
            title="Fixture RFP",
            agency="Fixture City",
        )
        candidate = DocumentCandidate(
            opportunity_id="auction-1",
            source_document_url="https://oracle.example.gov/document/10",
            source_opportunity_url=raw.source.opportunity_url,
            source_document_id="10",
            filename="RFP.pdf",
        )

        result = service.ingest(raw, document_candidates=[candidate])

        self.assertTrue(result.created)
        self.assertEqual(ingestor.calls[0][0].source.source_id, "auction-1")
        self.assertEqual(ingestor.calls[0][1], [candidate])

    def test_connector_without_documents_is_unchanged(self):
        ingestor = _CapturingIngestor()
        service = OpportunityService(InMemoryOpportunityRepository(), document_ingestor=ingestor)
        raw = RawOpportunity(
            source=SourceRef(
                platform_family="webprocure",
                jurisdiction="Connecticut",
                source_id="1",
                opportunity_url="https://example.gov/1",
            ),
            title="No documents",
            agency="Fixture Agency",
        )
        service.ingest(raw)
        self.assertEqual(ingestor.calls[0][1], [])

    def test_pennsylvania_payload_normalizes_public_and_restricted_documents(self):
        raw = RawOpportunity(
            source=SourceRef(
                platform_family="pennsylvania/emarketplace",
                jurisdiction="Pennsylvania",
                source_id="sid:1",
                opportunity_url="https://www.emarketplace.state.pa.us/BidDetail.aspx?SID=1",
            ),
            title="PA fixture",
            agency="Commonwealth",
            raw_payload={
                "document_links": [
                    {
                        "source_url": "https://www.emarketplace.state.pa.us/docs/rfp.pdf",
                        "displayed_title": "RFP",
                        "displayed_filename": "rfp.pdf",
                        "document_category": "solicitation",
                        "access_state": "public",
                        "retrieval_eligible": True,
                    },
                    {
                        "source_url": "https://supplier.example.gov/document/2",
                        "displayed_title": "Supplier attachment",
                        "access_state": "supplier_portal_required",
                        "retrieval_eligible": False,
                    },
                ]
            },
        )
        candidates = candidates_from_payload(OpportunityNormalizer().normalize(raw))
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].access_state, AccessState.PUBLIC)
        self.assertEqual(candidates[1].access_state, AccessState.REGISTRATION_REQUIRED)
        self.assertFalse(candidates[1].publicly_retrievable)


if __name__ == "__main__":
    unittest.main()
