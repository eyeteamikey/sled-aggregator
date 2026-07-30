from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sled_aggregator.config import Settings
from sled_aggregator.db.models import (
    DocumentArtifactRecord,
    DocumentExtractionRecord,
    DocumentTableRecord,
    DocumentTextBlockRecord,
    SolicitationDocumentRecord,
)
from sled_aggregator.documents.normalization import ExtractionNormalizer
from sled_aggregator.documents.parsers import DocumentParserRegistry
from sled_aggregator.documents.storage import DocumentStorage


class DocumentExtractionService:
    def __init__(
        self,
        session: Session,
        storage: DocumentStorage,
        settings: Settings,
        registry: DocumentParserRegistry | None = None,
    ) -> None:
        self.session, self.storage, self.settings = session, storage, settings
        self.registry = registry or DocumentParserRegistry()

    def extract(
        self, artifact: DocumentArtifactRecord, *, now: datetime | None = None
    ) -> DocumentExtractionRecord:
        now = now or datetime.now(UTC)
        document = self.session.get(SolicitationDocumentRecord, artifact.document_id)
        if document is None:
            raise ValueError("artifact document is missing")
        if artifact.content_length > self.settings.document_extraction_max_artifact_bytes:
            raise ValueError("artifact exceeds extraction limit")
        with self.storage.open(artifact.storage_key) as handle:
            data = handle.read(self.settings.document_extraction_max_artifact_bytes + 1)
        selection = self.registry.select(
            data,
            detected_media_type=artifact.detected_media_type,
            declared_media_type=artifact.declared_media_type,
            filename=artifact.displayed_filename or document.displayed_filename,
        )
        existing = self.session.scalar(
            select(DocumentExtractionRecord).where(
                DocumentExtractionRecord.artifact_id == artifact.id,
                DocumentExtractionRecord.content_sha256 == artifact.content_sha256,
                DocumentExtractionRecord.parser_name == selection.parser.parser_name,
                DocumentExtractionRecord.parser_version == selection.parser.parser_version,
                DocumentExtractionRecord.extraction_state.in_(
                    ("completed", "completed_with_warnings")
                ),
            )
        )
        if existing:
            return existing
        result = selection.parser.parse(data, settings=self.settings)
        result.warnings[:0] = selection.warnings
        result = ExtractionNormalizer().normalize(
            result, max_characters=self.settings.document_extraction_max_characters
        )
        if result.warnings and result.state.value == "completed":
            result.state = result.state.COMPLETED_WITH_WARNINGS
        self.session.execute(
            update(DocumentExtractionRecord)
            .where(
                DocumentExtractionRecord.document_id == document.id,
                DocumentExtractionRecord.is_current.is_(True),
            )
            .values(is_current=False)
        )
        record = DocumentExtractionRecord(
            id=str(uuid4()),
            document_id=document.id,
            artifact_id=artifact.id,
            opportunity_id=document.opportunity_id,
            parser_name=result.parser_name,
            parser_version=result.parser_version,
            detected_format=result.detected_format,
            extraction_state=result.state.value,
            ocr_state=result.ocr_state.value,
            language=self.settings.document_ocr_language,
            native_text_character_count=sum(
                len(b.normalized_text) for b in result.blocks if b.extraction_method == "native"
            ),
            ocr_text_character_count=sum(
                len(b.normalized_text) for b in result.blocks if b.extraction_method == "ocr"
            ),
            total_character_count=len(result.full_text),
            unit_count=len({(b.page_number, b.sheet_name, b.archive_entry) for b in result.blocks}),
            table_count=len(result.tables),
            warning_count=len(result.warnings),
            content_sha256=artifact.content_sha256,
            is_current=True,
            extraction_metadata={
                **result.metadata,
                "warnings": result.warnings[:100],
                "source_url": document.source_url,
            },
            started_at=now,
            completed_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        for block in result.blocks[: self.settings.document_extraction_max_blocks]:
            self.session.add(
                DocumentTextBlockRecord(
                    id=str(uuid4()),
                    extraction_id=record.id,
                    sequence=block.sequence,
                    page_number=block.page_number,
                    sheet_name=block.sheet_name,
                    archive_entry=block.archive_entry,
                    paragraph_index=block.paragraph_index,
                    table_index=block.table_index,
                    row_start=block.row_start,
                    row_end=block.row_end,
                    column_start=block.column_start,
                    column_end=block.column_end,
                    block_type=block.block_type,
                    heading_level=block.heading_level,
                    raw_text=block.raw_text,
                    normalized_text=block.normalized_text,
                    character_start=block.character_start,
                    character_end=block.character_end,
                    extraction_method=block.extraction_method,
                    ocr_confidence=int(block.ocr_confidence * 100)
                    if block.ocr_confidence is not None
                    else None,
                    source_location=block.source_location,
                    created_at=now,
                )
            )
        for table in result.tables[: self.settings.document_extraction_max_tables]:
            self.session.add(
                DocumentTableRecord(
                    id=str(uuid4()),
                    extraction_id=record.id,
                    sequence=table.sequence,
                    page_number=table.page_number,
                    sheet_name=table.sheet_name,
                    archive_entry=table.archive_entry,
                    row_count=len(table.rows),
                    column_count=max(map(len, table.rows), default=0),
                    structured_data=table.rows,
                    flattened_text="\n".join("\t".join(row) for row in table.rows),
                    created_at=now,
                )
            )
        document.extracted_text_available = bool(result.full_text)
        document.extraction_state = result.state.value
        document.ocr_state = result.ocr_state.value
        self.session.flush()
        return record
