from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator

from sled_aggregator.domain.enums import (
    AccessState,
    DocumentEligibility,
    DocumentRole,
    OpportunityStatus,
)


class SourceRef(BaseModel):
    platform_family: str
    jurisdiction: str
    source_id: str
    opportunity_url: HttpUrl


class RawOpportunity(BaseModel):
    source: SourceRef
    title: str
    agency: str
    description: str | None = None
    solicitation_number: str | None = None
    status: OpportunityStatus = OpportunityStatus.UNKNOWN
    posted_at: datetime | None = None
    due_at: datetime | None = None
    categories: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "agency")
    @classmethod
    def require_meaningful_text(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned


class CanonicalOpportunity(BaseModel):
    canonical_key: str
    source: SourceRef
    title: str
    agency: str
    description: str | None = None
    solicitation_number: str | None = None
    status: OpportunityStatus
    posted_at: datetime | None = None
    due_at: datetime | None = None
    categories: list[str] = Field(default_factory=list)
    normalized_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentCandidate(BaseModel):
    opportunity_id: str
    source_document_url: HttpUrl
    source_opportunity_url: HttpUrl
    filename: str
    label: str | None = None
    mime_type: str | None = None
    access_state: AccessState = AccessState.PUBLIC


class DocumentClassification(BaseModel):
    eligibility: DocumentEligibility
    role: DocumentRole
    score: float = Field(ge=0.0, le=1.0)
    rationale: list[str] = Field(default_factory=list)

