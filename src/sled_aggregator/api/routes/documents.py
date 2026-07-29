from fastapi import APIRouter

from sled_aggregator.domain.models import DocumentCandidate, DocumentClassification
from sled_aggregator.services.document_classifier import DocumentClassifier

router = APIRouter(prefix="/documents", tags=["documents"])
classifier = DocumentClassifier()


@router.post("/classify", response_model=DocumentClassification)
async def classify_document(payload: DocumentCandidate) -> DocumentClassification:
    return classifier.classify(payload)
