from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sled_aggregator.db.models import (
    OpportunityRecord,
    SolicitationChangeRecord,
    SolicitationCodeRecord,
    SolicitationConflictRecord,
    SolicitationContactRecord,
    SolicitationDeliverableRecord,
    SolicitationDocumentRecord,
    SolicitationEvaluationFactorRecord,
    SolicitationEvidenceRecord,
    SolicitationExtractionRunRecord,
    SolicitationFactRecord,
    SolicitationRequirementRecord,
    SolicitationSectionRecord,
    SolicitationSnapshotRecord,
)
from sled_aggregator.db.session import get_db_session
from sled_aggregator.documents.intelligence_export import StructuredExportService

DbSession = Annotated[Session, Depends(get_db_session)]
router = APIRouter(
    prefix="/opportunities/{opportunity_id}/intelligence", tags=["solicitation-intelligence"]
)


def require(session: Session, opportunity_id: str) -> None:
    if session.get(OpportunityRecord, opportunity_id) is None:
        raise HTTPException(404, "opportunity not found")


def page(
    session: Session, model: Any, opportunity_id: str, limit: int, offset: int, filters=()
) -> dict[str, Any]:
    statement = select(model).where(model.opportunity_id == opportunity_id, *filters)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(session.scalars(statement.order_by(model.id).limit(limit).offset(offset)))
    return {
        "items": [
            {c.name: getattr(item, c.name) for c in item.__table__.columns} for item in items
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("")
def summary(opportunity_id: str, session: DbSession) -> dict[str, Any]:
    require(session, opportunity_id)

    def count(model: Any) -> int:
        return (
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.opportunity_id == opportunity_id)
            )
            or 0
        )

    return {
        "opportunity_id": opportunity_id,
        "facts": count(SolicitationFactRecord),
        "requirements": count(SolicitationRequirementRecord),
        "deliverables": count(SolicitationDeliverableRecord),
        "conflicts": count(SolicitationConflictRecord),
        "schema_version": "1.0",
    }


@router.get("/snapshot")
def snapshot(opportunity_id: str, session: DbSession) -> dict[str, Any]:
    require(session, opportunity_id)
    item = session.scalar(
        select(SolicitationSnapshotRecord).where(
            SolicitationSnapshotRecord.opportunity_id == opportunity_id,
            SolicitationSnapshotRecord.is_current.is_(True),
        )
    )
    if item is None:
        raise HTTPException(404, "effective snapshot not available")
    return item.snapshot_data


@router.get("/facts")
def facts(
    opportunity_id: str,
    session: DbSession,
    canonical_field: str | None = None,
    category: str | None = None,
    effective_only: bool = False,
    confidence: str | None = None,
    source_status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    require(session, opportunity_id)
    filters = []
    for column, value in (
        (SolicitationFactRecord.canonical_field, canonical_field),
        (SolicitationFactRecord.category, category),
        (SolicitationFactRecord.confidence, confidence),
        (SolicitationFactRecord.source_status, source_status),
    ):
        if value is not None:
            filters.append(column == value)
    if effective_only:
        filters.append(SolicitationFactRecord.effective_status == "effective")
    return page(session, SolicitationFactRecord, opportunity_id, limit, offset, filters)


def simple(model):
    def endpoint(
        opportunity_id: str,
        session: DbSession,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        require(session, opportunity_id)
        return page(session, model, opportunity_id, limit, offset)

    return endpoint


router.add_api_route(
    "/dates", simple(SolicitationFactRecord), methods=["GET"], name="intelligence_dates"
)
router.add_api_route("/contacts", simple(SolicitationContactRecord), methods=["GET"])
router.add_api_route("/requirements", simple(SolicitationRequirementRecord), methods=["GET"])
router.add_api_route("/deliverables", simple(SolicitationDeliverableRecord), methods=["GET"])
router.add_api_route(
    "/evaluation-factors", simple(SolicitationEvaluationFactorRecord), methods=["GET"]
)
router.add_api_route("/codes", simple(SolicitationCodeRecord), methods=["GET"])
router.add_api_route("/changes", simple(SolicitationChangeRecord), methods=["GET"])
router.add_api_route("/conflicts", simple(SolicitationConflictRecord), methods=["GET"])


@router.get("/facts/{fact_id}/evidence")
def evidence(
    opportunity_id: str, fact_id: str, session: DbSession, limit: int = Query(100, ge=1, le=500)
):
    require(session, opportunity_id)
    fact = session.get(SolicitationFactRecord, fact_id)
    if fact is None or fact.opportunity_id != opportunity_id:
        raise HTTPException(404, "fact not found")
    items = list(
        session.scalars(
            select(SolicitationEvidenceRecord)
            .where(SolicitationEvidenceRecord.fact_id == fact_id)
            .order_by(SolicitationEvidenceRecord.id)
            .limit(limit)
        )
    )
    return {"items": [{c.name: getattr(x, c.name) for c in x.__table__.columns} for x in items]}


@router.get("/sections")
def sections(opportunity_id: str, session: DbSession, limit: int = Query(100, ge=1, le=500)):
    require(session, opportunity_id)
    rows = session.execute(
        select(SolicitationSectionRecord)
        .join(SolicitationExtractionRunRecord)
        .where(SolicitationExtractionRunRecord.opportunity_id == opportunity_id)
        .order_by(SolicitationSectionRecord.sequence)
        .limit(limit)
    )
    return {
        "items": [{c.name: getattr(x[0], c.name) for c in x[0].__table__.columns} for x in rows]
    }


@router.get("/documents")
def documents(opportunity_id: str, session: DbSession):
    require(session, opportunity_id)
    items = list(
        session.scalars(
            select(SolicitationDocumentRecord)
            .where(SolicitationDocumentRecord.opportunity_id == opportunity_id)
            .order_by(SolicitationDocumentRecord.id)
        )
    )
    return {
        "items": [
            {
                "id": x.id,
                "title": x.title,
                "document_type": x.document_type,
                "source_url": x.source_url,
                "structured_extraction_state": x.structured_extraction_state,
            }
            for x in items
        ]
    }


@router.get("/status")
def status(opportunity_id: str, session: DbSession):
    require(session, opportunity_id)
    items = list(
        session.scalars(
            select(SolicitationExtractionRunRecord)
            .where(SolicitationExtractionRunRecord.opportunity_id == opportunity_id)
            .order_by(SolicitationExtractionRunRecord.created_at)
        )
    )
    return {
        "items": [
            {
                "id": x.id,
                "state": x.state,
                "authority": x.authority,
                "field_count": x.field_count,
                "warning_count": x.warning_count,
                "completed_at": x.completed_at,
            }
            for x in items
        ]
    }


@router.get("/export.json")
def export(opportunity_id: str, session: DbSession):
    try:
        return StructuredExportService(session).build(opportunity_id)
    except LookupError as error:
        raise HTTPException(404, "opportunity not found") from error
