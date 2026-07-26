from enum import StrEnum


class AccessState(StrEnum):
    PUBLIC = "public"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"
    REMOVED = "removed"


class DocumentEligibility(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"
    RESTRICTED = "restricted"


class DocumentRole(StrEnum):
    SOLICITATION = "solicitation"
    RFP = "rfp"
    RFQ = "rfq"
    IFB = "ifb"
    SOW = "sow"
    PWS = "pws"
    SPECIFICATION = "specification"
    AMENDMENT = "amendment"
    QUESTIONS_AND_ANSWERS = "questions_and_answers"
    PRICING = "pricing"
    EVALUATION = "evaluation"
    SUBMISSION_INSTRUCTIONS = "submission_instructions"
    REQUIRED_FORM = "required_form"
    OTHER = "other"


class OpportunityStatus(StrEnum):
    FORECAST = "forecast"
    OPEN = "open"
    CLOSED = "closed"
    AWARDED = "awarded"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

