from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class FailureKind(StrEnum):
    TRANSIENT = "transient"
    LOGIN_REQUIRED = "login_required"
    REGISTRATION_REQUIRED = "registration_required"
    CAPTCHA = "captcha"
    RESTRICTED = "restricted"
    NOT_FOUND = "not_found"
    OVERSIZED = "oversized"
    UNSAFE_URL = "unsafe_url"
    UNSUPPORTED = "unsupported"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class ContentMetadata:
    sha256: str
    length: int
    declared_media_type: str | None
    detected_media_type: str
    filename: str | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    final_url: str
    temporary_path: Path | None
    metadata: ContentMetadata | None
    status_code: int
    redirects: tuple[str, ...] = field(default_factory=tuple)
    unchanged: bool = False


class DownloadFailure(RuntimeError):
    def __init__(
        self,
        kind: FailureKind,
        summary: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(summary[:512])
        self.kind, self.status_code, self.retry_after = kind, status_code, retry_after
