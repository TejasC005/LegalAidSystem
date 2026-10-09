"""
=============================================================================
LEXIS Document Drafter — Template & Clause Engine (Module 6)
=============================================================================

This module provides modular, clause-based document assembly for Indian legal documents.
Instead of monolithic static text strings, documents are assembled by composing
reusable clause functions (Header, Subject, Parties, Statement of Facts, Legal Claims/Demands,
Relief/Prayer, Signature, Verification).

SUPPORTED DOCUMENT TYPES:
  1. RTI Application (Right to Information Act, 2005)
  2. Legal Notice (General Legal Demand Notice under Indian Law)
  3. Consumer Complaint (Consumer Protection Act, 2019)

DISCLAIMER / NO HALLUCINATION NOTICE:
Standard Indian legal notice layouts, RTI formatting conventions, and consumer complaint structures
are implemented based on statutory provisions. Fields requiring state-specific compliance or exact fee rules
(e.g., RTI fee amounts which vary by state) are explicitly marked with `[PLACEHOLDER — verify state rules]`.
"""

from typing import Dict, Any, List, TypedDict, Callable


# =============================================================================
# REUSABLE CLAUSE BLOCKS
# =============================================================================

def clause_header(doc_title: str) -> str:
    return f"{doc_title.upper()}\n{'=' * len(doc_title)}"


def clause_date_location(city: str, date_str: str) -> str:
    return f"Place: {city}\nDate: {date_str}"


def clause_recipient_address(recipient_name: str, designation: str, address: str) -> str:
    res = "TO,\n"
    if designation:
        res += f"{designation.upper()},\n"
    if recipient_name:
        res += f"{recipient_name},\n"
    res += f"{address}"
    return res


def clause_sender_details(sender_name: str, phone: str, email: str, address: str) -> str:
    return (
        f"FROM:\n"
        f"{sender_name}\n"
        f"Address: {address}\n"
        f"Contact: {phone} | Email: {email}"
    )


def clause_subject(subject_text: str) -> str:
    return f"SUBJECT: {subject_text.strip()}"


def clause_salutation(salutation: str = "Sir/Madam") -> str:
    return f"Respected {salutation},"


def clause_facts(facts_summary: str) -> str:
    return (
        "STATEMENT OF FACTS:\n"
        "-------------------\n"
        f"{facts_summary.strip()}"
    )


def clause_legal_notice_demand(demands: str, notice_period_days: int = 15) -> str:
    return (
        f"DEMAND & NOTICE PERIOD:\n"
        f"-----------------------\n"
        f"You are hereby called upon to comply with the following demand(s) within a period of {notice_period_days} days "
        f"from the receipt of this legal notice:\n\n"
        f"{demands.strip()}\n\n"
        f"Failing which, my client / the undersigned shall be constrained to initiate appropriate legal proceedings "
        f"against you in a court of competent jurisdiction at your sole risk, cost, and consequence."
    )


def clause_rti_information_requested(particulars: str) -> str:
    return (
        "PARTICULARS OF INFORMATION SOUGHT UNDER SECTION 6(1) OF RTI ACT 2005:\n"
        "----------------------------------------------------------------------\n"
        f"{particulars.strip()}\n\n"
        "[PLACEHOLDER — verify state-specific RTI application fee: Central Govt is Rs. 10 via IPO/DD/Court Fee Stamp]"
    )


def clause_consumer_complaint_relief(relief_claimed: str, compensation_amount: str) -> str:
    return (
        "PRAYER / RELIEF CLAIMED UNDER CONSUMER PROTECTION ACT 2019:\n"
        "------------------------------------------------------------\n"
        "It is most respectfully prayed that this Hon'ble Commission may be pleased to:\n"
        f"1. Direct the Opposite Party to: {relief_claimed.strip()}\n"
        f"2. Direct the Opposite Party to pay a sum of Rs. {compensation_amount} as compensation for mental agony, harassment, and legal costs.\n"
        f"3. Pass any other order(s) as this Hon'ble Commission deems fit."
    )


def clause_signature(sender_name: str, advocate_name: str = "") -> str:
    sig = "\nYours faithfully,\n\n\n"
    if advocate_name:
        sig += f"({advocate_name}, Advocate)\nOn behalf of: {sender_name}"
    else:
        sig += f"({sender_name})"
    return sig


# =============================================================================
# DOCUMENT ASSEMBLY FUNCTIONS
# =============================================================================

