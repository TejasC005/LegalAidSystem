"""
=============================================================================
LEXIS — Scam Indicator Extractor & Sensitive Data Redactor
=============================================================================
Performs deterministic indicator extraction (URLs, UPI IDs, phone numbers,
payment demands, impersonations, urgency signals, threats, OTP requests)
and redacts sensitive personal credentials (passwords, OTPs, card numbers,
Aadhaar) to ensure clean, privacy-preserving scam intelligence.
"""

import hashlib
import re
from typing import Dict, List, Set, Tuple
from urllib.parse import urlparse

from models.scam_intelligence import ExtractedIndicators

# Common Indian UPI handle suffixes
COMMON_UPI_HANDLES = {
    "upi", "okhdfcbank", "okaxis", "oksbi", "okicici", "paytm", "apl", "ybl",
    "axl", "ibl", "barodampay", "aubank", "federal", "indus", "kotak",
    "postbank", "airtel", "yesbank", "idfcbank", "jupiteraxis", "slice"
}

# Trusted domains that are official reporting channels, NOT scam indicators
TRUSTED_DOMAINS = {
    "cybercrime.gov.in", "rbi.org.in", "npci.org.in", "uidai.gov.in",
    "cbic.gov.in", "incometax.gov.in", "trai.gov.in", "cbi.gov.in",
    "mha.gov.in", "sebi.gov.in"
}

# Impersonation keywords & authority markers
IMPERSONATION_PATTERNS = [
    r"\bcbi\b", r"\bcentral bureau of investigation\b",
    r"\benforcement directorate\b", r"\bed officer\b",
    r"\bdelhi police\b", r"\bmumbai police\b", r"\bstate police\b", r"\bcyber crime cell\b",
    r"\bnarcotics control bureau\b", r"\bncb officer\b",
    r"\bcustoms department\b", r"\bcustoms officer\b",
    r"\breserve bank of india\b", r"\brbi officer\b",
    r"\bincome tax department\b", r"\bit department\b",
    r"\btrai\b", r"\btelecom regulatory\b",
    r"\bsupreme court\b", r"\bhigh court\b", r"\bdistrict magistrate\b",
    r"\bfedex\b", r"\bdhl express\b", r"\bblue dart\b", r"\bindia post\b",
    r"\belectricity (?:department|board|officer)\b", r"\bbank manager\b",
    r"\bcustomer care\b", r"\bsupport team\b",
]

# Urgency keywords
URGENCY_PATTERNS = [
    r"\bimmediately\b", r"\bright now\b", r"\bwithin 24 hours?\b", r"\bwithin \d+ hours?\b",
    r"\bwithin \d+ minutes?\b", r"\burgent\b", r"\bhurry\b", r"\bexpire[sd]? today\b",
    r"\blast chance\b", r"\bbefore 5 ?pm\b", r"\btime-sensitive\b", r"\bdo not disconnect\b",
    r"\bstay on call\b", r"\bat \d{1,2}(?::\d{2})?\s*(?:am|pm)\b", r"\btonight\b",
]

# Threat / Coercion keywords
THREAT_PATTERNS = [
    r"\bdigital arrest\b", r"\bunder arrest\b", r"\barrest warrant\b", r"\bfir filed\b",
    r"\bnon-bailable warrant\b", r"\bjail\b", r"\bimprisonment\b", r"\bfreeze (?:your )?bank account\b",
    r"\baccount (?:is )?frozen\b", r"\bpolice raid\b", r"\blegal action\b", r"\bcourt summons\b",
    r"\bseize assets\b", r"\bpenalty\b", r"\bheavy fine\b", r"\bsuspend sim\b", r"\baadhaar suspended\b",
    r"\b(?:power|electricity|connection|service|water|gas)?\s*(?:will be )?disconnect(?:ed|ion)?\b",
    r"\bcut off\b",
]

