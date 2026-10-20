"""
=============================================================================
LEXIS — Persistent Scam Intelligence Management Service
=============================================================================
Provides persistent CRUD, lifecycle workflows (activate, deactivate, versioning),
Review Queue management (approve, reject, merge candidates), indicator-based
deduplication, Qdrant vector synchronization, and citizen upload analysis.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest_models

from core.config import get_settings
from db.qdrant_client import get_qdrant_client
from models.scam_intelligence import (
    CandidateApproveRequest,
    CandidateMergeRequest,
    CandidateRejectRequest,
    ExtractedIndicators,
    ScamAnalysisOutcome,
    ScamAnalysisUploadResponse,
    ScamAnalyticsResponse,
    ScamCandidateRecord,
    ScamPatternCreateRequest,
    ScamPatternRecord,
    ScamPatternUpdateRequest,
    ScamSubmissionRecord,
    ScamVerificationStatus,
)
from services.rag.embedder import BGEM3Embedder
from services.scam.indicator_extractor import ScamIndicatorEngine

logger = logging.getLogger(__name__)

SCAM_COLLECTION_NAME = "scam_patterns"


class ScamIntelligenceService:
    """
    Central service for persistent scam intelligence, candidate review queues,
    and citizen submission processing.
    """

    def __init__(self, mongo_db=None, qdrant_client: Optional[QdrantClient] = None, embedder: Optional[BGEM3Embedder] = None):
        self.mongo_db = mongo_db
        self.qdrant_client = qdrant_client or get_qdrant_client()
        self.embedder = embedder or BGEM3Embedder()

    # =========================================================================
    # Pattern Management (Curated & Verified)
    # =========================================================================

    async def list_patterns(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Lists curated scam patterns from MongoDB `scam_patterns`.
        """
        if self.mongo_db is None:
            return 0, []

        filter_dict: Dict[str, Any] = {}

        if category and category.lower() != "all":
            filter_dict["category"] = category
        if status and status.lower() != "all":
            filter_dict["status"] = status
        if severity and severity.lower() != "all":
            filter_dict["severity"] = severity
        if is_active is not None:
            filter_dict["is_active"] = is_active

        if query and query.strip():
            q_clean = query.strip()
            filter_dict["$or"] = [
                {"name": {"$regex": q_clean, "$options": "i"}},
                {"description": {"$regex": q_clean, "$options": "i"}},
                {"keywords": {"$regex": q_clean, "$options": "i"}},
                {"id": {"$regex": q_clean, "$options": "i"}},
            ]

        col = self.mongo_db["scam_patterns"]
        total = await col.count_documents(filter_dict)
        cursor = col.find(filter_dict).sort("created_at", -1).skip(skip).limit(limit)

        records = []
        async for doc in cursor:
            doc["_id"] = str(doc.get("_id", ""))
            records.append(doc)

        return total, records

    async def get_pattern(self, pattern_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single scam pattern by ID.
        """
        if self.mongo_db is None:
            return None
        doc = await self.mongo_db["scam_patterns"].find_one({"id": pattern_id})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def create_pattern(
        self, request: ScamPatternCreateRequest, reviewer_id: str = "admin"
    ) -> Dict[str, Any]:
        """
        Creates an admin-curated scam pattern and synchronizes with Qdrant and agent cache.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        pattern_id = f"SCAM_INT_{uuid.uuid4().hex[:8].upper()}"

        # Clean keywords
        clean_kws = [k.strip().lower() for k in request.keywords if k.strip()]
        if not clean_kws and request.name:
            clean_kws = [w.lower() for w in request.name.split() if len(w) > 3]

        pattern_doc = {
            "id": pattern_id,
            "name": request.name.strip(),
            "category": request.category,
            "description": request.description.strip(),
            "keywords": clean_kws,
            "legal_reality": request.legal_reality.strip(),
            "recommended_action": request.recommended_action.strip(),
            "reporting_channels": request.reporting_channels,
            "source_ref": request.source_ref.strip(),
            "severity": request.severity,
            "status": ScamVerificationStatus.VERIFIED.value,
            "is_active": request.auto_activate,
            "relevant_identifiers": request.relevant_identifiers,
            "redacted_examples": request.redacted_examples,
            "report_count": 1,
            "version": "1.0",
            "provenance": "admin_curated",
            "first_observed": now_iso,
            "last_observed": now_iso,
            "created_at": now_iso,
            "updated_at": now_iso,
            "reviewed_by": reviewer_id,
            "review_notes": request.review_notes,
        }

        if self.mongo_db is not None:
            await self.mongo_db["scam_patterns"].insert_one(pattern_doc)

        # Index in Qdrant if auto_activate
        if request.auto_activate:
            self._upsert_pattern_vector(pattern_doc)

        # Refresh agent in-memory cache
        self.invalidate_agent_cache()

        logger.info("Created scam pattern '%s' (%s)", pattern_id, request.name)
        pattern_doc["_id"] = str(pattern_doc.get("_id", ""))
        return pattern_doc

    async def update_pattern(
        self, pattern_id: str, updates: ScamPatternUpdateRequest, reviewer_id: str = "admin"
    ) -> Optional[Dict[str, Any]]:
        """
        Updates an existing scam pattern, increments version, and updates Qdrant & cache.
        """
        if self.mongo_db is None:
            return None

        existing = await self.mongo_db["scam_patterns"].find_one({"id": pattern_id})
        if not existing:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        current_version = float(existing.get("version", "1.0"))
        new_version = f"{current_version + 0.1:.1f}"

        set_dict: Dict[str, Any] = {
            "updated_at": now_iso,
            "version": new_version,
            "reviewed_by": reviewer_id,
        }

        if updates.name is not None:
            set_dict["name"] = updates.name.strip()
        if updates.category is not None:
            set_dict["category"] = updates.category
        if updates.description is not None:
            set_dict["description"] = updates.description.strip()
        if updates.keywords is not None:
            set_dict["keywords"] = [k.strip().lower() for k in updates.keywords if k.strip()]
        if updates.legal_reality is not None:
            set_dict["legal_reality"] = updates.legal_reality.strip()
        if updates.recommended_action is not None:
            set_dict["recommended_action"] = updates.recommended_action.strip()
        if updates.reporting_channels is not None:
            set_dict["reporting_channels"] = updates.reporting_channels
        if updates.source_ref is not None:
            set_dict["source_ref"] = updates.source_ref.strip()
        if updates.severity is not None:
            set_dict["severity"] = updates.severity
        if updates.relevant_identifiers is not None:
            set_dict["relevant_identifiers"] = updates.relevant_identifiers
        if updates.redacted_examples is not None:
            set_dict["redacted_examples"] = updates.redacted_examples
        if updates.review_notes is not None:
            set_dict["review_notes"] = updates.review_notes

        await self.mongo_db["scam_patterns"].update_one({"id": pattern_id}, {"$set": set_dict})

        updated = await self.mongo_db["scam_patterns"].find_one({"id": pattern_id})
        if updated.get("is_active", True):
            self._upsert_pattern_vector(updated)
        else:
            self._remove_pattern_vector(pattern_id)

        self.invalidate_agent_cache()
        updated["_id"] = str(updated["_id"])
        return updated

    async def activate_pattern(self, pattern_id: str, reviewer_id: str = "admin") -> bool:
        """
        Activates an approved pattern and ensures its vectors are indexed into Qdrant.
        """
        if self.mongo_db is None:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        res = await self.mongo_db["scam_patterns"].update_one(
            {"id": pattern_id},
            {
                "$set": {
                    "is_active": True,
                    "status": ScamVerificationStatus.VERIFIED.value,
                    "updated_at": now_iso,
                    "reviewed_by": reviewer_id,
                }
            },
        )
        if res.matched_count == 0:
            return False

        doc = await self.mongo_db["scam_patterns"].find_one({"id": pattern_id})
        if doc:
            self._upsert_pattern_vector(doc)
            self.invalidate_agent_cache()

        logger.info("Activated scam pattern '%s'", pattern_id)
        return True

    async def deactivate_pattern(self, pattern_id: str, reviewer_id: str = "admin") -> bool:
        """
        Deactivates a scam pattern, removing it from trusted matching without deleting data.
        """
        if self.mongo_db is None:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        res = await self.mongo_db["scam_patterns"].update_one(
            {"id": pattern_id},
            {
                "$set": {
                    "is_active": False,
                    "status": ScamVerificationStatus.DEACTIVATED.value,
                    "updated_at": now_iso,
                    "reviewed_by": reviewer_id,
                }
            },
        )
        if res.matched_count == 0:
            return False

        self._remove_pattern_vector(pattern_id)
        self.invalidate_agent_cache()

        logger.info("Deactivated scam pattern '%s'", pattern_id)
        return True

    async def delete_pattern(self, pattern_id: str) -> bool:
        """
        Permanently deletes a pattern from MongoDB and Qdrant.
        """
        if self.mongo_db is None:
            return False

        res = await self.mongo_db["scam_patterns"].delete_one({"id": pattern_id})
        self._remove_pattern_vector(pattern_id)
        self.invalidate_agent_cache()
        return res.deleted_count > 0

    # =========================================================================
    # Review Queue & Candidate Discovery
    # =========================================================================

    async def list_review_queue(
        self, status: str = "candidate", skip: int = 0, limit: int = 50
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Lists pending candidate records awaiting admin verification.
        """
        if self.mongo_db is None:
            return 0, []

        filter_dict: Dict[str, Any] = {}
        if status and status.lower() != "all":
            filter_dict["status"] = status

        col = self.mongo_db["scam_candidates"]
        total = await col.count_documents(filter_dict)
        cursor = col.find(filter_dict).sort("last_reported_at", -1).skip(skip).limit(limit)

        records = []
        async for doc in cursor:
            doc["_id"] = str(doc.get("_id", ""))
            records.append(doc)

        return total, records

    async def approve_candidate(
        self, candidate_id: str, request: CandidateApproveRequest, reviewer_id: str = "admin"
    ) -> Optional[Dict[str, Any]]:
        """
        Promotes a candidate intelligence record into a verified scam pattern.
        """
        if self.mongo_db is None:
            return None

        candidate = await self.mongo_db["scam_candidates"].find_one({"candidate_id": candidate_id})
        if not candidate:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        pattern_id = request.pattern_id or f"SCAM_INT_{uuid.uuid4().hex[:8].upper()}"

        clean_kws = [k.strip().lower() for k in request.keywords if k.strip()]
        if not clean_kws and candidate.get("indicators", {}).get("threat_keywords"):
            clean_kws.extend(candidate["indicators"]["threat_keywords"][:5])

        pattern_doc = {
            "id": pattern_id,
            "name": request.name.strip(),
            "category": request.category or candidate.get("category", "Other"),
            "description": request.description or candidate.get("summary", ""),
            "keywords": clean_kws,
            "legal_reality": request.legal_reality.strip(),
            "recommended_action": request.recommended_action.strip(),
            "reporting_channels": request.reporting_channels,
            "source_ref": request.source_ref.strip(),
            "severity": request.severity,
            "status": ScamVerificationStatus.VERIFIED.value,
            "is_active": True,
            "relevant_identifiers": (
                candidate.get("indicators", {}).get("upi_ids", [])
                + candidate.get("indicators", {}).get("phone_numbers", [])
                + candidate.get("indicators", {}).get("domains", [])
            ),
            "redacted_examples": [candidate.get("redacted_text", "")[:600]] if candidate.get("redacted_text") else [],
            "report_count": candidate.get("report_count", 1),
            "version": "1.0",
            "provenance": "candidate_promoted",
            "first_observed": candidate.get("first_reported_at", now_iso),
            "last_observed": candidate.get("last_reported_at", now_iso),
            "created_at": now_iso,
            "updated_at": now_iso,
            "reviewed_by": reviewer_id,
            "review_notes": request.review_notes,
        }

        # Save to scam_patterns
        await self.mongo_db["scam_patterns"].update_one({"id": pattern_id}, {"$set": pattern_doc}, upsert=True)

        # Mark candidate as approved
        await self.mongo_db["scam_candidates"].update_one(
            {"candidate_id": candidate_id},
            {
                "$set": {
                    "status": "approved",
                    "reviewer_id": reviewer_id,
                    "reviewer_notes": request.review_notes,
                    "merged_into_pattern_id": pattern_id,
                    "updated_at": now_iso,
                }
            },
        )

        # Index in Qdrant & sync cache
        self._upsert_pattern_vector(pattern_doc)
        self.invalidate_agent_cache()

        logger.info("Candidate '%s' approved as pattern '%s'", candidate_id, pattern_id)
        pattern_doc["_id"] = str(pattern_doc.get("_id", ""))
        return pattern_doc

    async def reject_candidate(
        self, candidate_id: str, request: CandidateRejectRequest, reviewer_id: str = "admin"
    ) -> bool:
        """
        Rejects a candidate record with required reviewer rationale.
        """
        if self.mongo_db is None:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        res = await self.mongo_db["scam_candidates"].update_one(
            {"candidate_id": candidate_id},
            {
                "$set": {
                    "status": "rejected",
                    "reviewer_id": reviewer_id,
                    "reviewer_notes": request.reason.strip(),
                    "updated_at": now_iso,
                }
            },
        )
        return res.matched_count > 0

    async def merge_candidate(
        self, candidate_id: str, request: CandidateMergeRequest, reviewer_id: str = "admin"
    ) -> bool:
        """
        Merges duplicate candidate into an existing verified pattern.
        """
        if self.mongo_db is None:
            return False

        target = await self.mongo_db["scam_patterns"].find_one({"id": request.target_pattern_id})
        if not target:
            return False

        candidate = await self.mongo_db["scam_candidates"].find_one({"candidate_id": candidate_id})
        if not candidate:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        additional_reports = candidate.get("report_count", 1)

        # Increment report count and record identifier associations
        cand_inds = candidate.get("indicators", {})
        new_identifiers = (
            cand_inds.get("upi_ids", [])
            + cand_inds.get("phone_numbers", [])
            + cand_inds.get("domains", [])
        )

        await self.mongo_db["scam_patterns"].update_one(
            {"id": request.target_pattern_id},
            {
                "$inc": {"report_count": additional_reports},
                "$addToSet": {"relevant_identifiers": {"$each": new_identifiers}},
                "$set": {"last_observed": now_iso, "updated_at": now_iso},
            },
        )

        # Update candidate status
        await self.mongo_db["scam_candidates"].update_one(
            {"candidate_id": candidate_id},
            {
                "$set": {
                    "status": "merged",
                    "merged_into_pattern_id": request.target_pattern_id,
                    "reviewer_id": reviewer_id,
                    "reviewer_notes": request.merge_notes,
                    "updated_at": now_iso,
                }
            },
        )

        logger.info(
            "Candidate '%s' merged into pattern '%s'", candidate_id, request.target_pattern_id
        )
        return True

    # =========================================================================
    # Analytics
    # =========================================================================

    async def get_analytics(self) -> ScamAnalyticsResponse:
        """
        Returns real-time aggregated metrics for scam intelligence and detection.
        """
        if self.mongo_db is None:
            return ScamAnalyticsResponse(
                total_verified_patterns=0,
                active_patterns_count=0,
                pending_candidates_count=0,
                rejected_candidates_count=0,
                merged_candidates_count=0,
                total_citizen_submissions=0,
                likely_scam_count=0,
                suspicious_count=0,
                no_indicators_count=0,
                category_breakdown={},
                recent_activity=[],
            )

        patterns_col = self.mongo_db["scam_patterns"]
        candidates_col = self.mongo_db["scam_candidates"]
        submissions_col = self.mongo_db["scam_submissions"]

        total_patterns = await patterns_col.count_documents({})
        active_patterns = await patterns_col.count_documents({"is_active": {"$ne": False}})

        pending_cand = await candidates_col.count_documents({"status": "candidate"})
        rejected_cand = await candidates_col.count_documents({"status": "rejected"})
        merged_cand = await candidates_col.count_documents({"status": "merged"})

        total_subs = await submissions_col.count_documents({})
        likely_scams = await submissions_col.count_documents({"outcome": ScamAnalysisOutcome.LIKELY_SCAM.value})
        suspicious_subs = await submissions_col.count_documents({"outcome": ScamAnalysisOutcome.SUSPICIOUS.value})
        no_ind_subs = await submissions_col.count_documents(
            {"outcome": ScamAnalysisOutcome.NO_STRONG_INDICATORS.value}
        )

        # Category breakdown
        cat_pipeline = [{"$group": {"_id": {"$ifNull": ["$category", "Other"]}, "count": {"$sum": 1}}}]
        categories = {}
        async for c in patterns_col.aggregate(cat_pipeline):
            categories[str(c["_id"])] = c["count"]

        # Recent activity (submissions & approvals)
        recent_activity = []
        cursor = submissions_col.find({}).sort("created_at", -1).limit(10)
        async for doc in cursor:
            recent_activity.append(
                {
                    "submission_id": doc.get("submission_id"),
                    "outcome": doc.get("outcome"),
                    "content_source": doc.get("content_source"),
                    "created_at": doc.get("created_at"),
                    "matched_pattern_id": doc.get("matched_pattern_id"),
                }
            )

        return ScamAnalyticsResponse(
            total_verified_patterns=total_patterns,
            active_patterns_count=active_patterns,
            pending_candidates_count=pending_cand,
            rejected_candidates_count=rejected_cand,
            merged_candidates_count=merged_cand,
            total_citizen_submissions=total_subs,
            likely_scam_count=likely_scams,
            suspicious_count=suspicious_subs,
            no_indicators_count=no_ind_subs,
            category_breakdown=categories,
            recent_activity=recent_activity,
        )

    # =========================================================================
    # Citizen Content Analysis & Candidate Discovery Pipeline
    # =========================================================================

    async def analyze_content(
        self,
        raw_text: str,
        content_source: str = "pasted_text",
        file_name: Optional[str] = None,
        file_type: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        user_id: str = "anonymous",
    ) -> ScamAnalysisUploadResponse:
        """
        Unified analysis pipeline:
          1. Redacts sensitive credentials.
          2. Extracts deterministic scam indicators (URLs, UPIs, phones, impersonations, threats, OTPs).
          3. Matches against active verified intelligence in Qdrant & MongoDB.
          4. If suspicious but novel, queues in Admin Review Queue.
          5. Returns explainable risk assessment.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        submission_id = f"sub_{uuid.uuid4().hex[:12]}"

        clean_text = raw_text.strip()
        if not clean_text:
            return ScamAnalysisUploadResponse(
                status="unable_to_analyze",
                outcome=ScamAnalysisOutcome.UNABLE_TO_ANALYZE,
                risk_level="LOW",
                confidence_score=0.0,
                summary="The submitted content is empty or unreadable.",
                matching_indicators=ExtractedIndicators(),
                recommended_actions=["Please provide a legible document or paste the suspicious message."],
                candidate_created=False,
                analyzed_at=now_iso,
            )

        # 1. Redact & Extract indicators
        redacted_text = ScamIndicatorEngine.redact_sensitive_data(clean_text)
        indicators = ScamIndicatorEngine.extract_indicators(clean_text)
        indicator_score = ScamIndicatorEngine.calculate_indicator_score(indicators)

        # 2. Check against ScamDetectionAgent
        from agents.scam_detection.agent import get_scam_agent
        scam_agent = get_scam_agent(mongo_db=self.mongo_db, qdrant_client=self.qdrant_client)
        alert_result = await scam_agent.check_scam(clean_text)

        matched_pattern_dict = None
        matched_id = None
        candidate_created = False
        candidate_id = None

        if alert_result.matched:
            # High-confidence pattern match
            matched_id = alert_result.db_id
            outcome = ScamAnalysisOutcome.LIKELY_SCAM
            risk_level = alert_result.severity or "HIGH"
            confidence = max(alert_result.confidence_score, 0.85)

            matched_pattern_dict = {
                "id": alert_result.db_id,
                "name": alert_result.pattern_name,
                "severity": alert_result.severity,
                "description": alert_result.description,
                "legal_reality": alert_result.legal_reality,
                "recommended_action": alert_result.recommended_action,
                "reporting_channels": alert_result.reporting_channels,
                "source_ref": alert_result.source_ref,
                "match_method": alert_result.match_method,
            }

            summary = (
                f"🚨 Matched known scam pattern: '{alert_result.pattern_name}' "
                f"(Severity: {alert_result.severity}). Immediate caution required."
            )
            recommended_actions = [
                a.strip() for a in alert_result.recommended_action.split("\n") if a.strip()
            ]

            # Increment pattern report count in DB
            if self.mongo_db is not None:
                await self.mongo_db["scam_patterns"].update_one(
                    {"id": alert_result.db_id},
                    {"$inc": {"report_count": 1}, "$set": {"last_observed": now_iso}},
                )

        else:
            # No confident match against verified patterns
            # Check for suspicious indicators (threat words, payment demand, OTP, impersonation)
            has_critical_indicators = (
                bool(indicators.otp_requests)
                or (bool(indicators.threat_keywords) and bool(indicators.payment_demands))
                or (bool(indicators.impersonation_claims) and bool(indicators.payment_demands))
                or (bool(indicators.threat_keywords) and bool(indicators.urgency_keywords))
                or bool(indicators.threat_keywords)
                or indicator_score >= 0.25
            )

            if has_critical_indicators:
                outcome = ScamAnalysisOutcome.SUSPICIOUS
                risk_level = "HIGH" if (indicators.otp_requests or indicators.threat_keywords) else "MEDIUM"
                confidence = max(indicator_score, 0.55)

                summary = (
                    "⚠️ Suspicious indicators detected (e.g. urgent demands, impersonation, or payment requests). "
                    "This does NOT match any established pattern in our verified database, but demonstrates coercive fraud patterns. "
                    "This report has been preserved for administrative intelligence verification."
                )
                recommended_actions = [
                    "Do NOT transfer any money or make advance payments.",
                    "Never disclose OTPs, PINs, or netbanking passwords to anyone.",
                    "If you received a call claiming to be law enforcement (CBI, Police), hang up — legitimate police do not conduct video-call arrests.",
                    "Call the National Cyber Helpline: 1930 immediately.",
                    "File an official complaint at cybercrime.gov.in.",
                ]

                # Queue in Review Queue with deduplication
                candidate_created, candidate_id = await self._queue_candidate(
                    redacted_text=redacted_text,
                    indicators=indicators,
                    confidence=confidence,
                    source=content_source,
                    submission_id=submission_id,
                )

            else:
                outcome = ScamAnalysisOutcome.NO_STRONG_INDICATORS
                risk_level = "LOW"
                confidence = 0.20
                summary = (
                    "No strong scam indicators were identified in the submitted content. "
                    "However, absence of a match does NOT guarantee that the document or communication is safe. "
                    "Always verify unknown senders independently before sharing information or funds."
                )
                recommended_actions = [
                    "Verify the sender's identity through official public directories or official websites.",
                    "Never click suspicious attachments or unexpected payment links.",
                    "If in doubt, contact the official organization directly on their published helpline.",
                ]

        # 3. Audit log submission
        if self.mongo_db is not None:
            sub_record = {
                "submission_id": submission_id,
                "user_id": user_id,
                "content_source": content_source,
                "file_name": file_name,
                "file_type": file_type,
                "file_size_bytes": file_size_bytes,
                "outcome": outcome.value,
                "matched_pattern_id": matched_id,
                "confidence_score": confidence,
                "indicators_count": (
                    len(indicators.threat_keywords)
                    + len(indicators.impersonation_claims)
                    + len(indicators.payment_demands)
                    + len(indicators.otp_requests)
                    + len(indicators.upi_ids)
                    + len(indicators.urls)
                ),
                "candidate_id": candidate_id,
                "created_at": now_iso,
            }
            try:
                await self.mongo_db["scam_submissions"].insert_one(sub_record)
            except Exception as exc:
                logger.warning("Could not log scam submission: %s", exc)

        return ScamAnalysisUploadResponse(
            status="matched" if alert_result.matched else ("suspicious" if outcome == ScamAnalysisOutcome.SUSPICIOUS else "no_match"),
            outcome=outcome,
            risk_level=risk_level,
            confidence_score=round(confidence, 4),
            summary=summary,
            matching_indicators=indicators,
            matched_pattern=matched_pattern_dict,
            alert={
                "matched": alert_result.matched,
                "db_id": alert_result.db_id,
                "pattern_name": alert_result.pattern_name,
                "severity": alert_result.severity,
                "match_method": alert_result.match_method,
                "confidence_score": alert_result.confidence_score,
                "description": alert_result.description,
                "legal_reality": alert_result.legal_reality,
                "recommended_action": alert_result.recommended_action,
                "reporting_channels": alert_result.reporting_channels,
                "source_ref": alert_result.source_ref,
                "safe_fallback_message": alert_result.safe_fallback_message,
            } if alert_result.matched else None,
            recommended_actions=recommended_actions,
            candidate_created=candidate_created,
            candidate_id=candidate_id,
            analyzed_at=now_iso,
        )

    async def _queue_candidate(
        self,
        redacted_text: str,
        indicators: ExtractedIndicators,
        confidence: float,
        source: str,
        submission_id: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Adds candidate to `scam_candidates` or deduplicates against an existing candidate.
        """
        if self.mongo_db is None:
            return False, None

        col = self.mongo_db["scam_candidates"]
        now_iso = datetime.now(timezone.utc).isoformat()

        # Check deduplication by indicator hashes or identical phone/UPI
        dedup_query: Dict[str, Any] = {}
        if indicators.indicator_hashes:
            dedup_query["indicators.indicator_hashes"] = {"$in": indicators.indicator_hashes}
        elif indicators.upi_ids:
            dedup_query["indicators.upi_ids"] = {"$in": indicators.upi_ids}
        elif indicators.phone_numbers:
            dedup_query["indicators.phone_numbers"] = {"$in": indicators.phone_numbers}

        if dedup_query:
            existing = await col.find_one({**dedup_query, "status": "candidate"})
            if existing:
                cand_id = existing["candidate_id"]
                await col.update_one(
                    {"candidate_id": cand_id},
                    {
                        "$inc": {"report_count": 1},
                        "$set": {"last_reported_at": now_iso},
                    },
                )
                logger.info("Deduplicated candidate submission to existing '%s'", cand_id)
                return True, cand_id

        # Derive suggested title from indicators
        title_parts = []
        if indicators.impersonation_claims:
            title_parts.append(f"Impersonation ({indicators.impersonation_claims[0].title()})")
        if indicators.threat_keywords:
            title_parts.append(indicators.threat_keywords[0].title())
        elif indicators.payment_demands:
            title_parts.append("Payment Demand")
        elif indicators.otp_requests:
            title_parts.append("OTP Trap")

        suggested_title = " - ".join(title_parts) if title_parts else "Unclassified Suspicious Scam Report"
        candidate_id = f"CAND_{uuid.uuid4().hex[:8].upper()}"

        summary = redacted_text[:300].strip() + ("..." if len(redacted_text) > 300 else "")

        cand_doc = {
            "candidate_id": candidate_id,
            "submission_id": submission_id,
            "suggested_title": suggested_title,
            "category": "Impersonation" if indicators.impersonation_claims else ("Payment/UPI" if indicators.upi_ids or indicators.payment_demands else "Other"),
            "summary": summary,
            "redacted_text": redacted_text[:2000],
            "indicators": indicators.model_dump(),
            "confidence_score": round(confidence, 3),
            "matched_pattern_ids": [],
            "status": "candidate",
            "report_count": 1,
            "first_reported_at": now_iso,
            "last_reported_at": now_iso,
            "source": source,
            "reviewer_id": None,
            "reviewer_notes": None,
            "merged_into_pattern_id": None,
        }

        await col.insert_one(cand_doc)
        logger.info("Queued new candidate intelligence record '%s'", candidate_id)
        return True, candidate_id

    # =========================================================================
    # Vector DB & In-Memory Synchronization
    # =========================================================================

    def _upsert_pattern_vector(self, pattern: Dict[str, Any]) -> None:
        """
        Embeds pattern text and upserts into Qdrant collection `scam_patterns`.
        """
        try:
            if not self.qdrant_client:
                return

            kw_str = ", ".join(pattern.get("keywords", []))
            embed_text = (
                f"Scam: {pattern.get('name', '')}\n"
                f"Description: {pattern.get('description', '')}\n"
                f"Keywords: {kw_str}"
            )
            vector = self.embedder.embed_query(embed_text)

            # Generate stable int ID from pattern string id
            int_id = int(hashlib.md5(pattern["id"].encode("utf-8")).hexdigest()[:8], 16)

            point = rest_models.PointStruct(
                id=int_id,
                vector=vector,
                payload={
                    "pattern_id": pattern["id"],
                    "name": pattern.get("name", ""),
                    "severity": pattern.get("severity", "MEDIUM"),
                    "is_active": True,
                },
            )
            self.qdrant_client.upsert(collection_name=SCAM_COLLECTION_NAME, points=[point])
            logger.info("Vector upserted for pattern '%s' in Qdrant", pattern["id"])
        except Exception as exc:
            logger.error("Failed to upsert vector into Qdrant for '%s': %s", pattern.get("id"), exc)

    def _remove_pattern_vector(self, pattern_id: str) -> None:
        """
        Removes pattern vector from Qdrant by pattern_id payload filter.
        """
        try:
            if not self.qdrant_client:
                return
            self.qdrant_client.delete(
                collection_name=SCAM_COLLECTION_NAME,
                points_selector=rest_models.FilterSelector(
                    filter=rest_models.Filter(
                        must=[
                            rest_models.FieldCondition(
                                key="pattern_id",
                                match=rest_models.MatchValue(value=pattern_id),
                            )
                        ]
                    )
                ),
            )
            logger.info("Removed pattern '%s' vector from Qdrant", pattern_id)
        except Exception as exc:
            logger.warning("Failed to remove vector from Qdrant for '%s': %s", pattern_id, exc)

    def invalidate_agent_cache(self) -> None:
        """
        Dynamic cache invalidation: forces the ScamDetectionAgent singleton to reload
        patterns from MongoDB and recompile its keyword map immediately.
        """
        try:
            from agents.scam_detection.agent import get_scam_agent
            agent = get_scam_agent(mongo_db=self.mongo_db, qdrant_client=self.qdrant_client)
            if hasattr(agent, "reload_intelligence"):
                agent.reload_intelligence()
            else:
                agent._load_pattern_cache()
            logger.info("Scam agent cache invalidated and synchronized.")
        except Exception as exc:
            logger.warning("Agent cache invalidation notification error: %s", exc)
