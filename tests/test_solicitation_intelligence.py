import json
import unittest
from dataclasses import dataclass
from datetime import UTC

from sled_aggregator.config import Settings
from sled_aggregator.documents.intelligence import (
    DeterministicSolicitationExtractor,
    DocumentAuthorityResolver,
    ReconciliationPolicy,
    SectionClassifier,
    SolicitationReconciler,
)
from sled_aggregator.documents.intelligence_types import (
    DocumentAuthority,
    StructuredExtractionResult,
    StructuredFact,
)


@dataclass
class Obj:
    id: str = "id"
    normalized_text: str = ""
    raw_text: str = ""
    sequence: int = 0
    page_number: int | None = 1
    sheet_name: str | None = None
    archive_entry: str | None = None
    table_index: int | None = None
    row_start: int | None = None
    column_start: int | None = None
    character_start: int = 0
    character_end: int = 10
    extraction_method: str = "native"
    ocr_confidence: int | None = None
    heading_level: int | None = None
    block_type: str = "paragraph"


def document(title="Request for Proposals", **kwargs):
    values = dict(
        id="doc",
        document_type="solicitation",
        document_category=None,
        title=title,
        displayed_filename="rfp.pdf",
        relationship_type="related",
        amendment_number=None,
        addendum_number=None,
        supersedes_document_id=None,
        source_url="https://public.example/rfp.pdf",
    )
    values.update(kwargs)
    return type("Document", (), values)()


def extract(blocks, doc=None):
    return DeterministicSolicitationExtractor(80, 120).extract(
        opportunity=Obj("opp"),
        document=doc or document(),
        artifact=Obj("artifact"),
        extraction=type("Extraction", (), {"id": "extraction", "warning_count": 0})(),
        blocks=blocks,
    )


