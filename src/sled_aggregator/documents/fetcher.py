import hashlib
import os
import tempfile
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from sled_aggregator.documents.policy import DownloadPolicy
from sled_aggregator.documents.types import (
    ContentMetadata,
    DownloadFailure,
    DownloadResult,
    FailureKind,
)
from sled_aggregator.documents.validation import classify_html, detect_media_type, safe_filename

_REDIRECTS = {301, 302, 303, 307, 308}
_TRANSIENT = {408, 425, 429, 500, 502, 503, 504}


class PublicDocumentFetcher:
    """Validated redirect loop and bounded streaming GET with incremental hashing."""

    def __init__(
        self,
        policy: DownloadPolicy,
        *,
        temp_root: Path,
        max_bytes: int,
        chunk_bytes: int = 65536,
        max_redirects: int = 5,
        html_probe_bytes: int = 32768,
        timeout: httpx.Timeout | None = None,
        user_agent: str = "TrustEST-SLED-DocumentDownloader/0.1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.policy, self.temp_root, self.max_bytes = policy, temp_root, max_bytes
        self.chunk_bytes, self.max_redirects, self.html_probe_bytes = (
            chunk_bytes,
            max_redirects,
            html_probe_bytes,
        )
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout or 30,
            limits=httpx.Limits(max_connections=10),
            headers={"User-Agent": user_agent},
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "PublicDocumentFetcher":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        allow_html: bool = False,
    ) -> DownloadResult:
        original_host = self.policy.validate(url)
        current, history, seen = url, [], {url}
        headers = {
            "Accept": "application/pdf,application/zip,text/plain,text/csv,text/html;q=0.5,*/*;q=0.1"
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        while True:
            try:
                request = self._client.build_request("GET", current, headers=headers)
                response = await self._client.send(request, stream=True)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise DownloadFailure(
                    FailureKind.TRANSIENT, "public document request failed"
                ) from exc
            if response.status_code in _REDIRECTS:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise DownloadFailure(FailureKind.UNSUPPORTED, "redirect omitted Location")
                destination = urljoin(current, location)
                if destination in seen:
                    raise DownloadFailure(FailureKind.UNSAFE_URL, "redirect loop")
                if len(history) >= self.max_redirects:
                    raise DownloadFailure(FailureKind.UNSAFE_URL, "redirect limit exceeded")
                self.policy.validate(
                    destination,
                    original_host=original_host,
                    previous_scheme=urlsplit(current).scheme,
                )
                history.append(destination[:2048])
                seen.add(destination)
                current = destination
                continue
            try:
                return await self._consume(response, current, tuple(history), allow_html)
            finally:
                await response.aclose()

    async def _consume(
        self, response: httpx.Response, final_url: str, redirects: tuple[str, ...], allow_html: bool
    ) -> DownloadResult:
        status = response.status_code
        if status == 304:
            return DownloadResult(final_url, None, None, status, redirects, unchanged=True)
        if status in _TRANSIENT:
            raise DownloadFailure(
                FailureKind.TRANSIENT,
                f"transient HTTP {status}",
                status_code=status,
                retry_after=_retry_after(response.headers.get("retry-after")),
            )
        terminal = {
            401: FailureKind.LOGIN_REQUIRED,
            404: FailureKind.NOT_FOUND,
            410: FailureKind.NOT_FOUND,
            413: FailureKind.OVERSIZED,
            415: FailureKind.UNSUPPORTED,
            451: FailureKind.RESTRICTED,
        }
        if status in terminal:
            raise DownloadFailure(terminal[status], f"terminal HTTP {status}", status_code=status)
        if status not in {200} and status != 403:
            raise DownloadFailure(
                FailureKind.UNSUPPORTED, f"unsupported HTTP {status}", status_code=status
            )
        declared_length = response.headers.get("content-length")
        if declared_length and declared_length.isdigit() and int(declared_length) > self.max_bytes:
            raise DownloadFailure(
                FailureKind.OVERSIZED, "declared document size exceeds limit", status_code=status
            )
        self.temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix="download-", dir=self.temp_root)
        path = Path(name)
        digest = hashlib.sha256()
        count = 0
        prefix = bytearray()
        try:
            with os.fdopen(fd, "wb") as handle:
                async for chunk in response.aiter_bytes(self.chunk_bytes):
                    count += len(chunk)
                    if count > self.max_bytes:
                        raise DownloadFailure(
                            FailureKind.OVERSIZED,
                            "streamed document size exceeds limit",
                            status_code=status,
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                    if len(prefix) < self.html_probe_bytes:
                        prefix.extend(chunk[: self.html_probe_bytes - len(prefix)])
                handle.flush()
                os.fsync(handle.fileno())
            if not count:
                raise DownloadFailure(
                    FailureKind.UNSUPPORTED, "empty document body", status_code=status
                )
            filename = safe_filename(response.headers.get("content-disposition"))
            detected = detect_media_type(
                bytes(prefix), filename=filename or urlsplit(final_url).path
            )
            html_kind = classify_html(bytes(prefix)) if detected == "text/html" else None
            if status == 403:
                raise DownloadFailure(
                    html_kind or FailureKind.RESTRICTED, "HTTP 403 access page", status_code=status
                )
            if html_kind:
                raise DownloadFailure(html_kind, "HTML access or error page", status_code=status)
            if detected == "text/html" and not allow_html:
                raise DownloadFailure(
                    FailureKind.QUARANTINED, "unexpected HTML document", status_code=status
                )
            media = response.headers.get("content-type", "").split(";", 1)[0].strip() or None
            metadata = ContentMetadata(
                digest.hexdigest(),
                count,
                media,
                detected,
                filename,
                response.headers.get("etag"),
                response.headers.get("last-modified"),
            )
            return DownloadResult(final_url[:2048], path, metadata, status, redirects)
        except BaseException:
            path.unlink(missing_ok=True)
            raise


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        from datetime import UTC, datetime

        return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None