# OTP / Credential request patterns
OTP_PATTERNS = [
    r"\bshare (?:the )?otp\b", r"\bsend (?:the )?otp\b", r"\benter (?:the )?otp\b",
    r"\bprovide (?:the )?otp\b", r"\bverification code\b", r"\bsms code\b",
    r"\bone[- ]time password\b", r"\bupi pin\b", r"\batm pin\b", r"\bcvv\b",
]

# Sensitive personal data requests
SENSITIVE_INFO_PATTERNS = [
    r"\baadhaar (?:card|number|copy)\b", r"\bpan card\b", r"\bnetbanking password\b",
    r"\bbank login credentials\b", r"\bdebit card details\b", r"\bcredit card number\b",
    r"\binstall (?:anydesk|teamviewer|rustdesk|quicksupport|apk)\b",
]

# Payment demand keywords
PAYMENT_PATTERNS = [
    r"(?:rs\.?|inr|₹)\s*[\d,]+(?:\.\d+)?",
    r"\btransfer (?:money|funds|amount)\b",
    r"\bpay (?:a )?(?:fine|fee|penalty|deposit|tax|clearance fee)\b",
    r"\badvance fee\b", r"\bsecurity deposit\b", r"\bregistration fee\b",
    r"\bscan (?:this |the )?qr code\b", r"\bpay via upi\b",
    r"\b(?:click |link )?(?:to )?pay\b", r"\bunpaid bill\b", r"\bdue bill\b",
    r"\bpay (?:now|immediately|bill|due|online)\b",
]


