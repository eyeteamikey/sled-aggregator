from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sled_aggregator.db.models import DocumentRetrievalJobRecord, SolicitationDocumentRecord
from sled_aggregator.db.session import get_db_session
from sled_aggregator.domain.models import DocumentCandidate, DocumentClassification
from sled_aggregator.services.document_classifier import DocumentClassifier

DbSession = Annotated[Session, Depends(get_db_session)]

router = APIRouter(prefix="/documents", tags=["documents"])
classifier = DocumentClassifier()


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    opportunity_id: str
    document_type: str
    title: str | None
    displayed_filename: str
    source_url: str
    access_state: str
    retrieval_state: str | None = None
    is_current: bool
    source_posted_at: datetime | None
    source_modified_at: datetime | None
    first_discovered_at: datetime
    last_discovered_at: datetime


class DocumentDetail(DocumentSummary):
    document_category: str | None
    eligibility_reason: str
    classification_confidence: int
    logical_document_key: str
    version_label: str | None
    version_number: int | None
    relationship_type: str
    source_metadata: dict[str, object]
    content_sha256: str | None
    content_length: int | None
    detected_media_type: str | None
    final_url: str | None
    extraction_state: str | None
    ocr_state: str | None
    structured_extraction_state: str | None


def _serialize(record: SolicitationDocumentRecord, *, detail: bool = False) -> dict[str, object]:
    data = {column.name: getattr(record, column.name) for column in record.__table__.columns}
    # Do not expose storage keys, leases, internal errors, or unrelated future internals.
    allowed = set((DocumentDetail if detail else DocumentSummary).model_fields)
    return {key: value for key, value in data.items() if key in allowed}


@router.post("/classify", response_model=DocumentClassification)
async def classify_document(payload: DocumentCandidate) -> DocumentClassification:
    return classifier.classify(payload)


@router.get("", response_model=list[DocumentSummary])
def list_documents(
    session: DbSession, opportunity_id: str | None = None, document_type: str | None = None,
    is_current: bool | None = None, access_state: str | None = None,
    retrieval_state: str | None = None, connector: str | None = None,
    tenant: str | None = None, jurisdiction: str | None = None,
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
) -> list[dict[str, object]]:
    statement = select(SolicitationDocumentRecord, DocumentRetrievalJobRecord.retrieval_state).outerjoin(DocumentRetrievalJobRecord)
    filters = {"opportunity_id": opportunity_id, "document_type": document_type, "is_current": is_current, "access_state": access_state, "connector": connector, "tenant": tenant, "jurisdiction": jurisdiction}
    for field, value in filters.items():
        if value is not None:
            statement = statement.where(getattr(SolicitationDocumentRecord, field) == value)
    if retrieval_state is not None:
        statement = statement.where(DocumentRetrievalJobRecord.retrieval_state == retrieval_state)
    rows = session.execute(statement.order_by(SolicitationDocumentRecord.first_discovered_at, SolicitationDocumentRecord.id).limit(limit).offset(offset))
    result = []
    for record, state in rows:
        item = _serialize(record)
        item["retrieval_state"] = state
        result.append(item)
    return result


@router.get("/queue/stats")
def queue_stats(session: DbSession) -> dict[str, int]:
    return dict(session.execute(select(DocumentRetrievalJobRecord.retrieval_state, func.count()).group_by(DocumentRetrievalJobRecord.retrieval_state)).all())


@router.get("/opportunity/{opportunity_id}", response_model=list[DocumentSummary])
def list_opportunity_documents(opportunity_id: str, session: DbSession, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> list[dict[str, object]]:
    rows = session.scalars(select(SolicitationDocumentRecord).where(SolicitationDocumentRecord.opportunity_id == opportunity_id).order_by(SolicitationDocumentRecord.first_discovered_at, SolicitationDocumentRecord.id).limit(limit).offset(offset))
    return [_serialize(record) for record in rows]


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, session: DbSession) -> dict[str, object]:
    record = session.get(SolicitationDocumentRecord, document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document not found")
    result = _serialize(record, detail=True)
    job = session.scalar(select(DocumentRetrievalJobRecord).where(DocumentRetrievalJobRecord.document_id == document_id))
    result["retrieval_state"] = job.retrieval_state if job else None
    return result
