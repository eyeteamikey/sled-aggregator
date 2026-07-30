import io
import unittest
import zipfile

from sled_aggregator.config import Settings
from sled_aggregator.documents.extraction_types import (
    ExtractedBlock,
    ExtractionFailure,
    ExtractionResult,
)
from sled_aggregator.documents.normalization import ExtractionNormalizer, normalize_text
from sled_aggregator.documents.ocr import OcrDecisionPolicy
from sled_aggregator.documents.parsers import DocumentParserRegistry


def archive(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as handle:
        for name, content in entries.items():
            handle.writestr(name, content)
    return output.getvalue()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry, self.settings = DocumentParserRegistry(), Settings()

    def test_signatures_and_text_formats(self):
        cases = [
            (b"%PDF-1.4", "PdfDocumentParser"),
            (b"{\\rtf1 hello}", "RtfDocumentParser"),
            (b"<html><p>Hello</p></html>", "HtmlDocumentParser"),
            (b"<?xml version='1.0'?><x>Hi</x>", "XmlDocumentParser"),
            (b"a,b\n1,2", "DelimitedTextParser"),
            (b"plain", "PlainTextParser"),
        ]
        for data, name in cases:
            with self.subTest(name=name):
                self.assertEqual(self.registry.select(data).parser.parser_name, name)

    def test_ooxml_container_detection(self):
        docx = archive(
            {
                "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>'
            }
        )
        xlsx = archive({"xl/workbook.xml": "<x/>"})
        self.assertEqual(self.registry.select(docx).parser.parser_name, "DocxDocumentParser")
        self.assertEqual(self.registry.select(xlsx).parser.parser_name, "SpreadsheetDocumentParser")
        self.assertEqual(
            self.registry.select(archive({"a.txt": "hi"})).parser.parser_name, "ZipDocumentParser"
        )

    def test_extension_mismatch_recorded(self):
        selection = self.registry.select(b"%PDF-1.4", filename="wrong.txt")
        self.assertIn("extension mismatch", selection.warnings[0])

    def test_unsupported_binary(self):
        with self.assertRaises(ExtractionFailure):
            self.registry.select(b"\x00\x01\x02")

    def test_html_removes_active_content(self):
        selection = self.registry.select(
            b"<html><script>bad()</script><form>secret</form><h1>RFP</h1><p>Safe</p></html>"
        )
        result = selection.parser.parse(
            b"<html><script>bad()</script><form>secret</form><h1>RFP</h1><p>Safe</p></html>",
            settings=self.settings,
        )
        self.assertEqual([b.raw_text for b in result.blocks], ["RFP", "Safe"])

    def test_xml_entities_quarantined(self):
        parser = self.registry.select(b"<?xml version='1.0'?><x/>").parser
        with self.assertRaises(ExtractionFailure):
            parser.parse(
                b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'x'>]><x>&a;</x>",
                settings=self.settings,
            )

    def test_zip_traversal_and_nested_rejected(self):
        parser = self.registry.select(archive({"ok.txt": "ok"})).parser
        with self.assertRaises(ExtractionFailure):
            parser.parse(archive({"../bad.txt": "bad"}), settings=self.settings)
        result = parser.parse(
            archive({"nested.zip": archive({"x.txt": "x"})}), settings=self.settings
        )
        self.assertIn("nested archive skipped", result.warnings[0])

    def test_archive_provenance(self):
        parser = self.registry.select(archive({"folder/rfp.txt": "scope"})).parser
        result = parser.parse(archive({"folder/rfp.txt": "scope"}), settings=self.settings)
        self.assertEqual(result.blocks[0].archive_entry, "folder/rfp.txt")


class NormalizationAndOcrTests(unittest.TestCase):
    def test_normalization_and_offsets(self):
        self.assertEqual(normalize_text("e\u0301\x00\r\nA\t  B\n\n\nC"), "é\nA B\n\nC")
        result = ExtractionNormalizer().normalize(
            ExtractionResult(
                "p",
                "1",
                "txt",
                blocks=[ExtractedBlock(raw_text=" one "), ExtractedBlock(raw_text="two")],
            ),
            max_characters=100,
        )
        self.assertEqual(result.full_text, "one\n\ntwo")
        self.assertEqual((result.blocks[1].character_start, result.blocks[1].character_end), (5, 8))

    def test_page_specific_ocr_policy(self):
        policy = OcrDecisionPolicy(
            minimum_characters=10, minimum_words=2, maximum_replacement_ratio=0.05
        )
        self.assertEqual(
            policy.decide("meaningful native words", has_substantial_image=True).decision,
            "native_text",
        )
        self.assertEqual(policy.decide("", has_substantial_image=True).decision, "OCR_required")
        self.assertEqual(policy.decide("", has_substantial_image=False).decision, "blank")
        self.assertEqual(
            policy.decide("bad��", has_substantial_image=True).decision, "OCR_required"
        )


class SettingsTests(unittest.TestCase):
    def test_limits_validate(self):
        with self.assertRaises(ValueError):
            Settings(document_zip_max_entry_bytes=2000, document_zip_max_total_bytes=1000)
