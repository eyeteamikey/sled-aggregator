import unittest

from sled_aggregator.domain.enums import AccessState, DocumentEligibility, DocumentRole
from sled_aggregator.domain.models import DocumentCandidate
from sled_aggregator.services.document_classifier import DocumentClassifier


def candidate(filename: str, access_state: AccessState = AccessState.PUBLIC) -> DocumentCandidate:
    return DocumentCandidate(
        opportunity_id="opp-1",
        source_document_url="https://example.gov/files/document.pdf",
        source_opportunity_url="https://example.gov/opportunities/1",
        filename=filename,
        access_state=access_state,
    )


class DocumentClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = DocumentClassifier()

    def test_includes_statement_of_work(self) -> None:
        result = self.classifier.classify(candidate("Attachment_02_SOW.pdf"))
        self.assertEqual(result.eligibility, DocumentEligibility.INCLUDE)
        self.assertEqual(result.role, DocumentRole.SOW)

    def test_excludes_vendor_registration(self) -> None:
        result = self.classifier.classify(candidate("Vendor Registration Guide.pdf"))
        self.assertEqual(result.eligibility, DocumentEligibility.EXCLUDE)

    def test_restricted_document_stops_retrieval(self) -> None:
        result = self.classifier.classify(
            candidate("RFP.pdf", access_state=AccessState.RESTRICTED)
        )
        self.assertEqual(result.eligibility, DocumentEligibility.RESTRICTED)

    def test_ambiguous_document_requires_review(self) -> None:
        result = self.classifier.classify(candidate("Attachment_7.pdf"))
        self.assertEqual(result.eligibility, DocumentEligibility.REVIEW)


if __name__ == "__main__":
    unittest.main()

