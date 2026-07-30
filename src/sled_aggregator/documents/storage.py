import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


@dataclass(frozen=True, slots=True)
class StorageStat:
    key: str
    size: int


class DocumentStorage(Protocol):
    def generate_key(
        self, jurisdiction: str, opportunity_id: str, document_id: str, sha256: str
    ) -> str: ...
    def commit(self, temporary_path: Path, key: str, *, size: int, sha256: str) -> StorageStat: ...
    def exists(self, key: str) -> bool: ...
    def open(self, key: str) -> BinaryIO: ...
    def stat(self, key: str) -> StorageStat: ...
    def delete(self, key: str) -> None: ...


class LocalDocumentStorage:
    """Atomic local adapter; a deterministic key reconciles DB commit failures."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def _component(value: str) -> str:
        safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
        if not safe or safe in {".", ".."}:
            raise ValueError("unsafe storage key component")
        return safe[:100]

    def generate_key(
        self, jurisdiction: str, opportunity_id: str, document_id: str, sha256: str
    ) -> str:
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError("invalid SHA-256")
        parts = map(self._component, (jurisdiction, opportunity_id, document_id))
        return "/".join(("documents", *parts, sha256))

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in Path(key).parts:
            raise ValueError("unsafe storage key")
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("storage path escaped root")
        return path

    def commit(self, temporary_path: Path, key: str, *, size: int, sha256: str) -> StorageStat:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            self._verify(destination, size, sha256)
            temporary_path.unlink(missing_ok=True)
            return StorageStat(key, size)
        staging = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            shutil.copyfile(temporary_path, staging)
            os.chmod(staging, 0o600)
            with staging.open("rb+") as handle:
                os.fsync(handle.fileno())
            self._verify(staging, size, sha256)
            os.replace(staging, destination)
        finally:
            staging.unlink(missing_ok=True)
            temporary_path.unlink(missing_ok=True)
        return StorageStat(key, size)

    @staticmethod
    def _verify(path: Path, size: int, expected: str) -> None:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        if path.stat().st_size != size or digest.hexdigest() != expected:
            raise OSError("stored artifact integrity check failed")

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def stat(self, key: str) -> StorageStat:
        return StorageStat(key, self._path(key).stat().st_size)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
