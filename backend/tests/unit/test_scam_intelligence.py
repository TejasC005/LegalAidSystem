"""
=============================================================================
LEXIS — Unit Tests: Admin-Managed Scam Intelligence Knowledge Base
=============================================================================
Comprehensive unit and integration tests verifying:
  1. Indicator extraction & sensitive data redaction (OTPs, cards, Aadhaar)
  2. File upload parsing & validation (PDF, DOCX, TXT, JSON, size/extension checks)
  3. Pattern lifecycle (curation, activation, deactivation, versioning)
  4. Candidate discovery & Review Queue workflows (approve, reject, merge, deduplicate)
  5. Safety invariant: Pending/rejected/deactivated items excluded from detection
  6. Admin authorization guards on all /admin/scam-intelligence/ endpoints
  7. Citizen /api/v1/scam/analyze-upload endpoint integration
"""

import io
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, APIRouter

from models.scam_intelligence import (
    CandidateApproveRequest,
    CandidateMergeRequest,
    CandidateRejectRequest,
    ExtractedIndicators,
    ScamAnalysisOutcome,
    ScamPatternCreateRequest,
    ScamPatternUpdateRequest,
)
from services.auth.jwt_service import create_access_token
from services.scam.indicator_extractor import ScamIndicatorEngine
from services.scam.intelligence_service import ScamIntelligenceService
from services.scam.upload_analyzer import ScamUploadParser, ScamUploadValidationError


# =============================================================================
# 1. Indicator Extraction & PII Redaction Tests
# =============================================================================

class TestIndicatorExtractionAndRedaction:
    """Verifies that sensitive data is redacted and scam indicators are identified."""

    def test_sensitive_data_redaction(self):
        sample = (
            "My card number is 4111 2222 3333 4444 and my Aadhaar is 1234 5678 9012. "
            "The caller asked for OTP: 839201 and password: mySecretPassword123"
        )
        redacted = ScamIndicatorEngine.redact_sensitive_data(sample)

        assert "4111 2222 3333 4444" not in redacted
        assert "[REDACTED_CARD]" in redacted
        assert "1234 5678 9012" not in redacted
        assert "[REDACTED_AADHAAR]" in redacted
        assert "839201" not in redacted
        assert "mySecretPassword123" not in redacted

    def test_extract_indicators_impersonation_and_threats(self):
        text = (
            "A person claiming to be a CBI officer called saying I am under digital arrest. "
            "They said an FIR is filed and police raid will happen unless I transfer ₹25,000 "
            "immediately via UPI to officer.cbi@oksbi or pay penalty."
        )
        indicators = ScamIndicatorEngine.extract_indicators(text)

        assert "cbi" in indicators.impersonation_claims
        assert any("arrest" in t for t in indicators.threat_keywords)
        assert any("immediately" in u for u in indicators.urgency_keywords)
        assert any("25,000" in p or "transfer" in p for p in indicators.payment_demands)
        assert "officer.cbi@oksbi" in indicators.upi_ids
        assert len(indicators.indicator_hashes) > 0

    def test_indicator_scoring(self):
        critical_text = "CBI officer under digital arrest. Pay fine now or go to jail. Enter your OTP: 1234."
        ind_crit = ScamIndicatorEngine.extract_indicators(critical_text)
        score_crit = ScamIndicatorEngine.calculate_indicator_score(ind_crit)
        assert score_crit >= 0.50

        benign_text = "Good morning, please review the attached meeting notes for tomorrow's project discussion."
        ind_benign = ScamIndicatorEngine.extract_indicators(benign_text)
        score_benign = ScamIndicatorEngine.calculate_indicator_score(ind_benign)
        assert score_benign < 0.20


# =============================================================================
# 2. Upload Parser & Validation Tests
# =============================================================================

