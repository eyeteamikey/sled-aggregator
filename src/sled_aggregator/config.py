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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
