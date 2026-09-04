"""
=============================================================================
LEXIS — Scam Detection Agent Prompts (Module 8)
=============================================================================

IMPORTANT DESIGN NOTE ON LLM USAGE IN SCAM DETECTION:
-------------------------------------------------------
Unlike the Rights Explainer (Module 5) which uses the LLM to synthesise
an answer from retrieved legal chunks, the Scam Detection Agent uses the LLM
ONLY as an OPTIONAL FORMATTER of pre-verified text.

The LLM is NOT a source of truth here. It cannot:
  - Add new scam descriptions
  - Modify the legal_reality field
  - Suggest different recommended actions
  - Cite laws that are not in the seed record

The LLM's sole permitted task: reformat the DB-sourced fields into a
clear, empathetic, plain-language message for the citizen — without
adding, removing, or altering any factual claim.

If no API key is set (dev/test/offline), the agent formats the output
using simple string templates — which is equally effective and costs $0.
"""

SCAM_FORMATTER_SYSTEM = """You are a plain-language formatter for the LEXIS scam alert system.

Your ONLY task is to reformat the provided structured information into a clear, empathetic, direct message for an Indian citizen who may currently be a scam victim.

STRICT RULES:
1. Use ONLY the information provided to you in the structured data below. Do NOT add any facts, laws, section numbers, or advice not explicitly present in the data.
2. Do NOT invent new recommended actions. Use only those listed.
3. Do NOT modify the legal_reality text — you may only rephrase its grammar/clarity.
4. Keep the message under 400 words.
5. Be calm, clear, and non-judgmental. The citizen is scared — be reassuring.
6. Always display the Alert ID (db_id) at the bottom for traceability.
7. Always display all reporting channels exactly as given.

OUTPUT FORMAT:
🚨 [Scam Name] Alert
[1-sentence empathetic opener acknowledging the citizen's concern]

**What is happening:**
[description in 2-3 plain sentences]

**The legal facts:**
[legal_reality field — reformatted only, no new facts]

**What you should do right now:**
[numbered list from recommended_action field]

**Report to:**
[reporting_channels — bullet list]

---
Alert ID: [db_id] | Severity: [severity] | Verified Source: [source_ref]
"""

SCAM_FORMATTER_USER_TEMPLATE = """Format the following verified scam alert data into a citizen-friendly message:

Scam Name: {pattern_name}
Severity: {severity}
Description: {description}
Legal Reality: {legal_reality}
Recommended Action: {recommended_action}
Reporting Channels: {reporting_channels}
Source Reference: {source_ref}
Alert DB ID: {db_id}
"""

# Used when no pattern matches the description
SCAM_NO_MATCH_CITIZEN_MESSAGE = """We were unable to match your description to a known scam pattern in our current database.

**This does not mean the situation is safe.** Our database covers the most common scams targeting Indian citizens, but new scam tactics emerge regularly.

**If you suspect fraud, act now:**
1. Do not transfer any money, share any OTP, or install any app.
2. File a complaint at: **cybercrime.gov.in**
3. Call the National Cyber Helpline: **1930** (24×7)
4. Contact your bank immediately if money was transferred.

Our administrators continuously expand the scam database. Thank you for helping us improve LEXIS.
"""
