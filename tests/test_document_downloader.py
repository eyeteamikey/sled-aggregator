import hashlib
import tempfile
import unittest
from pathlib import Path

import httpx

from sled_aggregator.config import Settings
from sled_aggregator.documents.fetcher import PublicDocumentFetcher
from sled_aggregator.documents.policy import DownloadPolicy
from sled_aggregator.documents.storage import LocalDocumentStorage
from sled_aggregator.documents.types import DownloadFailure, FailureKind
from sled_aggregator.documents.validation import classify_html, detect_media_type, safe_filename


class ValidationTests(unittest.TestCase):
    def test_common_signatures(self):
        cases = {
            b"%PDF-1.7": "application/pdf",
            b"PK\x03\x04x": "application/zip",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": "application/x-ole-storage",
            b"{\\rtf1": "application/rtf",
            b"<?xml version='1.0'?>": "application/xml",
            b"\x89PNG\r\n\x1a\n": "image/png",
            b"plain text": "text/plain",
        }
        for content, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_media_type(content), expected)

    def test_html_access_classification(self):
        for body, kind in (
            (b"<html>supplier login</html>", FailureKind.LOGIN_REQUIRED),
            (b"<html>registration required</html>", FailureKind.REGISTRATION_REQUIRED),
            (b"<html>hCaptcha</html>", FailureKind.CAPTCHA),
            (b"<html>service unavailable</html>", FailureKind.TRANSIENT),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(classify_html(body), kind)

    def test_filename_star_and_traversal(self):
        self.assertEqual(
            safe_filename("attachment; filename*=UTF-8''report%20one.pdf"), "report one.pdf"
        )
        self.assertEqual(safe_filename('attachment; filename="../../bad.pdf"'), "_.._bad.pdf")


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = DownloadPolicy(
            allowed_hosts=("example.gov", "cdn.example.gov"),
            resolver=lambda _host: ["93.184.216.34"],
        )

    def test_allows_public_allowlisted_urls(self):
        self.assertEqual(self.policy.validate("https://docs.example.gov/a.pdf"), "docs.example.gov")

    def test_blocks_network_bypasses(self):
        urls = (
            "http://localhost/x",
            "http://127.0.0.1/x",
            "http://[::1]/x",
            "http://[::ffff:127.0.0.1]/x",
            "http://169.254.169.254/x",
            "ftp://example.gov/x",
            "http://user:pass@example.gov/x",
            "http://2130706433/x",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(DownloadFailure):
                self.policy.validate(url)

    def test_blocks_unapproved_redirect_and_downgrade(self):
        with self.assertRaises(DownloadFailure):
            self.policy.validate("https://evil.example/a", original_host="example.gov")
        with self.assertRaises(DownloadFailure):
            self.policy.validate("http://example.gov/a", previous_scheme="https")


class FetcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.policy = DownloadPolicy(
            allowed_hosts=("example.gov",), resolver=lambda _: ["93.184.216.34"]
        )

    async def asyncTearDown(self):
        self.temp.cleanup()

    def fetcher(self, handler, max_bytes=1024):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return PublicDocumentFetcher(
            self.policy,
            temp_root=Path(self.temp.name),
            max_bytes=max_bytes,
            chunk_bytes=4,
            client=client,
        ), client

    async def test_streams_hashes_and_preserves_injected_client(self):
        body = b"%PDF-1.7\ncontent"
        fetcher, client = self.fetcher(
            lambda request: httpx.Response(
                200, headers={"content-type": "application/pdf", "etag": '"v1"'}, content=body
            )
        )
        result = await fetcher.fetch("https://example.gov/rfp.pdf")
        self.assertEqual(result.metadata.sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(result.temporary_path.read_bytes(), body)
        await fetcher.aclose()
        self.assertFalse(client.is_closed)
        result.temporary_path.unlink()
        await client.aclose()

    async def test_conditional_304(self):
        def handler(request):
            self.assertEqual(request.headers["if-none-match"], '"old"')
            return httpx.Response(304)

        fetcher, client = self.fetcher(handler)
        result = await fetcher.fetch("https://example.gov/rfp.pdf", etag='"old"')
        self.assertTrue(result.unchanged)
        self.assertIsNone(result.temporary_path)
        await client.aclose()

    async def test_redirect_and_relative_location(self):
        def handler(request):
            return (
                httpx.Response(302, headers={"location": "/final.pdf"})
                if request.url.path != "/final.pdf"
                else httpx.Response(200, content=b"%PDF-x")
            )

        fetcher, client = self.fetcher(handler)
        result = await fetcher.fetch("https://example.gov/start")
        self.assertEqual(result.final_url, "https://example.gov/final.pdf")
        result.temporary_path.unlink()
        await client.aclose()

    async def test_oversize_cleans_partial(self):
        fetcher, client = self.fetcher(
            lambda _: httpx.Response(200, content=b"%PDF-123456"), max_bytes=8
        )
        with self.assertRaises(DownloadFailure) as error:
            await fetcher.fetch("https://example.gov/x.pdf")
        self.assertEqual(error.exception.kind, FailureKind.OVERSIZED)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        await client.aclose()

    async def test_login_and_captcha_not_stored(self):
        for body, kind in (
            (b"<html>supplier login</html>", FailureKind.LOGIN_REQUIRED),
            (b"<html>recaptcha</html>", FailureKind.CAPTCHA),
        ):
            fetcher, client = self.fetcher(lambda _, body=body: httpx.Response(200, content=body))
            with self.subTest(kind=kind), self.assertRaises(DownloadFailure) as error:
                await fetcher.fetch("https://example.gov/x.pdf")
            self.assertEqual(error.exception.kind, kind)
            await client.aclose()


class StorageTests(unittest.TestCase):
    def test_atomic_commit_reuse_and_traversal(self):
        with tempfile.TemporaryDirectory() as root:
            storage = LocalDocumentStorage(Path(root))
            content = b"artifact"
            digest = hashlib.sha256(content).hexdigest()
            key = storage.generate_key("va", "opp", "doc", digest)
            temporary = Path(root) / "temporary"
            temporary.write_bytes(content)
            storage.commit(temporary, key, size=len(content), sha256=digest)
            with storage.open(key) as handle:
                self.assertEqual(handle.read(), content)
            duplicate = Path(root) / "duplicate"
            duplicate.write_bytes(content)
            storage.commit(duplicate, key, size=len(content), sha256=digest)
            self.assertFalse(duplicate.exists())
            with self.assertRaises(ValueError):
                storage.exists("../escape")


class DownloaderSettingsTests(unittest.TestCase):
    def test_safe_defaults_and_validation(self):
        settings = Settings()
        self.assertEqual(settings.document_download_max_bytes, 100 * 1024 * 1024)
        self.assertEqual(settings.document_download_concurrency, 1)
        with self.assertRaises(ValueError):
            Settings(document_download_allowed_ports=(0,))
        with self.assertRaises(ValueError):
            Settings(document_download_max_bytes=1024, document_download_chunk_bytes=2048)
