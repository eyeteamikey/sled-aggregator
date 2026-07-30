from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "TrustEST SLED Aggregator"
    app_env: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://sled:sled@localhost:5432/sled"
    connector_request_timeout_seconds: int = 30
    connector_user_agent: str = "TrustEST-SLED-Aggregator/0.1"
    document_max_download_bytes: int = 50 * 1024 * 1024
    archive_max_expanded_bytes: int = 250 * 1024 * 1024
    archive_max_files: int = 500
    archive_max_depth: int = 3
    document_manifest_enabled: bool = True
    document_auto_enqueue_enabled: bool = True
    document_queue_max_attempts: int = Field(default=5, ge=1, le=100)
    document_queue_default_priority: int = Field(default=50, ge=0, le=100)
    document_queue_lease_seconds: int = Field(default=300, ge=1, le=86400)
    document_queue_retry_base_seconds: int = Field(default=60, ge=0, le=86400)
    document_queue_retry_max_seconds: int = Field(default=3600, ge=0, le=604800)
    document_queue_retry_jitter: float = Field(default=0.1, ge=0, le=1)
    document_queue_batch_size: int = Field(default=10, ge=1, le=1000)
    document_max_source_metadata_bytes: int = Field(default=65536, ge=1024, le=1048576)
    document_downloader_enabled: bool = False
    document_storage_backend: str = "local"
    document_storage_root: Path = Path("/tmp/sled-aggregator/documents")
    document_download_temp_root: Path = Path("/tmp/sled-aggregator/tmp")
    document_download_max_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    document_download_chunk_bytes: int = Field(default=64 * 1024, ge=1024, le=4 * 1024 * 1024)
    document_download_connect_timeout: float = Field(default=10, gt=0)
    document_download_read_timeout: float = Field(default=60, gt=0)
    document_download_write_timeout: float = Field(default=10, gt=0)
    document_download_pool_timeout: float = Field(default=10, gt=0)
    document_download_max_redirects: int = Field(default=5, ge=0, le=20)
    document_download_max_attempts: int = Field(default=5, ge=1, le=20)
    document_download_retry_base_seconds: int = Field(default=60, ge=0)
    document_download_retry_max_seconds: int = Field(default=3600, ge=0)
    document_download_retry_jitter: float = Field(default=0.1, ge=0, le=1)
    document_download_batch_size: int = Field(default=10, ge=1, le=100)
    document_download_concurrency: int = Field(default=1, ge=1, le=16)
    document_download_use_head: bool = False
    document_download_user_agent: str = "TrustEST-SLED-DocumentDownloader/0.1"
    document_download_allowed_ports: tuple[int, ...] = (80, 443)
    document_download_allowed_hosts: tuple[str, ...] = ()
    document_download_html_probe_bytes: int = Field(default=32768, ge=1024, le=262144)
    document_download_error_probe_bytes: int = Field(default=8192, ge=512, le=65536)
    document_extraction_enabled: bool = True
    document_extraction_auto_enqueue: bool = True
    document_extraction_batch_size: int = Field(default=10, ge=1, le=100)
    document_extraction_concurrency: int = Field(default=1, ge=1, le=16)
    document_extraction_max_attempts: int = Field(default=3, ge=1, le=20)
    document_extraction_lease_seconds: int = Field(default=600, ge=30, le=86400)
    document_extraction_max_artifact_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    document_extraction_max_characters: int = Field(default=5_000_000, ge=1000)
    document_extraction_max_blocks: int = Field(default=10_000, ge=1)
    document_extraction_max_tables: int = Field(default=1_000, ge=1)
    document_pdf_max_pages: int = Field(default=500, ge=1)
    document_pdf_native_text_min_characters: int = Field(default=40, ge=0)
    document_pdf_native_text_min_words: int = Field(default=5, ge=0)
    document_pdf_max_replacement_ratio: float = Field(default=0.05, ge=0, le=1)
    document_ocr_enabled: bool = False
    document_ocr_provider: str = "tesseract"
    document_ocr_language: str = "eng"
    document_ocr_dpi: int = Field(default=200, ge=72, le=600)
    document_ocr_timeout_seconds: int = Field(default=60, ge=1, le=600)
    document_ocr_max_pages: int = Field(default=25, ge=0, le=500)
    document_ocr_max_pixels: int = Field(default=25_000_000, ge=1_000_000)
    document_zip_enabled: bool = True
    document_zip_max_entries: int = Field(default=100, ge=1, le=5000)
    document_zip_max_entry_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    document_zip_max_total_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    document_zip_max_compression_ratio: float = Field(default=100, ge=1, le=1000)
    document_zip_max_nesting_depth: int = Field(default=0, ge=0, le=3)
    document_spreadsheet_max_sheets: int = Field(default=50, ge=1)
    document_spreadsheet_max_rows: int = Field(default=100_000, ge=1)
    document_spreadsheet_max_columns: int = Field(default=1_000, ge=1)
    document_spreadsheet_max_cells: int = Field(default=1_000_000, ge=1)
    solicitation_intelligence_enabled: bool = True
    solicitation_intelligence_auto_enqueue: bool = True
    solicitation_intelligence_batch_size: int = Field(default=10, ge=1, le=100)
    solicitation_intelligence_concurrency: int = Field(default=1, ge=1, le=16)
    solicitation_intelligence_max_attempts: int = Field(default=3, ge=1, le=20)
    solicitation_intelligence_lease_seconds: int = Field(default=600, ge=30, le=86400)
    solicitation_intelligence_retry_base_seconds: int = Field(default=60, ge=0, le=86400)
    solicitation_intelligence_retry_max_seconds: int = Field(default=3600, ge=0, le=604800)
    solicitation_intelligence_max_fields: int = Field(default=1000, ge=1, le=10000)
    solicitation_intelligence_max_requirements: int = Field(default=2000, ge=1, le=10000)
    solicitation_intelligence_max_deliverables: int = Field(default=500, ge=1, le=5000)
    solicitation_intelligence_max_evaluation_factors: int = Field(default=250, ge=1, le=2000)
    solicitation_intelligence_max_contacts: int = Field(default=100, ge=1, le=1000)
    solicitation_intelligence_max_evidence_quote_chars: int = Field(default=500, ge=32, le=4000)
    solicitation_intelligence_context_window_chars: int = Field(default=800, ge=32, le=8000)
    solicitation_intelligence_min_confidence: int = Field(default=40, ge=0, le=100)
    solicitation_intelligence_reconcile_qa: bool = True
    solicitation_intelligence_export_enabled: bool = True

    @model_validator(mode="after")
    def validate_document_retry_bounds(self) -> "Settings":
        if self.document_queue_retry_max_seconds < self.document_queue_retry_base_seconds:
            raise ValueError("document retry maximum must be at least the base")
        if self.document_download_max_bytes < self.document_download_chunk_bytes:
            raise ValueError("document maximum bytes must be at least the chunk size")
        if self.document_storage_backend != "local":
            raise ValueError("only the local document storage backend is supported")
        if any(port < 1 or port > 65535 for port in self.document_download_allowed_ports):
            raise ValueError("document download ports must be between 1 and 65535")
        if self.document_download_retry_max_seconds < self.document_download_retry_base_seconds:
            raise ValueError("document download retry maximum must be at least the base")
        if self.document_zip_max_entry_bytes > self.document_zip_max_total_bytes:
            raise ValueError("ZIP entry limit cannot exceed total limit")
        if self.solicitation_intelligence_retry_max_seconds < self.solicitation_intelligence_retry_base_seconds:
            raise ValueError("intelligence retry maximum must be at least the base")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