class IntelligenceTests(unittest.TestCase):
    def test_section_numbered_scope(self):
        sections = SectionClassifier().classify(
            [Obj(normalized_text="2.1 Scope", raw_text="2.1 Scope")]
        )
        self.assertEqual(sections[0]["normalized_type"], "scope")

    def test_uppercase_body_not_heading(self):
        self.assertEqual(
            SectionClassifier().classify([Obj(normalized_text="SCOPE", raw_text="SCOPE")]), []
        )

    def test_identity_and_deadlines_have_evidence(self):
        result = extract(
            [
                Obj(
                    normalized_text="Solicitation Number: RFP-123",
                    raw_text="Solicitation Number: RFP-123",
                ),
                Obj(
                    normalized_text="Proposals due: August 30, 2026 2:00 PM CT",
                    raw_text="Proposals due: August 30, 2026 2:00 PM CT",
                ),
            ]
        )
        self.assertEqual(
            {x.canonical_field for x in result.facts}, {"solicitation_number", "proposal_deadline"}
        )
        self.assertTrue(all(x.evidence for x in result.facts))

    def test_requirement_strengths(self):
        cases = [
            ("Vendor must respond.", "mandatory"),
            ("Vendor must not call.", "prohibited"),
            ("If selected, vendor shall attend.", "conditional"),
            ("Vendor should explain.", "recommended"),
            ("Vendor may attach details.", "optional"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    extract([Obj(normalized_text=text, raw_text=text)]).requirements[0]["strength"],
                    expected,
                )

    def test_narrative_not_requirement(self):
        self.assertEqual(
            extract(
                [
                    Obj(
                        normalized_text="The agency describes its network.",
                        raw_text="The agency describes its network.",
                    )
                ]
            ).requirements,
            [],
        )

    def test_codes_deduplicate(self):
        result = extract(
            [
                Obj(
                    normalized_text="NAICS: 541512 NAICS: 541512",
                    raw_text="NAICS: 541512 NAICS: 541512",
                )
            ]
        )
        self.assertEqual(len(result.codes), 1)

    def test_contact_and_phone_extension(self):
        text = "Procurement Contact: buyer@example.gov (512) 555-1212 ext. 9"
        item = extract([Obj(normalized_text=text, raw_text=text)]).contacts[0]
        self.assertEqual(item["email"], "buyer@example.gov")
        self.assertIn("9", item["phone"])

    def test_deliverable_without_due_date(self):
        item = extract(
            [
                Obj(
                    normalized_text="The contractor shall submit a monthly status report.",
                    raw_text="The contractor shall submit a monthly status report.",
                )
            ]
        ).deliverables[0]
        self.assertIsNone(item["due_information"])
        self.assertEqual(item["frequency"], "monthly")

    def test_evaluation_qualitative_not_numeric(self):
        item = extract(
            [
                Obj(
                    normalized_text="Technical merit is more important than price.",
                    raw_text="Technical merit is more important than price.",
                )
            ]
        ).evaluation_factors[0]
        self.assertIsNone(item["weight"])
        self.assertEqual(item["qualitative_importance"], "more_important_than_price")

    def test_evaluation_points_and_percentage(self):
        item = extract(
            [
                Obj(
                    normalized_text="Evaluation Factor: Experience 30% and 30 points",
                    raw_text="Evaluation Factor: Experience 30% and 30 points",
                )
            ]
        ).evaluation_factors[0]
        self.assertEqual((item["weight"], item["points"]), (30, 30))

    def test_ocr_reduces_confidence_and_is_retained(self):
        fact = extract(
            [
                Obj(
                    normalized_text="Event Number: EVT-55",
                    raw_text="Event Number: EVT-55",
                    extraction_method="ocr",
                    ocr_confidence=61,
                )
            ]
        ).facts[0]
        self.assertEqual(fact.confidence, "medium")
        self.assertEqual(fact.evidence[0].ocr_confidence, 61)

    def test_evidence_is_bounded_and_hash_stable(self):
        block = Obj(
            normalized_text="Issue Date: 2026-07-30" + "x" * 200,
            raw_text="Issue Date: 2026-07-30" + "x" * 200,
        )
        one, two = extract([block]).facts[0].evidence[0], extract([block]).facts[0].evidence[0]
        self.assertLessEqual(len(one.quote), 80)
        self.assertEqual(one.evidence_hash, two.evidence_hash)

    def test_authority_vocabulary(self):
        resolver = DocumentAuthorityResolver()
        cases = [
            (document("Cancellation Notice"), DocumentAuthority.CANCELLATION),
            (document("Addendum 2", addendum_number="2"), DocumentAuthority.ADDENDUM),
            (document("Official Questions and Answers"), DocumentAuthority.QA),
            (document("Intent to Award"), DocumentAuthority.INTENT),
            (document("Award Notice"), DocumentAuthority.AWARD),
        ]
        for value, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(resolver.resolve(value), expected)

    def test_unknown_attachment_not_promoted(self):
        self.assertEqual(
            DocumentAuthorityResolver().resolve(
                document("Map", document_type="file", displayed_filename="map.bin")
            ),
            DocumentAuthority.UNKNOWN,
        )

    def test_award_does_not_control_deadline(self):
        self.assertFalse(
            ReconciliationPolicy.controls(DocumentAuthority.AWARD, "proposal_deadline")
        )
        self.assertTrue(ReconciliationPolicy.controls(DocumentAuthority.AWARD, "award_date"))

    def test_same_authority_conflict_visible(self):
        def result(value):
            return StructuredExtractionResult(
                "o",
                "d",
                "a",
                "e",
                DocumentAuthority.ADDENDUM,
                facts=[StructuredFact("proposal_deadline", value, value)],
            )

        reconciled = SolicitationReconciler().reconcile([result("Aug 1"), result("Aug 2")])
        self.assertEqual(len(reconciled["unresolved_conflicts"]), 1)
        self.assertNotIn("proposal_deadline", reconciled["effective_facts"])

    def test_addendum_changes_only_present_field(self):
        primary = StructuredExtractionResult(
            "o",
            "p",
            "a",
            "e",
            DocumentAuthority.PRIMARY,
            facts=[
                StructuredFact("proposal_deadline", "Aug 1", "Aug 1"),
                StructuredFact("scope", "Work", "Work"),
            ],
        )
        addendum = StructuredExtractionResult(
            "o",
            "d",
            "a2",
            "e2",
            DocumentAuthority.ADDENDUM,
            facts=[StructuredFact("proposal_deadline", "Aug 2", "Aug 2")],
        )
        facts = SolicitationReconciler().reconcile([primary, addendum])["effective_facts"]
        self.assertEqual(facts["proposal_deadline"].normalized_value, "Aug 2")
        self.assertEqual(facts["scope"].normalized_value, "Work")

    def test_settings_bounds(self):
        with self.assertRaises(ValueError):
            Settings(solicitation_intelligence_batch_size=0)
        with self.assertRaises(ValueError):
            Settings(solicitation_intelligence_max_evidence_quote_chars=9000)

    def test_result_completeness_missing_not_failure(self):
        result = extract([])
        self.assertEqual(result.completeness["fields_found"], 0)
        self.assertFalse(result.completeness["missing_is_failure"])

    def test_deterministic_values(self):
        blocks = [
            Obj(normalized_text="Estimated Value: $1,000.00", raw_text="Estimated Value: $1,000.00")
        ]
        one, two = extract(blocks), extract(blocks)
        self.assertEqual(
            json.dumps(one.facts[0].normalized_value), json.dumps(two.facts[0].normalized_value)
        )
        self.assertTrue(one.created_at.tzinfo is UTC)
