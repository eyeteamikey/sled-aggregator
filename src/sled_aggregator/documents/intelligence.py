import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sled_aggregator.documents.intelligence_types import (
    DocumentAuthority,
    Evidence,
    RequirementStrength,
    StructuredExtractionResult,
    StructuredFact,
)

HEADINGS = {
    "scope": "scope",
    "statement of work": "sow",
    "sow": "sow",
    "performance work statement": "pws",
    "pws": "pws",
    "deliverables": "deliverables",
    "submission instructions": "submission",
    "proposal format": "submission",
    "evaluation criteria": "evaluation",
    "mandatory requirements": "requirements",
    "qualifications": "qualifications",
    "pricing": "pricing",
    "insurance": "insurance",
    "security": "security",
    "cybersecurity": "cybersecurity",
    "questions and answers": "qa",
    "amendment": "amendment",
    "award": "award",
    "cancellation": "cancellation",
}


class SectionClassifier:
    numbered = re.compile(r"^(?P<num>\d+(?:\.\d+)*)[.)]?\s+(?P<title>.{2,100})$")

    def classify(self, blocks: Iterable[Any]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for block in blocks:
            text = block.normalized_text.strip()
            match = self.numbered.match(text)
            candidate = (match.group("title") if match else text).strip(" :-").lower()
            kind = next(
                (v for k, v in HEADINGS.items() if candidate == k or candidate.startswith(k + " ")),
                None,
            )
            heading_signal = (
                block.heading_level is not None
                or block.block_type in {"heading", "table_heading"}
                or match
            )
            if kind and heading_signal and len(text) <= 120:
                level = block.heading_level or (len(match.group("num").split(".")) if match else 1)
                found.append(
                    {
                        "normalized_type": kind,
                        "source_title": text,
                        "sequence": block.sequence,
                        "starting_block_id": block.id,
                        "ending_block_id": block.id,
                        "starting_page": block.page_number,
                        "ending_page": block.page_number,
                        "confidence": "high",
                        "level": level,
                    }
                )
        return found


class DocumentAuthorityResolver:
    def resolve(self, document: Any) -> DocumentAuthority:
        text = " ".join(
            filter(
                None,
                [
                    document.document_type,
                    document.document_category,
                    document.title,
                    document.displayed_filename,
                    document.relationship_type,
                ],
            )
        ).lower()
        if "cancel" in text:
            return DocumentAuthority.CANCELLATION
        if "intent" in text and "award" in text:
            return DocumentAuthority.INTENT
        if "award" in text:
            return DocumentAuthority.AWARD
        if "question" in text or re.search(r"\bq\s*&\s*a\b", text):
            return DocumentAuthority.QA
        if document.amendment_number or "amend" in text:
            return DocumentAuthority.AMENDMENT
        if document.addendum_number or "addend" in text:
            return DocumentAuthority.ADDENDUM
        if "revised" in text or document.supersedes_document_id:
            return DocumentAuthority.REVISED
        if "pricing" in text or "price sheet" in text:
            return DocumentAuthority.PRICING
        if "bid form" in text:
            return DocumentAuthority.BID_FORM
        if "solicitation" in text or "rfp" in text or "invitation for bid" in text:
            return DocumentAuthority.PRIMARY
        if "attachment" in text:
            return DocumentAuthority.ATTACHMENT
        if "notice" in text:
            return DocumentAuthority.NOTICE
        return DocumentAuthority.UNKNOWN


class EvidenceResolver:
    def __init__(self, quote_limit: int = 500, context_limit: int = 800) -> None:
        self.quote_limit, self.context_limit = quote_limit, context_limit

    def from_block(
        self, block: Any, document: Any, extraction: Any, artifact: Any, quote: str | None = None
    ) -> Evidence:
        bounded = (quote or block.raw_text).replace("\x00", "")[: self.quote_limit]
        context = block.raw_text.replace("\x00", "")[: self.context_limit]
        identity = f"{document.id}|{extraction.id}|{block.id}|{bounded}"
        return Evidence(
            document.id,
            artifact.id,
            extraction.id,
            block.id,
            bounded,
            context,
            hashlib.sha256(identity.encode()).hexdigest(),
            block.page_number,
            block.sheet_name,
            block.archive_entry,
            table_index=block.table_index,
            row_start=block.row_start,
            column_start=block.column_start,
            character_start=block.character_start,
            character_end=block.character_end,
            extraction_method=block.extraction_method,
            ocr_confidence=block.ocr_confidence,
        )


class DeterministicSolicitationExtractor:
    extractor_name, extractor_version, schema_version = "deterministic_solicitation", "1.0.0", "1.0"
    supported_document_types = frozenset(
        {"solicitation", "attachment", "addendum", "amendment", "notice"}
    )
    labels = {
        "solicitation_number": re.compile(
            r"(?i)\b(?:solicitation|rfp|ifb)\s*(?:number|no\.?|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})"
        ),
        "event_number": re.compile(
            r"(?i)\bevent\s*(?:number|no\.?|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})"
        ),
        "proposal_deadline": re.compile(
            r"(?i)\b(?:proposal|bid|response)s?\s+(?:due|deadline)\s*:?\s*(.{4,60})"
        ),
        "question_deadline": re.compile(r"(?i)\bquestions?\s+(?:due|deadline)\s*:?\s*(.{4,60})"),
        "issue_date": re.compile(r"(?i)\b(?:issue|issued)\s+date\s*:?\s*(.{4,40})"),
        "place_of_performance": re.compile(r"(?i)\bplace of performance\s*:?\s*(.{3,160})"),
        "estimated_value": re.compile(
            r"(?i)\b(?:estimated value|budget|not to exceed)\s*:?\s*(\$[\d,]+(?:\.\d{2})?)"
        ),
    }
    code_pattern = re.compile(
        r"(?i)\b(NAICS|NIGP|UNSPSC|PSC|commodity code)\s*[:#-]?\s*([A-Z0-9.-]{2,20})"
    )
    email = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
    phone = re.compile(
        r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?:\s*(?:x|ext\.?)\s*\d+)?", re.I
    )

    def __init__(self, quote_limit: int = 500, context_limit: int = 800) -> None:
        self.evidence = EvidenceResolver(quote_limit, context_limit)

    def extract(
        self,
        *,
        opportunity: Any,
        document: Any,
        artifact: Any,
        extraction: Any,
        blocks: list[Any],
        tables: list[Any] | None = None,
        configuration_fingerprint: str = "default",
    ) -> StructuredExtractionResult:
        now = datetime.now(UTC)
        authority = DocumentAuthorityResolver().resolve(document)
        result = StructuredExtractionResult(
            opportunity.id,
            document.id,
            artifact.id,
            extraction.id,
            authority,
            configuration_fingerprint=configuration_fingerprint,
            created_at=now,
        )
        result.sections = SectionClassifier().classify(blocks)
        for block in blocks:
            text = block.normalized_text[:4000]
            ev = self.evidence.from_block(block, document, extraction, artifact)
            score = 65 if block.extraction_method == "ocr" else 90
            confidence = "low" if score < 60 else "medium" if score < 80 else "high"
            for field, pattern in self.labels.items():
                if match := pattern.search(text):
                    raw = match.group(1).strip(" .;")
                    result.facts.append(
                        StructuredFact(
                            field,
                            raw,
                            raw,
                            "datetime" if "date" in field or "deadline" in field else "string",
                            confidence=confidence,
                            confidence_score=score,
                            evidence=[ev],
                            category=self._category(field),
                        )
                    )
            for match in self.code_pattern.finditer(text):
                code = match.group(2).upper()
                system = match.group(1).lower().replace(" ", "_")
                if not any(c["system"] == system and c["code"] == code for c in result.codes):
                    result.codes.append(
                        {"system": system, "code": code, "description": None, "evidence": ev}
                    )
            emails = self.email.findall(text)
            phones = self.phone.findall(text)
            if emails or phones:
                role = next(
                    (
                        r
                        for r in (
                            "contracting officer",
                            "procurement contact",
                            "submission contact",
                            "q&a contact",
                        )
                        if r in text.lower()
                    ),
                    "unspecified",
                )
                result.contacts.append(
                    {
                        "role": role.replace(" ", "_"),
                        "name": None,
                        "email": emails[0].lower() if emails else None,
                        "phone": phones[0] if phones else None,
                        "confidence": confidence,
                        "evidence": ev,
                    }
                )
            strength = self._strength(text)
            if strength:
                result.requirements.append(
                    {
                        "normalized_text": " ".join(text.split()),
                        "original_text": block.raw_text,
                        "strength": strength.value,
                        "category": self._requirement_category(text),
                        "effective_status": "candidate",
                        "evidence": ev,
                    }
                )
            if "deliverable" in text.lower() or re.search(
                r"(?i)\b(?:submit|provide|deliver)\b.+\b(?:report|plan|schedule|invoice)\b", text
            ):
                result.deliverables.append(
                    {
                        "name": text[:120],
                        "description": text,
                        "due_information": None,
                        "frequency": self._frequency(text),
                        "evidence": ev,
                    }
                )
            if re.search(
                r"(?i)\b(?:evaluation factor|points?|percent|best value|lowest responsive|pass/fail|more important than price|approximately equal)\b",
                text,
            ):
                pct = re.search(r"(?i)(\d{1,3})\s*%", text)
                points = re.search(r"(?i)(\d{1,4})\s+points?", text)
                result.evaluation_factors.append(
                    {
                        "name": text[:120],
                        "weight": int(pct.group(1)) if pct else None,
                        "points": int(points.group(1)) if points else None,
                        "qualitative_importance": "more_important_than_price"
                        if "more important than price" in text.lower()
                        else None,
                        "pass_fail": "pass/fail" in text.lower(),
                        "evidence": ev,
                    }
                )
        result.facts = self._dedupe(result.facts)
        result.completeness = {
            "fields_found": len(result.facts),
            "sections_available": sorted({s["normalized_type"] for s in result.sections}),
            "documents_processed": 1,
            "parser_warnings": extraction.warning_count,
            "missing_is_failure": False,
        }
        if extraction.warning_count:
            result.warnings.append("source text extraction completed with warnings")
        result.status = "completed_with_warnings" if result.warnings else "completed"
        result.completed_at = now
        return result

    @staticmethod
    def _category(field: str) -> str:
        if "date" in field or "deadline" in field:
            return "dates"
        if "number" in field:
            return "identity"
        if "value" in field:
            return "pricing"
        return "scope"

    @staticmethod
    def _strength(text: str) -> RequirementStrength | None:
        low = text.lower()
        if re.search(r"\b(?:must not|shall not|may not|prohibited)\b", low):
            return RequirementStrength.PROHIBITED
        if re.search(r"\b(?:if|when|provided that)\b.{0,120}\b(?:must|shall|required)\b", low):
            return RequirementStrength.CONDITIONAL
        if re.search(r"\b(?:must|shall|is required|will be required)\b", low):
            return RequirementStrength.MANDATORY
        if re.search(r"\b(?:should|encouraged)\b", low):
            return RequirementStrength.RECOMMENDED
        if re.search(r"\bmay\b", low):
            return RequirementStrength.OPTIONAL
        return None

    @staticmethod
    def _requirement_category(text: str) -> str:
        low = text.lower()
        for category, terms in {
            "security": ("security", "cyber"),
            "insurance": ("insurance", "coverage"),
            "submission": ("proposal", "submit", "page limit"),
            "staffing": ("personnel", "staff"),
            "past_performance": ("past performance", "reference"),
            "pricing": ("price", "cost"),
        }.items():
            if any(term in low for term in terms):
                return category
        return "technical"

    @staticmethod
    def _frequency(text: str) -> str | None:
        match = re.search(
            r"(?i)\b(daily|weekly|monthly|quarterly|annually|within \d+ days)\b", text
        )
        return match.group(1).lower() if match else None

    @staticmethod
    def _dedupe(facts: list[StructuredFact]) -> list[StructuredFact]:
        seen: set[tuple[str, str]] = set()
        output = []
        for fact in facts:
            key = (
                fact.canonical_field,
                json.dumps(fact.normalized_value, sort_keys=True, default=str).lower(),
            )
            if key not in seen:
                seen.add(key)
                output.append(fact)
        return output


