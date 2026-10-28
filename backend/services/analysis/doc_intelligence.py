"""
=============================================================================
LEXIS — Document Intelligence Service (Module 7)
=============================================================================

PURPOSE:
Transforms the Document Analyzer from a pure contract clause checker into
an intelligent, multi-type legal document analyzer that:
  1. Auto-classifies any uploaded document:
     - Identity Documents (Aadhaar, PAN, Voter ID, Passport)
     - Court Documents (Judgments, Orders, Bail Orders)
     - Agreements & Contracts (Rental Deeds, Service Agreements, NDAs)
     - General Legal Documents (Affidavits, Notices, Powers of Attorney)
  2. Extracts key entities and structured metadata without asking questions.
  3. Translates complex court verdicts into simple everyday language (EN + HI).
  4. Formats and normalizes dates (e.g. ISO YYYY-MM-DD for user profiles).
"""

import re
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

from core.config import get_settings
from agents.document_analyzer.prompts import (
    DOC_CLASSIFICATION_SYSTEM,
    DOC_CLASSIFICATION_USER,
    IDENTITY_EXTRACTION_SYSTEM,
    IDENTITY_EXTRACTION_USER,
    RENTAL_EXTRACTION_SYSTEM,
    RENTAL_EXTRACTION_USER,
    COURT_EXTRACTION_SYSTEM,
    COURT_EXTRACTION_USER,
    GENERAL_LEGAL_EXTRACTION_SYSTEM,
    GENERAL_LEGAL_EXTRACTION_USER,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATE NORMALIZATION UTILITY
# =============================================================================

def normalize_to_iso_date(date_str: Optional[str]) -> Optional[str]:
    """
    Normalizes diverse Indian date strings (DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD)
    into standard ISO format (YYYY-MM-DD) for database storage and profile models.
    Returns None if parsing fails.
    """
    if not date_str:
        return None

    cleaned = date_str.strip()
    # Match 4-digit year format (YYYY-MM-DD)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        return cleaned

    # Common formats in Indian IDs and legal deeds
    formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y/%m/%d",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Try extracting via regex if embedded in surrounding text (e.g., "DOB: 15/08/1985")
    match = re.search(r"\b(\d{2})[\/\-\.](\d{2})[\/\-\.](\d{4})\b", cleaned)
    if match:
        day, month, year = match.groups()
        try:
            dt = datetime(int(year), int(month), int(day))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None


# =============================================================================
# LLM HELPER (Google GenAI with OpenAI fallback)
# =============================================================================

async def _call_llm_json(
    system_prompt: str,
    user_prompt: str,
    api_key: str = "",
    model: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Invokes the configured LLM (Google GenAI first, OpenAI second) and parses
    the resulting JSON output cleanly.
    """
    settings = get_settings()
    gemini_key = settings.GEMINI_API_KEY or api_key
    gemini_model = settings.GEMINI_MODEL_DEV or "gemini-2.5-flash"

    # Path A: Google GenAI Client with multi-model cascade
    if gemini_key and not gemini_key.startswith("sk-replace"):
        candidate_models = [
            settings.GEMINI_MODEL_DEV or "gemini-3.5-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-2.5-flash",
        ]
        seen = set()
        models_to_try = [m for m in candidate_models if not (m in seen or seen.add(m))]

        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            full_prompt = f"{system_prompt}\n\n{user_prompt}"

            for m_name in models_to_try:
                try:
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=m_name,
                            contents=full_prompt,
                        ),
                        timeout=5.0,
                    )
                    raw_text = response.text.strip() if response.text else ""
                    parsed = _extract_json_from_text(raw_text)
                    if parsed:
                        return parsed
                except Exception as m_exc:
                    logger.warning("GenAI JSON generation attempt failed with model '%s': %s", m_name, m_exc)
        except Exception as exc:
            logger.warning("GenAI client initialization failed: %s", exc)

    # Path B: OpenAI fallback if OpenAI key exists
    openai_key = settings.OPENAI_API_KEY
    if openai_key and not openai_key.startswith("sk-replace"):
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=openai_key)
            resp = await client.chat.completions.create(
                model=settings.OPENAI_MODEL_DEV or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            return json.loads(raw)
        except Exception as exc:
            logger.warning("OpenAI fallback failed: %s", exc)

    return None


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extracts and parses a JSON object from raw markdown code blocks or text."""
    if not text:
        return None

    # Strip markdown ```json code block if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback regex search for { ... }
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return None


# =============================================================================
# DOCUMENT CLASSIFICATION SERVICE
# =============================================================================

async def classify_document_type(
    text: str,
    api_key: str = "",
    model: str = "",
) -> Tuple[str, str, str]:
    """
    Categorizes the document into:
      category: "identity_document" | "court_document" | "agreement_contract" | "general_legal"
      doc_type: "aadhaar_card" | "pan_card" | "rental_agreement" | "court_judgment" | "contract" | "other"
      title: Human-readable display label

    Uses high-speed heuristic signatures first; falls back to LLM for ambiguous texts.
    """
    text_lower = text.lower()
    text_sample = text[:3000]

    # ── 1. Heuristic: Aadhaar Card ────────────────────────────────────────────
    aadhaar_keywords = [
        "unique identification authority of india",
        "uidai",
        "mera aadhaar meri pehchan",
        "government of india",
        "mera aadhaar",
        "enrollment no",
    ]
    has_aadhaar_kw = any(kw in text_lower for kw in aadhaar_keywords)
    has_aadhaar_pattern = bool(re.search(r"\b\d{4}\s\d{4}\s\d{4}\b", text))
    if has_aadhaar_kw or (has_aadhaar_pattern and "income tax" not in text_lower):
        if "unique identification" in text_lower or has_aadhaar_pattern or "aadhaar" in text_lower:
            return "identity_document", "aadhaar_card", "Aadhaar Card (UIDAI)"

    # ── 2. Heuristic: PAN Card ────────────────────────────────────────────────
    pan_keywords = [
        "income tax department",
        "permanent account number",
        "govt. of india",
        "father's name",
    ]
    has_pan_pattern = bool(re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text))
    if has_pan_pattern or ("income tax department" in text_lower and "permanent account" in text_lower):
        return "identity_document", "pan_card", "Permanent Account Number (PAN Card)"

    # ── 3. Heuristic: Court Judgment / Order ──────────────────────────────────
    court_keywords = [
        "in the high court",
        "supreme court of india",
        "court of judicature",
        "district court",
        "sessions court",
        "petitioner",
        "respondent",
        "versus",
        "bail appl",
        "writ petition",
        "coram:",
        "operative order",
        "impugned order",
    ]
    court_hits = sum(1 for kw in court_keywords if kw in text_lower)
    if court_hits >= 2:
        # Determine specific court order type
        if "bail" in text_lower:
            return "court_document", "court_judgment", "Court Order — Bail Application"
        return "court_document", "court_judgment", "Court Judgment / Order"

    # ── 4. Heuristic: Rental Agreement ────────────────────────────────────────
    rental_keywords = [
        "rent agreement",
        "tenancy agreement",
        "lease deed",
        "residential lease",
        "landlord",
        "lessor",
        "tenant",
        "lessee",
        "security deposit",
        "monthly rent",
        "rent of rs",
        "licensed premises",
    ]
    rental_hits = sum(1 for kw in rental_keywords if kw in text_lower)
    if rental_hits >= 2:
        return "agreement_contract", "rental_agreement", "Residential Tenancy Agreement"

    # ── 5. Heuristic: General Legal Agreement ─────────────────────────────────
    contract_keywords = [
        "agreement",
        "this agreement is made",
        "indemnification",
        "arbitration",
        "governing law",
        "terms and conditions",
    ]
    contract_hits = sum(1 for kw in contract_keywords if kw in text_lower)
    if contract_hits >= 2:
        return "agreement_contract", "contract", "Legal Contract / Agreement"

    # ── 6. LLM Fallback for ambiguous texts ───────────────────────────────────
    llm_result = await _call_llm_json(
        DOC_CLASSIFICATION_SYSTEM,
        DOC_CLASSIFICATION_USER.format(text=text_sample),
        api_key=api_key,
        model=model,
    )
    if llm_result:
        cat = llm_result.get("category", "general_legal")
        dtype = llm_result.get("document_type", "other")
        title = llm_result.get("title", "Legal Document")
        return cat, dtype, title

    # Default fallback
    return "agreement_contract", "contract", "General Legal Document"


# =============================================================================
# IDENTITY DOCUMENT EXTRACTOR
# =============================================================================

async def extract_identity_info(
    text: str,
    doc_type: str = "aadhaar_card",
    api_key: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """
    Extracts name, ID number, address, DOB, and issuing authority from Aadhaar or PAN.
    Combines high-reliability regex patterns with LLM structured parsing.
    """
    extracted: Dict[str, Any] = {
        "name": None,
        "id_number": None,
        "id_type": "Aadhaar Card" if doc_type == "aadhaar_card" else "PAN Card",
        "dob": None,
        "dob_iso": None,
        "gender": None,
        "care_of": None,
        "address": None,
        "city": None,
        "pin_code": None,
        "issuing_authority": "Unique Identification Authority of India (UIDAI)" if doc_type == "aadhaar_card" else "Income Tax Department",
    }

    # ── Deterministic Regex Extraction ────────────────────────────────────────
    # 1. Aadhaar 12-digit number (masked)
    aadhaar_match = re.search(r"\b(\d{4}\s\d{4}\s\d{4})\b", text)
    if aadhaar_match:
        raw_id = aadhaar_match.group(1)
        # Mask first 8 digits: XXXX XXXX 1234
        extracted["id_number"] = f"XXXX XXXX {raw_id[-4:]}"
        extracted["id_type"] = "Aadhaar Card"

    # 2. PAN Number format: [A-Z]{5}[0-9]{4}[A-Z]
    pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text)
    if pan_match:
        extracted["id_number"] = pan_match.group(1)
        extracted["id_type"] = "PAN Card"

    # 3. DOB detection
    dob_match = re.search(r"(?:DOB|Date of Birth|जन्म तिथि)[:\s]*([0-9]{2}[\/\-][0-9]{2}[\/\-][0-9]{4})", text, re.IGNORECASE)
    if not dob_match:
        dob_match = re.search(r"\b([0-9]{2}[\/\-][0-9]{2}[\/\-][0-9]{4})\b", text)
    if dob_match:
        raw_dob = dob_match.group(1)
        extracted["dob"] = raw_dob
        extracted["dob_iso"] = normalize_to_iso_date(raw_dob)

    # 4. Gender detection
    if re.search(r"\b(Female|महिला)\b", text, re.IGNORECASE):
        extracted["gender"] = "Female"
    elif re.search(r"\b(Male|पुरुष)\b", text, re.IGNORECASE):
        extracted["gender"] = "Male"

    # 5. PIN code detection (6-digit Indian PIN)
    pin_match = re.search(r"\b([1-9][0-9]{5})\b", text)
    if pin_match:
        extracted["pin_code"] = pin_match.group(1)

    # ── LLM Extraction Pass (Fills Full Name, Address, Care of, City) ─────────
    llm_data = await _call_llm_json(
        IDENTITY_EXTRACTION_SYSTEM,
        IDENTITY_EXTRACTION_USER.format(text=text[:3500]),
        api_key=api_key,
        model=model,
    )

    if llm_data and isinstance(llm_data, dict):
        # Merge LLM fields when not already found or when more complete
        if llm_data.get("name"):
            extracted["name"] = str(llm_data["name"]).strip()
        if not extracted["id_number"] and llm_data.get("id_number"):
            extracted["id_number"] = str(llm_data["id_number"]).strip()
        if not extracted["dob"] and llm_data.get("dob"):
            extracted["dob"] = str(llm_data["dob"]).strip()
            extracted["dob_iso"] = normalize_to_iso_date(extracted["dob"])
        if not extracted["dob_iso"] and llm_data.get("dob_iso"):
            extracted["dob_iso"] = normalize_to_iso_date(str(llm_data["dob_iso"]).strip())
        if not extracted["gender"] and llm_data.get("gender"):
            extracted["gender"] = str(llm_data["gender"]).strip()

        if llm_data.get("care_of"):
            extracted["care_of"] = str(llm_data["care_of"]).strip()
        if llm_data.get("address"):
            extracted["address"] = str(llm_data["address"]).strip()
        if llm_data.get("city"):
            extracted["city"] = str(llm_data["city"]).strip()
        if not extracted["pin_code"] and llm_data.get("pin_code"):
            extracted["pin_code"] = str(llm_data["pin_code"]).strip()
        if llm_data.get("issuing_authority"):
            extracted["issuing_authority"] = str(llm_data["issuing_authority"]).strip()

    # Fallback name, address, and city extraction for offline parsing/unit tests if LLM is unavailable
    if not extracted["name"]:
        name_match = re.search(r"(?:Name|नाम|Full Name)[:\s]+([A-Za-z\s\.]+)", text, re.IGNORECASE)
        if name_match:
            cand = name_match.group(1).splitlines()[0].strip()
            if cand and not any(kw in cand.lower() for kw in ["income tax", "government", "unique", "uidai", "father", "dob", "address"]):
                extracted["name"] = cand

    if not extracted["name"]:
        lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 3]
        for line in lines[:8]:
            if not any(kw in line.lower() for kw in ["income tax", "government", "unique", "uidai", "india", "father", "dob", "male", "female"]):
                if re.match(r"^[A-Z][a-zA-Z\s\.]+$", line) and len(line) < 40:
                    extracted["name"] = line
                    break

    if not extracted["address"]:
        addr_match = re.search(r"(?:Address|पता)[:\s]+([^\n\r]+)", text, re.IGNORECASE)
        if addr_match:
            extracted["address"] = addr_match.group(1).strip()

    if not extracted["city"] and extracted.get("address"):
        for city_cand in ["Bangalore", "Bengaluru", "Delhi", "New Delhi", "Mumbai", "Pune", "Hyderabad", "Chennai", "Kolkata", "Noida", "Gurugram"]:
            if city_cand.lower() in extracted["address"].lower():
                extracted["city"] = city_cand
                break

    # 6. Aadhaar card side detection
    if doc_type == "aadhaar_card":
        if extracted.get("name") and extracted.get("id_number") and not extracted.get("address"):
            extracted["card_side"] = "front"
        elif extracted.get("address"):
            extracted["card_side"] = "both"
        else:
            extracted["card_side"] = "front"
    else:
        extracted["card_side"] = "both"

    return extracted


