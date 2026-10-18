"""
=============================================================================
LEXIS Filing Guide — Authority Catalog & Rule Engine (Module 9)
=============================================================================

Provides structured access to verified Indian filing authorities, pecuniary
jurisdiction calculations, category inference, and requirement checklists.

GROUNDING DIRECTIVE:
All catalog data is grounded strictly in authentic Indian statutory frameworks:
  - Right to Information Act, 2005 (Act 22 of 2005)
  - Consumer Protection Act, 2019 (Act 35 of 2019)
  - Code of Civil Procedure, 1908 & Transfer of Property Act, 1882
  - Negotiable Instruments Act, 1881 (Sec 138)
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Path to the authoritative seed dataset
SEED_FILE = Path(__file__).parent.parent.parent / "data" / "filing_authorities" / "filing_seed.json"

# List of all Indian States and Union Territories for jurisdiction detection
INDIAN_STATES_AND_UTS = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Chandigarh", "Puducherry",
    "Andaman and Nicobar Islands", "Dadra and Nagar Haveli and Daman and Diu", "Lakshadweep"
]

MAJOR_CITY_TO_STATE = {
    "mumbai": "Maharashtra",
    "navi mumbai": "Maharashtra",
    "pune": "Maharashtra",
    "nagpur": "Maharashtra",
    "thane": "Maharashtra",
    "nashik": "Maharashtra",
    "aurangabad": "Maharashtra",
    "solapur": "Maharashtra",
    "bengaluru": "Karnataka",
    "bangalore": "Karnataka",
    "mysore": "Karnataka",
    "chennai": "Tamil Nadu",
    "coimbatore": "Tamil Nadu",
    "madurai": "Tamil Nadu",
    "trichy": "Tamil Nadu",
    "salem": "Tamil Nadu",
    "kolkata": "West Bengal",
    "hyderabad": "Telangana",
    "ahmedabad": "Gujarat",
    "surat": "Gujarat",
    "vadodara": "Gujarat",
    "rajkot": "Gujarat",
    "jaipur": "Rajasthan",
    "jodhpur": "Rajasthan",
    "lucknow": "Uttar Pradesh",
    "kanpur": "Uttar Pradesh",
    "varanasi": "Uttar Pradesh",
    "noida": "Uttar Pradesh",
    "ghaziabad": "Uttar Pradesh",
    "agra": "Uttar Pradesh",
    "meerut": "Uttar Pradesh",
    "prayagraj": "Uttar Pradesh",
    "allahabad": "Uttar Pradesh",
    "patna": "Bihar",
    "bhopal": "Madhya Pradesh",
    "indore": "Madhya Pradesh",
    "chandigarh": "Chandigarh",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "gurgaon": "Haryana",
    "gurugram": "Haryana",
    "faridabad": "Haryana",
    "ludhiana": "Punjab",
    "amritsar": "Punjab",
    "jalandhar": "Punjab",
    "kochi": "Kerala",
    "thiruvananthapuram": "Kerala",
    "kozhikode": "Kerala",
    "calicut": "Kerala",
    "bhubaneswar": "Odisha",
    "ranchi": "Jharkhand",
    "guwahati": "Assam",
    "dehradun": "Uttarakhand",
    "visakhapatnam": "Andhra Pradesh",
    "vizag": "Andhra Pradesh",
    "vijayawada": "Andhra Pradesh",
    "guntur": "Andhra Pradesh",
    "raipur": "Chhattisgarh",
    "bilaspur": "Chhattisgarh",
    "shimla": "Himachal Pradesh",
    "srinagar": "Jammu and Kashmir",
    "jammu": "Jammu and Kashmir",
}


class FilingCatalog:
    """
    In-memory catalog and rule engine for verified Indian filing procedures.
    Operates offline without requiring external network access or LLMs.
    """

    def __init__(self, seed_file: Optional[Path] = None):
        self.seed_file = seed_file or SEED_FILE
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load_catalog()

    def _load_catalog(self):
        """Loads verified records from the seed file."""
        if not self.seed_file.exists():
            logger.error("Filing seed file does not exist at %s", self.seed_file)
            return

        try:
            with open(self.seed_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    doc_type = item.get("doc_type")
                    if doc_type:
                        self._records[doc_type] = item
            logger.info("FilingCatalog loaded %d verified authorities", len(self._records))
        except Exception as exc:
            logger.error("Failed to parse filing seed file: %s", exc)

    def get_all_authorities(self) -> List[Dict[str, Any]]:
        """Returns all authority records."""
        return list(self._records.values())

    def get_by_doc_type(self, doc_type: str) -> Optional[Dict[str, Any]]:
        """Retrieves verified authority record by exact doc_type."""
        if not doc_type:
            return None
        return self._records.get(doc_type.strip().lower())

    def infer_doc_type(self, text: str) -> Optional[str]:
        """Infers document / complaint type from natural language query."""
        q = text.lower()

        # 1. RTI Application
        rti_keywords = [
            "rti", "right to information", "pio", "cpio", "first appeal",
            "information officer", "public authority", "government record",
            "tender details", "marksheet verification", "pension delay", "road work details",
            "public information", "govt record", "examination answer sheet", "answer key",
            "tender copy", "municipal records", "public grievance", "information commissioner",
            "rti appeal", "public records", "file rti"
        ]
        if any(kw in q for kw in rti_keywords):
            return "rti_application"

        # 2. Consumer Complaint
        consumer_keywords = [
            "consumer", "defective", "deficiency", "warranty", "refund",
            "flipkart", "amazon", "e-commerce", "faulty product", "repair refusal",
            "consumer court", "dcdrc", "scdrc", "ncdrc", "edaakhil", "daakhil",
            "airline refund", "damaged goods", "bad service", "hospital negligence",
            "medical negligence", "doctor negligence", "electricity", "discom", "power cut",
            "power supply", "meter fault", "broadband", "telecom", "mobile recharge",
            "insurance claim", "claim rejected", "builder", "flat", "possession",
            "real estate", "amenities", "bank charges", "unauthorized debit",
            "unauthorized deduction", "overcharging", "flight refund", "flight cancellation",
            "cancelled flight", "train ticket refund", "irctc refund", "adulterated",
            "expired product", "food safety", "bad food", "courier delay", "lost parcel",
            "missing package"
        ]
        if any(kw in q for kw in consumer_keywords):
            return "consumer_complaint"

        # 3. Legal Demand Notice
        legal_notice_keywords = [
            "legal notice", "demand notice", "deposit", "landlord", "tenant",
            "eviction", "rent dispute", "cheque bounce", "section 138", "unpaid dues",
            "breach of contract", "salary dues", "unpaid salary", "builder delay", "rpad",
            "speed post", "promissory note", "recovery of money", "breach of agreement",
            "default in payment", "dues recovery", "dishonour of cheque", "dishonored cheque",
            "dishonour", "dishonored", "money recovery", "loan recovery", "outstanding payment",
            "security deposit", "statutory notice"
        ]
        if any(kw in q for kw in legal_notice_keywords):
            return "legal_notice"

        return None

    def calculate_consumer_pecuniary_tier(self, amount_inr: float) -> Dict[str, Any]:
        """
        Calculates Consumer Commission pecuniary jurisdiction under Consumer Protection Act 2019:
          - Up to ₹50 Lakh (₹5,000,000) -> District Consumer Disputes Redressal Commission (DCDRC)
          - Above ₹50 Lakh up to ₹2 Crore (₹20,000,000) -> State Consumer Disputes Redressal Commission (SCDRC)
          - Above ₹2 Crore -> National Consumer Disputes Redressal Commission (NCDRC)
        """
        if amount_inr <= 5_000_000:
            return {
                "tier_name": "District Consumer Disputes Redressal Commission (DCDRC)",
                "short_name": "District Commission",
                "jurisdiction_limit": "Value of goods/services paid up to ₹50 Lakh",
                "where_to_file": "District Commission having territorial jurisdiction where the complainant resides, works, or where opposite party operates.",
                "portal": "https://edaakhil.nic.in",
                "statutory_ref": "Section 34, Consumer Protection Act 2019",
            }
        elif amount_inr <= 20_000_000:
            return {
                "tier_name": "State Consumer Disputes Redressal Commission (SCDRC)",
                "short_name": "State Commission",
                "jurisdiction_limit": "Value of goods/services paid between ₹50 Lakh and ₹2 Crore",
                "where_to_file": "State Consumer Commission located in the capital of your State / Union Territory.",
                "portal": "https://edaakhil.nic.in",
                "statutory_ref": "Section 47, Consumer Protection Act 2019",
            }
        else:
            return {
                "tier_name": "National Consumer Disputes Redressal Commission (NCDRC)",
                "short_name": "National Commission",
                "jurisdiction_limit": "Value of goods/services paid exceeding ₹2 Crore",
                "where_to_file": "NCDRC, Upbhokta Nyay Bhawan, F-Block, GPO Complex, INA, New Delhi — 110 023 (or online via e-Daakhil).",
                "portal": "https://edaakhil.nic.in",
                "statutory_ref": "Section 58, Consumer Protection Act 2019",
            }

    def extract_monetary_amount(self, text: str) -> Optional[float]:
        """
        Extracts monetary amounts from strings such as:
          - "₹50,000", "50000", "Rs. 25,000", "1.5 crore", "75 lakhs", "10 lakh", "45000 rs"
        """
        cleaned = text.replace(",", "").lower()

        # Check for Crore (e.g. 2.5 crore, 1 crore)
        crore_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:cr|crore|crores)', cleaned)
        if crore_match:
            try:
                return float(crore_match.group(1)) * 10_000_000.0
            except ValueError:
                pass

        # Check for Lakh (e.g. 50 lakh, 15 lakhs, 10 lac)
        lakh_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs)', cleaned)
        if lakh_match:
            try:
                return float(lakh_match.group(1)) * 100_000.0
            except ValueError:
                pass

        # Check for numeric amounts with currency symbol or prefix (e.g. ₹50000, Rs 50000)
        currency_match = re.search(r'(?:₹|rs\.?|inr)\s*(\d+(?:\.\d+)?)', cleaned)
        if currency_match:
            try:
                return float(currency_match.group(1))
            except ValueError:
                pass

        # Check for numeric amounts with currency suffix (e.g. 50000 rs, 45000 rupees, 500 inr)
        currency_suffix_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:rs\.?|rupees|inr)\b', cleaned)
        if currency_suffix_match:
            try:
                return float(currency_suffix_match.group(1))
            except ValueError:
                pass

        # Generic number standalone (e.g. "claim is 75000")
        num_match = re.search(r'\b(\d{4,9})\b', cleaned)
        if num_match:
            try:
                return float(num_match.group(1))
            except ValueError:
                pass

        return None

    def extract_jurisdiction_state(self, text: str) -> Optional[str]:
        """Extracts Indian State or UT name from text (including major cities)."""
        lower_text = text.lower()
        for state in INDIAN_STATES_AND_UTS:
            if re.search(rf'\b{re.escape(state.lower())}\b', lower_text):
                return state

        for city, mapped_state in MAJOR_CITY_TO_STATE.items():
            if re.search(rf'\b{re.escape(city)}\b', lower_text):
                return mapped_state

        return None

    def detect_missing_information(self, query: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> List[str]:
        """
        Checks if the user's inquiry has sufficient detail to produce an accurate filing guide.
        Returns a list of missing parameters: ['dispute_category', 'claim_amount', 'state_jurisdiction']
        """
        q = query.strip()
        all_text = q
        if conversation_history:
            turns = [m.get("content", "") or m.get("text", "") for m in conversation_history]
            all_text = " ".join(turns) + " " + q

        missing = []

        # Check if vague
        vague_phrases = [
            "i want to file a case", "file a complaint", "how to file", "file case",
            "someone cheated me", "need legal help", "where to complain", "file fir",
            "guide me to file", "court case", "legal action"
        ]
        q_lower = q.lower()
        is_strictly_vague = any(q_lower == phrase for phrase in vague_phrases) or len(q.split()) <= 4

        inferred = self.infer_doc_type(all_text)
        if not inferred:
            missing.append("dispute_category")

        # For consumer complaints, claim amount determines which Commission has pecuniary jurisdiction
        if inferred == "consumer_complaint" and not self.extract_monetary_amount(all_text):
            missing.append("claim_amount")

        # State jurisdiction affects fee schedules and local portals
        if not self.extract_jurisdiction_state(all_text):
            missing.append("state_jurisdiction")

        return missing


# Global singleton instance
_catalog_instance: Optional[FilingCatalog] = None

def get_filing_catalog() -> FilingCatalog:
    """Returns singleton instance of FilingCatalog."""
    global _catalog_instance
    if _catalog_instance is None:
        _catalog_instance = FilingCatalog()
    return _catalog_instance