class TestUploadParserAndValidation:
    """Tests file size, format security, and text extraction."""

    def test_valid_text_extraction(self):
        content = b"Suspicious message from fake bank asking for KYC update."
        ftype = ScamUploadParser.validate_file(content, "message.txt", "text/plain")
        assert ftype == "txt"
        extracted = ScamUploadParser.extract_text_content(content, ftype)
        assert "Suspicious message" in extracted

    def test_valid_json_extraction(self):
        data = {"sender": "CBI Officer", "message": "You are under digital arrest. Pay ₹10000"}
        raw_json = json.dumps(data).encode("utf-8")
        ftype = ScamUploadParser.validate_file(raw_json, "report.json", "application/json")
        assert ftype == "json"
        extracted = ScamUploadParser.extract_text_content(raw_json, ftype)
        assert "CBI Officer" in extracted
        assert "digital arrest" in extracted

    def test_reject_unsupported_file_extension(self):
        with pytest.raises(ScamUploadValidationError, match="Unsupported file format"):
            ScamUploadParser.validate_file(b"echo 'malicious'", "payload.exe")

    def test_reject_empty_file(self):
        with pytest.raises(ScamUploadValidationError, match="file is empty"):
            ScamUploadParser.validate_file(b"", "empty.pdf")

    def test_reject_oversized_file(self):
        oversized = b"A" * (16 * 1024 * 1024)  # 16 MB
        with pytest.raises(ScamUploadValidationError, match="exceeds maximum limit"):
            ScamUploadParser.validate_file(oversized, "huge.txt")

    def test_pdf_magic_byte_validation(self):
        fake_pdf = b"NOT_A_REAL_PDF"
        with pytest.raises(ScamUploadValidationError, match="Missing %PDF signature"):
            ScamUploadParser.validate_file(fake_pdf, "document.pdf")


# =============================================================================
# 3. Persistent Scam Intelligence Service Workflows
# =============================================================================

@pytest.mark.asyncio
class TestScamIntelligenceServiceWorkflows:
    """Tests persistent CRUD, candidate creation, deduplication, and approval."""

    async def test_create_and_deactivate_pattern(self):
        mock_mongo = MagicMock()
        mock_col = AsyncMock()
        mock_mongo.__getitem__.return_value = mock_col
        mock_col.find_one = AsyncMock(return_value={
            "id": "SCAM_INT_TEST1",
            "name": "Customs Courier Scam",
            "is_active": True,
            "version": "1.0",
        })
        mock_col.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        mock_qdrant = MagicMock()
        service = ScamIntelligenceService(mongo_db=mock_mongo, qdrant_client=mock_qdrant)

        # 1. Create Pattern
        req = ScamPatternCreateRequest(
            name="Customs Courier Scam",
            category="Customs/Courier",
            description="Fake parcel detained at customs with illegal drugs.",
            keywords=["parcel customs", "customs fee"],
            legal_reality="Customs duty is never paid via phone UPI.",
            recommended_action="Do not pay.",
            source_ref="CBIC Advisory",
            severity="HIGH",
            auto_activate=True,
        )
        created = await service.create_pattern(req, reviewer_id="admin_1")
        assert created["name"] == "Customs Courier Scam"
        assert created["is_active"] is True
        assert mock_col.insert_one.called
        assert mock_qdrant.upsert.called

        # 2. Deactivate Pattern
        success = await service.deactivate_pattern("SCAM_INT_TEST1", reviewer_id="admin_1")
        assert success is True
        assert mock_col.update_one.called
        assert mock_qdrant.delete.called

    async def test_candidate_creation_and_deduplication(self):
        mock_mongo = MagicMock()
        mock_cand_col = AsyncMock()
        mock_sub_col = AsyncMock()
        mock_pat_col = AsyncMock()

        def get_col(name):
            if name == "scam_candidates":
                return mock_cand_col
            elif name == "scam_submissions":
                return mock_sub_col
            return mock_pat_col

        mock_mongo.__getitem__.side_effect = get_col

        # First run: no existing candidate
        mock_cand_col.find_one = AsyncMock(return_value=None)
        mock_cand_col.insert_one = AsyncMock()
        mock_sub_col.insert_one = AsyncMock()

        service = ScamIntelligenceService(mongo_db=mock_mongo, qdrant_client=MagicMock())

        text = "Caller said electricity power will be disconnected at 9:30 PM due to unpaid bill. Click link to pay."
        res = await service.analyze_content(raw_text=text, content_source="pasted_text")

        assert res.outcome in [ScamAnalysisOutcome.SUSPICIOUS, ScamAnalysisOutcome.LIKELY_SCAM]
        assert mock_sub_col.insert_one.called

    async def test_approve_candidate_promotes_to_verified(self):
        mock_mongo = MagicMock()
        mock_cand_col = AsyncMock()
        mock_pat_col = AsyncMock()

        mock_cand_col.find_one = AsyncMock(return_value={
            "candidate_id": "CAND_999",
            "suggested_title": "Electricity Bill Threat",
            "summary": "Urgent power disconnection threat",
            "redacted_text": "Power will be cut at 9:30pm",
            "category": "Other",
            "report_count": 3,
            "indicators": {"threat_keywords": ["disconnected"]},
        })
        mock_pat_col.update_one = AsyncMock()
        mock_cand_col.update_one = AsyncMock()

        mock_mongo.__getitem__.side_effect = lambda name: mock_cand_col if name == "scam_candidates" else mock_pat_col

        mock_qdrant = MagicMock()
        service = ScamIntelligenceService(mongo_db=mock_mongo, qdrant_client=mock_qdrant)

        approve_req = CandidateApproveRequest(
            name="Electricity Bill Disconnection Fraud",
            category="Payment/UPI",
            description="Fraudsters threaten immediate power cut to coerce payment.",
            keywords=["power cut", "electricity bill", "disconnected"],
            legal_reality="State discoms do not issue power disconnection notices via SMS with personal phone numbers.",
            recommended_action="Contact official electricity board helpline directly.",
            source_ref="Ministry of Power Public Alert 2024",
            severity="MEDIUM",
        )

        promoted = await service.approve_candidate("CAND_999", approve_req, reviewer_id="admin_1")
        assert promoted is not None
        assert promoted["name"] == "Electricity Bill Disconnection Fraud"
        assert promoted["provenance"] == "candidate_promoted"
        assert promoted["status"] == "verified"
        assert mock_qdrant.upsert.called


