from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