class ScamIndicatorEngine:
    """
    Analyzes submitted text or parsed document content to extract scam indicators
    and safely redact sensitive information.
    """

    @staticmethod
    def redact_sensitive_data(text: str) -> str:
        """
        Redacts sensitive credentials, passwords, OTPs, and card numbers.
        """
        if not text:
            return ""

        # Redact credit/debit card numbers (13 to 19 digits with optional hyphens/spaces)
        redacted = re.sub(r"\b(?:\d{4}[ -]?){3}\d{4}\b", "[REDACTED_CARD]", text)

        # Redact Aadhaar numbers (12 digits, often formatted as 4-4-4)
        redacted = re.sub(r"\b\d{4}\s\d{4}\s\d{4}\b", "[REDACTED_AADHAAR]", redacted)

        # Redact OTP & password values directly following credentials/password keywords
        redacted = re.sub(
            r"((?:otp|code|pin|password|passwd|pwd)[:\s=]+)(\S+)",
            r"\1[REDACTED]",
            redacted,
            flags=re.IGNORECASE,
        )

        # Redact standalone 6-digit OTP codes preceded by 'is' or 'code'
        redacted = re.sub(
            r"(?i)\b(is|code|verification is|otp is)\s+(\d{4,8})\b",
            r"\1 [REDACTED_CODE]",
            redacted,
        )

        return redacted

    @classmethod
    def extract_indicators(cls, text: str) -> ExtractedIndicators:
        """
        Extracts structured scam indicators from text.
        """
        if not text:
            return ExtractedIndicators()

        lower_text = text.lower()

        # 1. URLs & Domains
        urls: List[str] = []
        domains: List[str] = []
        raw_urls = re.findall(r"https?://[^\s<>\"'()]+", text)
        for u in raw_urls:
            cleaned_url = u.rstrip(".,;!?)]}")
            parsed = urlparse(cleaned_url)
            domain = (parsed.netloc or "").lower().split(":")[0]
            if domain and domain not in TRUSTED_DOMAINS:
                urls.append(cleaned_url)
                if domain not in domains:
                    domains.append(domain)

        # 2. Indian Phone Numbers (+91 or 10-digit mobile)
        phone_matches = re.findall(
            r"(?:\+91[\-\s]?)?[6-9]\d{4}[\-\s]?\d{5}\b", text
        )
        phones = list({re.sub(r"[\-\s]", "", p) for p in phone_matches})

        # 3. Email Addresses
        raw_emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b", text)
        emails = list({e.lower() for e in raw_emails if not any(t in e.lower() for t in TRUSTED_DOMAINS)})

        # 4. UPI IDs
        raw_upi = re.findall(r"\b[a-zA-Z0-9.\-_]{2,64}@[a-zA-Z]{2,32}\b", text)
        upi_ids = []
        for cand in raw_upi:
            handle = cand.split("@")[-1].lower()
            if handle in COMMON_UPI_HANDLES or any(bank in handle for bank in ["bank", "pay", "axis", "sbi", "hdfc", "icici"]):
                if cand.lower() not in upi_ids:
                    upi_ids.append(cand.lower())

        # 5. Payment demands
        payment_demands = []
        for pat in PAYMENT_PATTERNS:
            found = re.findall(pat, lower_text)
            for item in found:
                item_str = item if isinstance(item, str) else str(item)
                if item_str and item_str not in payment_demands:
                    payment_demands.append(item_str)

        # 6. Impersonation Claims
        impersonation = []
        for pat in IMPERSONATION_PATTERNS:
            found = re.findall(pat, lower_text)
            for item in found:
                clean_item = item.strip()
                if clean_item and clean_item not in impersonation:
                    impersonation.append(clean_item)

        # 7. Urgency Keywords
        urgency = []
        for pat in URGENCY_PATTERNS:
            found = re.findall(pat, lower_text)
            for item in found:
                clean_item = item.strip()
                if clean_item and clean_item not in urgency:
                    urgency.append(clean_item)

        # 8. Threat Keywords
        threats = []
        for pat in THREAT_PATTERNS:
            found = re.findall(pat, lower_text)
            for item in found:
                clean_item = item.strip()
                if clean_item and clean_item not in threats:
                    threats.append(clean_item)

        # 9. OTP Requests
        otp_reqs = []
        for pat in OTP_PATTERNS:
            found = re.findall(pat, lower_text)
            for item in found:
                clean_item = item.strip()
                if clean_item and clean_item not in otp_reqs:
                    otp_reqs.append(clean_item)

        # 10. Sensitive Info Requests
        sensitive_info = []
        for pat in SENSITIVE_INFO_PATTERNS:
            found = re.findall(pat, lower_text)
            for item in found:
                clean_item = item.strip()
                if clean_item and clean_item not in sensitive_info:
                    sensitive_info.append(clean_item)

        # 11. Indicator Hashes (for cross-submission deduplication)
        hashes = []
        all_identifiers = urls + phones + emails + upi_ids
        for ident in all_identifiers:
            norm = ident.strip().lower()
            h = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
            if h not in hashes:
                hashes.append(h)

        return ExtractedIndicators(
            urls=urls,
            domains=domains,
            phone_numbers=phones,
            email_addresses=emails,
            upi_ids=upi_ids,
            payment_demands=payment_demands,
            impersonation_claims=impersonation,
            urgency_keywords=urgency,
            threat_keywords=threats,
            otp_requests=otp_reqs,
            sensitive_info_requests=sensitive_info,
            indicator_hashes=hashes,
        )

    @classmethod
    def calculate_indicator_score(cls, indicators: ExtractedIndicators) -> float:
        """
        Calculates a suspicious indicator score [0.0, 1.0] based on density and
        criticality of extracted signals.
        """
        score = 0.0

        # High-threat signals
        if indicators.threat_keywords:
            score += min(len(indicators.threat_keywords) * 0.25, 0.45)
        if indicators.otp_requests:
            score += min(len(indicators.otp_requests) * 0.30, 0.40)
        if indicators.impersonation_claims:
            score += min(len(indicators.impersonation_claims) * 0.20, 0.35)
        if indicators.payment_demands:
            score += min(len(indicators.payment_demands) * 0.15, 0.30)
        if indicators.urgency_keywords:
            score += min(len(indicators.urgency_keywords) * 0.10, 0.20)
        if indicators.sensitive_info_requests:
            score += min(len(indicators.sensitive_info_requests) * 0.15, 0.25)
        if indicators.upi_ids or indicators.urls:
            score += 0.15

        return min(round(score, 3), 1.0)