class StructuredExtractorRegistry:
    def __init__(self) -> None:
        self.extractors = [DeterministicSolicitationExtractor()]

    def select(self, _document_type: str) -> DeterministicSolicitationExtractor:
        return self.extractors[0]


class ReconciliationPolicy:
    precedence = {
        DocumentAuthority.CANCELLATION: 100,
        DocumentAuthority.REVISED: 90,
        DocumentAuthority.AMENDMENT: 80,
        DocumentAuthority.ADDENDUM: 80,
        DocumentAuthority.QA: 70,
        DocumentAuthority.PRIMARY: 60,
        DocumentAuthority.PRICING: 55,
        DocumentAuthority.ATTACHMENT: 50,
        DocumentAuthority.NOTICE: 30,
        DocumentAuthority.INTENT: 20,
        DocumentAuthority.AWARD: 20,
        DocumentAuthority.UNKNOWN: 10,
    }

    @staticmethod
    def controls(
        authority: DocumentAuthority, field: str, explicitly_modifies: bool = True
    ) -> bool:
        if authority in {DocumentAuthority.AWARD, DocumentAuthority.INTENT}:
            return field.startswith("award_")
        if authority is DocumentAuthority.CANCELLATION:
            return field == "status"
        if authority is DocumentAuthority.QA:
            return explicitly_modifies
        return True