def assemble_rti_application(answers: Dict[str, Any]) -> str:
    """
    Assembles an RTI Application (Right to Information Act, 2005).
    Required answers: applicant_name, applicant_address, applicant_contact,
                      pio_designation, public_authority_name, office_address,
                      city, date, information_sought
    """
    header = clause_header("APPLICATION UNDER SECTION 6(1) OF THE RIGHT TO INFORMATION ACT, 2005")

    date_loc = clause_date_location(
        city=answers.get("city", "[City]"),
        date_str=answers.get("date", "[Date]")
    )

    recipient = clause_recipient_address(
        recipient_name="",
        designation=f"The Public Information Officer (PIO) / {answers.get('pio_designation', 'PIO')}",
        address=f"{answers.get('public_authority_name', '[Public Authority]')}\n{answers.get('office_address', '[Office Address]')}"
    )

    sender = clause_sender_details(
        sender_name=answers.get("applicant_name", "[Applicant Name]"),
        phone=answers.get("applicant_contact", "[Phone]"),
        email=answers.get("applicant_email", "N/A"),
        address=answers.get("applicant_address", "[Applicant Address]")
    )

    subject = clause_subject(f"Seeking Information under RTI Act 2005 regarding {answers.get('subject_brief', 'public matter')}")

    salutation = clause_salutation()

    info_clause = clause_rti_information_requested(answers.get("information_sought", "[Details of information required]"))

    fee_clause = (
        "FEE DETAILS:\n"
        "An RTI Application fee of Rs. 10/- is attached herewith via Demand Draft / Postal Order / Cash Receipt.\n"
        "I am a citizen of India."
    )

    sig = clause_signature(answers.get("applicant_name", "[Applicant Name]"))

    sections = [header, date_loc, "\n" + recipient, "\n" + sender, "\n" + subject, "\n" + salutation, "\n" + info_clause, "\n" + fee_clause, sig]
    return "\n\n".join(sections)


def assemble_legal_notice(answers: Dict[str, Any]) -> str:
    """
    Assembles a Legal Notice (e.g. landlord deposit refund, breach of contract, unpaid dues).
    Required answers: sender_name, sender_address, sender_contact,
                      opposite_party_name, opposite_party_address,
                      city, date, grievance_facts, demand_details, notice_period_days
    """
    header = clause_header("LEGAL NOTICE")

    date_loc = clause_date_location(
        city=answers.get("city", "[City]"),
        date_str=answers.get("date", "[Date]")
    )

    recipient = clause_recipient_address(
        recipient_name=answers.get("opposite_party_name", "[Opposite Party Name]"),
        designation=answers.get("opposite_party_designation", ""),
        address=answers.get("opposite_party_address", "[Opposite Party Address]")
    )

    sender = clause_sender_details(
        sender_name=answers.get("sender_name", "[Sender Name]"),
        phone=answers.get("sender_contact", "[Phone]"),
        email=answers.get("sender_email", "N/A"),
        address=answers.get("sender_address", "[Sender Address]")
    )

    subject = clause_subject(f"Legal Notice regarding {answers.get('subject_summary', 'Grievance and Demand for Redressal')}")

    salutation = clause_salutation("Sir/Madam")

    facts = clause_facts(answers.get("grievance_facts", "[Detailed statement of facts]"))

    demand = clause_legal_notice_demand(
        demands=answers.get("demand_details", "[Specific demands, e.g. refund amount, action]"),
        notice_period_days=int(answers.get("notice_period_days", 15))
    )

    sig = clause_signature(answers.get("sender_name", "[Sender Name]"))

    sections = [header, date_loc, "\n" + recipient, "\n" + sender, "\n" + subject, "\n" + salutation, "\n" + facts, "\n" + demand, sig]
    return "\n\n".join(sections)


