from sled_aggregator.domain.enums import AccessState, DocumentEligibility, DocumentRole
from sled_aggregator.domain.models import DocumentCandidate, DocumentClassification


class DocumentClassifier:
    _role_terms: tuple[tuple[DocumentRole, tuple[str, ...]], ...] = (
        (DocumentRole.PWS, ("pws", "performance work statement")),
        (DocumentRole.SOW, ("sow", "statement of work", "scope of work")),
        (DocumentRole.RFP, ("rfp", "request for proposal")),
        (DocumentRole.RFQ, ("rfq", "request for quotation", "request for quote")),
        (DocumentRole.IFB, ("ifb", "invitation for bid", "invitation to bid", "itb")),
        (DocumentRole.AMENDMENT, ("amendment", "addendum", "revision")),
        (
            DocumentRole.QUESTIONS_AND_ANSWERS,
            ("questions and answers", "q&a", "questions responses"),
        ),
        (DocumentRole.PRICING, ("pricing", "price sheet", "cost proposal", "bid schedule")),
        (DocumentRole.EVALUATION, ("evaluation criteria", "scoring criteria")),
        (
            DocumentRole.SUBMISSION_INSTRUCTIONS,
            ("submission instructions", "proposal instructions"),
        ),
        (DocumentRole.SPECIFICATION, ("specification", "specifications", "technical specs")),
        (DocumentRole.REQUIRED_FORM, ("required form", "certification form")),
        (DocumentRole.SOLICITATION, ("solicitation",)),
    )
    _exclude_terms = (
        "vendor registration",
        "newsletter",
        "marketing brochure",
        "annual report",
        "meeting agenda",
    )

    def classify(self, candidate: DocumentCandidate) -> DocumentClassification:
        if candidate.access_state is not AccessState.PUBLIC:
            return DocumentClassification(
                eligibility=DocumentEligibility.RESTRICTED,
                role=DocumentRole.OTHER,
                score=1.0,
                rationale=[f"source access state is {candidate.access_state.value}"],
            )

        text = f"{candidate.filename} {candidate.label or ''}".lower()
        for term in self._exclude_terms:
            if term in text:
                return DocumentClassification(
                    eligibility=DocumentEligibility.EXCLUDE,
                    role=DocumentRole.OTHER,
                    score=0.95,
                    rationale=[f"matched exclusion signal: {term}"],
                )

        for role, terms in self._role_terms:
            for term in terms:
                if term in text:
                    return DocumentClassification(
                        eligibility=DocumentEligibility.INCLUDE,
                        role=role,
                        score=0.9,
                        rationale=[f"matched solicitation signal: {term}"],
                    )

        return DocumentClassification(
            eligibility=DocumentEligibility.REVIEW,
            role=DocumentRole.OTHER,
            score=0.5,
            rationale=["filename and label do not contain a decisive solicitation signal"],
        )
