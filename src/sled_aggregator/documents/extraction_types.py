from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExtractionState(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    UNSUPPORTED = "unsupported"
    MALFORMED = "malformed"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class OcrState(StrEnum):
    NOT_NEEDED = "not_needed"
    PARTIALLY_USED = "partially_used"
    FULLY_USED = "fully_used"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(slots=True)
class ExtractedBlock:
    sequence: int = 0
    raw_text: str = ""
    normalized_text: str = ""
    block_type: str = "paragraph"
    page_number: int | None = None
    sheet_name: str | None = None
    archive_entry: str | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_start: int | None = None
    row_end: int | None = None
    column_start: int | None = None
    column_end: int | None = None
    heading_level: int | None = None
    character_start: int = 0
    character_end: int = 0
    extraction_method: str = "native"
    ocr_confidence: float | None = None
    source_location: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedTable:
    sequence: int
    rows: list[list[str]]
    page_number: int | None = None
    sheet_name: str | None = None
    archive_entry: str | None = None


@dataclass(slots=True)
class ExtractionResult:
    parser_name: str
    parser_version: str
    detected_format: str
    blocks: list[ExtractedBlock] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    state: ExtractionState = ExtractionState.COMPLETED
    ocr_state: OcrState = OcrState.NOT_NEEDED
    metadata: dict[str, Any] = field(default_factory=dict)
    full_text: str = ""


class ExtractionFailure(RuntimeError):
    def __init__(self, state: ExtractionState, summary: str) -> None:
        super().__init__(summary[:512])
        self.state = state