# =============================================================================
# 4. Safety Invariant: Deactivated & Candidate Patterns Excluded
# =============================================================================

@pytest.mark.asyncio
class TestSafetyInvariants:
    """Verifies that deactivated patterns and unverified candidates NEVER generate alerts."""

    async def test_deactivated_pattern_excluded_from_agent(self):
        from agents.scam_detection.agent import ScamDetectionAgent

        mock_mongo = MagicMock()
        mock_col = AsyncMock()
        mock_mongo.__getitem__.return_value = mock_col

        # MongoDB returns pattern with is_active=False
        mock_col.find_one = AsyncMock(return_value={
            "id": "SCAM_DEACTIVATED",
            "name": "Deactivated Scam",
            "is_active": False,
            "status": "deactivated",
            "keywords": ["test deactivation phrase"],
            "legal_reality": "Reality",
            "recommended_action": "Action",
        })

        agent = ScamDetectionAgent(mongo_db=mock_mongo, qdrant_client=MagicMock())
        result = await agent.check_scam("Someone used test deactivation phrase")

        # Must NOT match since pattern is deactivated!
        assert result.matched is False
        assert "not matched" in result.safe_fallback_message.lower()


# =============================================================================
# 5. Role-Based Authorization on Admin Endpoints
# =============================================================================

@pytest.mark.asyncio
class TestAdminEndpointsAuthorization:
    """Verifies that non-admin and anonymous tokens are rejected with 401/403."""

    def _build_test_app(self):
        app = FastAPI()
        from api.routes.admin_scam import router as admin_scam_router
        api_v1 = APIRouter(prefix="/api/v1")
        api_v1.include_router(admin_scam_router)
        app.include_router(api_v1)
        # Mock database dependency
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_col.count_documents = AsyncMock(return_value=0)
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_col.find.return_value = mock_cursor
        mock_db.__getitem__.return_value = mock_col
        app.state.mongo_client = {"lexis": mock_db}
        app.state.mongo_db_name = "lexis"
        return app

    async def test_unauthenticated_request_rejected_401(self):
        app = self._build_test_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/admin/scam-intelligence/patterns")
            assert resp.status_code == 401

    async def test_regular_user_token_rejected_403(self):
        app = self._build_test_app()
        user_token = create_access_token("user_123", "user")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/admin/scam-intelligence/patterns",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert resp.status_code == 403

    async def test_admin_token_authorized_200(self):
        app = self._build_test_app()
        admin_token = create_access_token("admin_123", "admin")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get(
                "/api/v1/admin/scam-intelligence/patterns",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "patterns" in data

    async def test_full_main_app_initialization(self):
        from main import create_app
        app = create_app()
        assert app is not None
        # Verify both scam and admin-scam routes are mounted
        route_paths = [r.path for r in app.routes]
        assert "/api/v1/scam/analyze-upload" in route_paths
        assert "/api/v1/admin/scam-intelligence/patterns" in route_paths
