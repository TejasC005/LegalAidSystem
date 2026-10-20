"""
=============================================================================
LEXIS — Scam Intelligence Knowledge Base Data Models
=============================================================================
Defines persistent schemas for admin-curated scam patterns, candidate reports
from citizen submissions, extracted indicators, review queue workflows, and
citizen document analysis envelopes.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class ScamVerificationStatus(str, Enum):
    VERIFIED = "verified"
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    DEACTIVATED = "deactivated"
    NEEDS_EVIDENCE = "needs_evidence"


class ScamRiskClassification(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ScamCategory(str, Enum):
    IMPERSONATION = "Impersonation"
    PAYMENT_UPI = "Payment/UPI"
    INVESTMENT = "Investment"
    JOB_EMPLOYMENT = "Job/Employment"
    KYC_IDENTITY = "KYC/Identity"
    LOTTERY_PHISHING = "Lottery/Phishing"
    LOAN_CREDIT = "Loan/Credit"
    CUSTOMS_COURIER = "Customs/Courier"
    DIGITAL_ARREST = "Digital Arrest"
    OTHER = "Other"


class ScamAnalysisOutcome(str, Enum):
    LIKELY_SCAM = "Likely scam"
    SUSPICIOUS = "Suspicious — needs verification"
    NO_STRONG_INDICATORS = "No strong scam indicators found"
    UNABLE_TO_ANALYZE = "Unable to analyze"


class ExtractedIndicators(BaseModel):
    """
    Normalized, redacted indicators discovered in uploaded document or text.
    """
    urls: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    phone_numbers: List[str] = Field(default_factory=list)
    email_addresses: List[str] = Field(default_factory=list)
    upi_ids: List[str] = Field(default_factory=list)
    payment_demands: List[str] = Field(default_factory=list)
    impersonation_claims: List[str] = Field(default_factory=list)
    urgency_keywords: List[str] = Field(default_factory=list)
    threat_keywords: List[str] = Field(default_factory=list)
    otp_requests: List[str] = Field(default_factory=list)
    sensitive_info_requests: List[str] = Field(default_factory=list)
    indicator_hashes: List[str] = Field(default_factory=list)


class ScamPatternRecord(BaseModel):
    """
    Authoritative scam pattern record stored in MongoDB `scam_patterns`.
    Maintains 100% backward compatibility with seed pattern schema (id, name,
    description, keywords, legal_reality, recommended_action, reporting_channels,
    source_ref, severity), enriched with intelligence lifecycle fields.
    """
    id: str
    name: str
    category: str = "Other"
    description: str
    keywords: List[str] = Field(default_factory=list)
    legal_reality: str
    recommended_action: str
    reporting_channels: List[str] = Field(default_factory=list)
    source_ref: str
    severity: str = "MEDIUM"
    status: str = "verified"             # verified | deactivated
    is_active: bool = True
    indicators: Optional[ExtractedIndicators] = None
    redacted_examples: List[str] = Field(default_factory=list)
    relevant_identifiers: List[str] = Field(default_factory=list)
    report_count: int = 1
    version: str = "1.0"
    provenance: str = "seed"            # seed | admin_curated | candidate_promoted
    first_observed: str = ""
    last_observed: str = ""
    created_at: str = ""
    updated_at: str = ""
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None


class ScamCandidateRecord(BaseModel):
    """
    Candidate intelligence record awaiting human admin verification in Review Queue.
    Never used in trusted high-confidence detection until approved.
    """
    candidate_id: str
    submission_id: str
    suggested_title: str
    category: str = "Other"
    summary: str
    redacted_text: str
    indicators: ExtractedIndicators
    confidence_score: float = 0.0
    matched_pattern_ids: List[str] = Field(default_factory=list)
    status: str = "candidate"           # candidate | approved | rejected | merged | needs_evidence
    report_count: int = 1
    first_reported_at: str
    last_reported_at: str
    source: str = "citizen_upload"
    reviewer_id: Optional[str] = None
    reviewer_notes: Optional[str] = None
    merged_into_pattern_id: Optional[str] = None


class ScamSubmissionRecord(BaseModel):
    """
    Audit log of citizen submissions with retention metadata.
    Sensitive payload is redacted before persistence.
    """
    submission_id: str
    user_id: str = "anonymous"
    content_source: str = "pasted_text" # file_upload | pasted_text
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    outcome: str = ScamAnalysisOutcome.NO_STRONG_INDICATORS.value
    matched_pattern_id: Optional[str] = None
    confidence_score: float = 0.0
    indicators_count: int = 0
    candidate_id: Optional[str] = None
    created_at: str


# ── Request / Response Envelopes ─────────────────────────────────────────────

class ScamPatternCreateRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=120)
    category: str = Field(default="Other")
    description: str = Field(..., min_length=10)
    keywords: List[str] = Field(default_factory=list)
    legal_reality: str = Field(..., min_length=10)
    recommended_action: str = Field(..., min_length=10)
    reporting_channels: List[str] = Field(default_factory=lambda: ["cybercrime.gov.in", "Helpline: 1930"])
    source_ref: str = Field(..., min_length=3)
    severity: str = Field(default="MEDIUM")
    relevant_identifiers: List[str] = Field(default_factory=list)
    redacted_examples: List[str] = Field(default_factory=list)
    auto_activate: bool = True
    review_notes: Optional[str] = None


class ScamPatternUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    legal_reality: Optional[str] = None
    recommended_action: Optional[str] = None
    reporting_channels: Optional[List[str]] = None
    source_ref: Optional[str] = None
    severity: Optional[str] = None
    relevant_identifiers: Optional[List[str]] = None
    redacted_examples: Optional[List[str]] = None
    review_notes: Optional[str] = None


class CandidateApproveRequest(BaseModel):
    pattern_id: Optional[str] = None    # If empty, auto-generate SCAM_INT_...
    name: str = Field(..., min_length=3)
    category: str = Field(default="Other")
    description: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    legal_reality: str = Field(..., min_length=10)
    recommended_action: str = Field(..., min_length=10)
    reporting_channels: List[str] = Field(default_factory=lambda: ["cybercrime.gov.in", "Helpline: 1930"])
    source_ref: str = Field(..., min_length=3)
    severity: str = Field(default="MEDIUM")
    review_notes: Optional[str] = None


class CandidateRejectRequest(BaseModel):
    reason: str = Field(..., min_length=3)


class CandidateMergeRequest(BaseModel):
    target_pattern_id: str = Field(..., description="ID of existing pattern to merge into")
    merge_notes: Optional[str] = None


class ScamAnalyticsResponse(BaseModel):
    total_verified_patterns: int
    active_patterns_count: int
    pending_candidates_count: int
    rejected_candidates_count: int
    merged_candidates_count: int
    total_citizen_submissions: int
    likely_scam_count: int
    suspicious_count: int
    no_indicators_count: int
    category_breakdown: Dict[str, int] = Field(default_factory=dict)
    recent_activity: List[Dict[str, Any]] = Field(default_factory=list)


class ScamAnalysisUploadResponse(BaseModel):
    status: str                         # "matched" | "suspicious" | "no_match" | "unable_to_analyze"
    outcome: ScamAnalysisOutcome
    risk_level: str                     # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    confidence_score: float
    summary: str
    matching_indicators: ExtractedIndicators
    matched_pattern: Optional[Dict[str, Any]] = None
    alert: Optional[Dict[str, Any]] = None
    recommended_actions: List[str] = Field(default_factory=list)
    candidate_created: bool = False
    candidate_id: Optional[str] = None
    analyzed_at: str