def assemble_consumer_complaint(answers: Dict[str, Any]) -> str:
    """
    Assembles a Consumer Complaint draft for submission to the District Consumer Disputes Redressal Commission.
    Required answers: complainant_name, complainant_address, complainant_contact,
                      opposite_party_name, opposite_party_address,
                      forum_city, date, transaction_details, deficiency_alleged, relief_claimed, compensation_amount
    """
    header = clause_header("BEFORE THE DISTRICT CONSUMER DISPUTES REDRESSAL COMMISSION")

    jurisdiction = f"AT {answers.get('forum_city', '[District/City]').upper()}\n"

    parties = (
        f"COMPLAINANT:\n"
        f"{answers.get('complainant_name', '[Complainant Name]')}, S/D/W of [Parent/Spouse Name]\n"
        f"R/o {answers.get('complainant_address', '[Address]')}\n"
        f"Contact: {answers.get('complainant_contact', '[Contact]')}\n\n"
        f"VERSUS\n\n"
        f"OPPOSITE PARTY:\n"
        f"{answers.get('opposite_party_name', '[Opposite Party Name]')}\n"
        f"Address: {answers.get('opposite_party_address', '[Address]')}"
    )

    subject = clause_subject("COMPLAINT UNDER SECTION 35 OF THE CONSUMER PROTECTION ACT, 2019 FOR DEFICIENCY IN SERVICE / UNFAIR TRADE PRACTICE")

    facts = clause_facts(
        f"1. Transaction Details: {answers.get('transaction_details', '[Product/Service purchase details, price paid, date]')}\n\n"
        f"2. Deficiency / Defect Alleged: {answers.get('deficiency_alleged', '[Details of defect, failure to fulfill obligation, unreturned money]')}\n\n"
        f"3. Jurisdiction: The cause of action arose within the territorial jurisdiction of this Hon'ble Commission."
    )

    prayer = clause_consumer_complaint_relief(
        relief_claimed=answers.get("relief_claimed", "[Replacement / Refund / Service repair]"),
        compensation_amount=str(answers.get("compensation_amount", "50000"))
    )

    verification = (
        "VERIFICATION:\n"
        f"I, {answers.get('complainant_name', '[Complainant Name]')}, do hereby verify that the contents of paragraphs 1 to 3 "
        "above are true and correct to the best of my knowledge and belief, and nothing material has been concealed therefrom.\n"
        f"Verified at {answers.get('forum_city', '[City]')} on this {answers.get('date', '[Date]')}.\n"
    )

    sig = clause_signature(answers.get("complainant_name", "[Complainant Name]"))

    sections = [header, jurisdiction, "\n" + parties, "\n" + subject, "\n" + facts, "\n" + prayer, "\n" + verification, sig]
    return "\n\n".join(sections)


class TemplateQuestion(TypedDict):
    key: str
    question: str
    type: str


class TemplateConfig(TypedDict):
    name: str
    description: str
    assembler: Callable[[Dict[str, Any]], str]
    questions: List[TemplateQuestion]


# Registry of templates
TEMPLATES: Dict[str, TemplateConfig] = {
    "rti_application": {
        "name": "RTI Application",
        "description": "Application under Section 6(1) of Right to Information Act, 2005",
        "assembler": assemble_rti_application,
        "questions": [
            {"key": "applicant_name", "question": "What is your full name?", "type": "text"},
            {"key": "applicant_address", "question": "What is your complete postal address (including pincode)?", "type": "text"},
            {"key": "applicant_contact", "question": "What is your phone number and email address?", "type": "text"},
            {"key": "public_authority_name", "question": "Which Government Department / Public Authority are you seeking information from?", "type": "text"},
            {"key": "information_sought", "question": "Please describe clearly the exact information or documents you want from the department.", "type": "text"},
            {"key": "city", "question": "Which city/town are you filing this application from?", "type": "text"}
        ]
    },
    "legal_notice": {
        "name": "Legal Notice",
        "description": "Formal legal demand notice (e.g., landlord deposit refund, breach of agreement)",
        "assembler": assemble_legal_notice,
        "questions": [
            {"key": "sender_name", "question": "What is your full name?", "type": "text"},
            {"key": "sender_address", "question": "What is your current address?", "type": "text"},
            {"key": "opposite_party_name", "question": "Who are you sending this notice to (Person / Company / Landlord name)?", "type": "text"},
            {"key": "opposite_party_address", "question": "What is the opposite party's address?", "type": "text"},
            {"key": "grievance_facts", "question": "Describe your grievance in brief (e.g. 'Landlord won't return my deposit of Rs 40,000 despite lease ending on June 30').", "type": "text"},
            {"key": "demand_details", "question": "What exact action or payment are you demanding, and within how many days (e.g. 'Refund Rs 40,000 within 15 days')?", "type": "text"}
        ]
    },
    "consumer_complaint": {
        "name": "Consumer Complaint",
        "description": "Complaint draft under Consumer Protection Act 2019 for District Commission",
        "assembler": assemble_consumer_complaint,
        "questions": [
            {"key": "complainant_name", "question": "What is your full name?", "type": "text"},
            {"key": "complainant_address", "question": "What is your complete address and contact details?", "type": "text"},
            {"key": "opposite_party_name", "question": "What is the name of the company / seller / service provider you are complaining against?", "type": "text"},
            {"key": "transaction_details", "question": "What product/service did you purchase, on what date, and how much did you pay?", "type": "text"},
            {"key": "deficiency_alleged", "question": "What was the defect, deficiency in service, or unfair practice you experienced?", "type": "text"},
            {"key": "relief_claimed", "question": "What relief do you want (e.g., full refund of Rs. X, plus compensation amount for harassment)?", "type": "text"}
        ]
    }
}