class SolicitationReconciler:
    def reconcile(self, results: list[StructuredExtractionResult]) -> dict[str, Any]:
        groups: dict[str, list[tuple[StructuredExtractionResult, StructuredFact]]] = {}
        for result in results:
            for fact in result.facts:
                groups.setdefault(fact.canonical_field, []).append((result, fact))
        effective, conflicts, changes = {}, [], []
        for field, candidates in sorted(groups.items()):
            eligible = [
                (r, f) for r, f in candidates if ReconciliationPolicy.controls(r.authority, field)
            ]
            if not eligible:
                continue
            top = max(ReconciliationPolicy.precedence[r.authority] for r, _ in eligible)
            controlling = [
                (r, f) for r, f in eligible if ReconciliationPolicy.precedence[r.authority] == top
            ]
            values = {
                json.dumps(f.normalized_value, sort_keys=True, default=str) for _, f in controlling
            }
            if len(values) > 1:
                group = hashlib.sha256(
                    (field + "|" + "|".join(sorted(values))).encode()
                ).hexdigest()[:24]
                conflicts.append(
                    {
                        "conflict_group": group,
                        "canonical_field": field,
                        "reason": "incompatible same-authority values",
                        "status": "unresolved",
                    }
                )
                for _, fact in controlling:
                    fact.effective_status = "conflicting"
            else:
                selected = controlling[-1][1]
                selected.effective_status = "effective"
                effective[field] = selected
                changes.append(
                    {
                        "canonical_field": field,
                        "change_type": "added",
                        "new_value": selected.normalized_value,
                        "reason": "highest field-specific authority",
                    }
                )
            for _, fact in candidates:
                if fact is not effective.get(field) and fact.effective_status != "conflicting":
                    fact.effective_status = "superseded"
        return {"effective_facts": effective, "unresolved_conflicts": conflicts, "changes": changes}
