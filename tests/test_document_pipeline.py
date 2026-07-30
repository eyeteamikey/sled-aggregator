import unittest
from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from sled_aggregator.config import Settings
from sled_aggregator.domain.enums import RetrievalState
from sled_aggregator.services.document_manifest import DocumentQueueService
from sled_aggregator.services.document_state import InvalidRetrievalTransition, transition
from sled_aggregator.services.document_urls import UnsafeDocumentUrl, canonicalize_document_url


class DocumentUrlTests(unittest.TestCase):
    def test_normalizes_identity_without_changing_document_ids(self):
        self.assertEqual(canonicalize_document_url("HTTPS://Example.COM:443/a/../docs/rfp.pdf?sid=x&documentId=42#top"), "https://example.com/docs/rfp.pdf?documentId=42")

    def test_sorts_stable_parameters(self):
        self.assertEqual(canonicalize_document_url("https://example.com/d?z=2&a=1"), "https://example.com/d?a=1&z=2")

    def test_rejects_unsafe_urls(self):
        for url in ("javascript:alert(1)", "data:text/plain,x", "file:///tmp/x", "http://u:p@example.com/x", "http://localhost/x", "http://127.0.0.1/x", "http://10.0.0.1/x", "http://169.254.169.254/latest"):
            with self.subTest(url=url), self.assertRaises(UnsafeDocumentUrl):
                canonicalize_document_url(url)


class RetrievalStateTests(unittest.TestCase):
    def test_happy_path(self):
        state = RetrievalState.DISCOVERED
        for target in (RetrievalState.ELIGIBLE, RetrievalState.QUEUED, RetrievalState.LEASED, RetrievalState.DOWNLOADING, RetrievalState.DOWNLOADED, RetrievalState.SUPERSEDED):
            state = transition(state, target)
        self.assertEqual(state, RetrievalState.SUPERSEDED)

    def test_invalid_transition_has_domain_error(self):
        with self.assertRaises(InvalidRetrievalTransition):
            transition(RetrievalState.RESTRICTED, RetrievalState.DOWNLOADING)

    def test_nonterminal_can_be_quarantined(self):
        self.assertEqual(transition(RetrievalState.QUEUED, RetrievalState.QUARANTINED), RetrievalState.QUARANTINED)

    def test_downloaded_only_supersedes(self):
        with self.assertRaises(InvalidRetrievalTransition):
            transition(RetrievalState.DOWNLOADED, RetrievalState.QUEUED)


class QueueSqlTests(unittest.TestCase):
    def test_postgresql_claim_uses_skip_locked_and_stable_order(self):
        statement = DocumentQueueService.claim_statement(datetime(2026, 7, 30, tzinfo=UTC), 5)
        sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertIn("priority DESC", sql)
        self.assertIn("next_attempt_at", sql)


class DocumentSettingsTests(unittest.TestCase):
    def test_defaults_are_bounded(self):
        settings = Settings()
        self.assertLessEqual(settings.document_queue_batch_size, 1000)
        self.assertGreater(settings.document_queue_lease_seconds, 0)

    def test_rejects_invalid_retry_bounds(self):
        with self.assertRaises(ValueError):
            Settings(document_queue_retry_base_seconds=20, document_queue_retry_max_seconds=10)