# =============================================================================
# RENTAL AGREEMENT EXTRACTOR
# =============================================================================

async def extract_rental_agreement_info(
    text: str,
    api_key: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """
    Extracts key tenancy parameters: parties, rent, deposit, tenure, and notice periods.
    Generates plain-language explanation of tenant commitments.
    """
    extracted: Dict[str, Any] = {
        "landlord_name": None,
        "tenant_name": None,
        "property_address": None,
        "monthly_rent": None,
        "rent_due_day": "5th of each month",
        "security_deposit": None,
        "deposit_refund_terms": "Refundable within 30 days of vacating after deductions for damages.",
        "lease_duration": "11 Months",
        "notice_period": "1 Month",
        "lock_in_period": "None",
        "plain_language_summary": "",
        "plain_language_summary_hi": "",
    }

    # Deterministic heuristics
    rent_match = re.search(r"(?:rent\s*(?:of)?\s*(?:rs\.?|inr|₹)?\s*)([0-9,]+)", text, re.IGNORECASE)
    if rent_match:
        extracted["monthly_rent"] = f"₹{rent_match.group(1)} / month"

    deposit_match = re.search(r"(?:deposit\s*(?:of)?\s*(?:rs\.?|inr|₹)?\s*)([0-9,]+)", text, re.IGNORECASE)
    if deposit_match:
        extracted["security_deposit"] = f"₹{deposit_match.group(1)} (Refundable)"

    if "11 months" in text.lower() or "eleven months" in text.lower():
        extracted["lease_duration"] = "11 Months"

    # LLM extraction pass
    llm_data = await _call_llm_json(
        RENTAL_EXTRACTION_SYSTEM,
        RENTAL_EXTRACTION_USER.format(text=text[:4000]),
        api_key=api_key,
        model=model,
    )

    if llm_data and isinstance(llm_data, dict):
        for k in extracted.keys():
            if llm_data.get(k):
                extracted[k] = llm_data[k]

    if not extracted["plain_language_summary"]:
        rent_val = extracted["monthly_rent"] or "agreed amount"
        dep_val = extracted["security_deposit"] or "security deposit"
        extracted["plain_language_summary"] = (
            f"This is a residential tenancy agreement for premises leased at {rent_val} "
            f"with a {dep_val}. Under Indian Model Tenancy provisions, the security deposit must "
            f"be refunded within one month of vacating the property."
        )
        extracted["plain_language_summary_hi"] = (
            f"यह {rent_val} के मासिक किराए और {dep_val} की सुरक्षा राशि के साथ एक आवासीय किराया समझौता है। "
            f"मकान खाली करने के एक महीने के भीतर डिपॉजिट वापस किया जाना अनिवार्य है।"
        )

    return extracted


# =============================================================================
# COURT JUDGMENT EXTRACTOR
# =============================================================================

async def extract_court_order_info(
    text: str,
    api_key: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """
    Extracts court name, case number, parties, judge, verdict, and operative directions.
    Translates ruling into plain language for everyday citizens in both English & Hindi.
    """
    extracted: Dict[str, Any] = {
        "court_name": "High Court / District Court",
        "case_number": None,
        "decision_date": None,
        "bench": None,
        "petitioner": None,
        "respondent": None,
        "acts_sections": [],
        "verdict": "ORDER PASSED",
        "operative_order": "",
        "plain_language_summary": "",
        "plain_language_summary_hi": "",
        "key_actions": [],
    }

    # Deterministic heuristics for court name and verdict
    for c_cand in ["Supreme Court of India", "High Court of Judicature at Bombay", "Bombay High Court", "Delhi High Court", "High Court of Karnataka"]:
        if c_cand.lower() in text.lower():
            extracted["court_name"] = c_cand
            break

    text_upper = text.upper()
    if "BAIL IS GRANTED" in text_upper or "ADMITTED TO BAIL" in text_upper or "BAIL GRANTED" in text_upper:
        extracted["verdict"] = "BAIL GRANTED"
    elif "PETITION DISMISSED" in text_upper or "DISMISSED" in text_upper:
        extracted["verdict"] = "PETITION DISMISSED"
    elif "INTERIM RELIEF GRANTED" in text_upper or "INJUNCTION ALLOWED" in text_upper or ("INJUNCTION" in text_upper and "GRANTED" in text_upper):
        extracted["verdict"] = "RELIEF / INJUNCTION GRANTED"
    elif "DISPOSED OF" in text_upper:
        extracted["verdict"] = "DISPOSED OF WITH DIRECTIONS"

    # CNR / Case number heuristic
    case_match = re.search(r"\b((?:BAIL\s+APPLN|CRL\.\s*M\.\s*C|W\.?\s*P\.?|CNR\s*NO\.?)\s*[:\.]?\s*[0-9A-Z\/\-]+)\b", text, re.IGNORECASE)
    if case_match:
        extracted["case_number"] = case_match.group(1).strip()

    # LLM extraction pass
    llm_data = await _call_llm_json(
        COURT_EXTRACTION_SYSTEM,
        COURT_EXTRACTION_USER.format(text=text[:4000]),
        api_key=api_key,
        model=model,
    )

    if llm_data and isinstance(llm_data, dict):
        for k in extracted.keys():
            if llm_data.get(k):
                extracted[k] = llm_data[k]

    if not extracted["plain_language_summary"]:
        extracted["plain_language_summary"] = (
            f"The court has reviewed this matter and ordered: {extracted['verdict']}. "
            "Please examine the compliance requirements and key directions issued by the judge."
        )
        extracted["plain_language_summary_hi"] = (
            f"अदालत ने इस मामले की सुनवाई पूरी कर फैसला दिया है: {extracted['verdict']}। "
            "कृपया न्यायाधीश द्वारा दिए गए निर्देशों और आवश्यक औपचारिकताओं का पालन करें।"
        )

    return extracted


# =============================================================================
# GENERAL LEGAL DOCUMENT EXTRACTOR
# =============================================================================

async def extract_general_legal_info(
    text: str,
    api_key: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """
    Extracts summary, parties, and core obligations from general legal notices,
    affidavits, or uncategorized contracts.
    """
    extracted: Dict[str, Any] = {
        "document_title": "Legal Document",
        "parties_involved": [],
        "effective_date": None,
        "core_obligations": [],
        "plain_language_summary": "General legal document outlining obligations and commitments.",
        "plain_language_summary_hi": "यह एक कानूनी दस्तावेज है जो दोनों पक्षों के दायित्वों और शर्तों को निर्धारित करता है।",
        "key_deadlines_or_actions": [],
    }

    llm_data = await _call_llm_json(
        GENERAL_LEGAL_EXTRACTION_SYSTEM,
        GENERAL_LEGAL_EXTRACTION_USER.format(text=text[:3500]),
        api_key=api_key,
        model=model,
    )

    if llm_data and isinstance(llm_data, dict):
        for k in extracted.keys():
            if llm_data.get(k):
                extracted[k] = llm_data[k]

    return extracted
