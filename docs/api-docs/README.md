# LEXIS API Reference

> **Version:** 1.1.0 · **Base URL:** `http://localhost:8000` (local dev) · **Last updated:** 2026-08-26

LEXIS exposes a versioned REST API under `/api/v1`. All endpoints accept and return JSON unless otherwise noted. Authentication uses JWT Bearer tokens issued by the Auth module.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Authentication](#authentication)
- [Error Handling](#error-handling)
- [Rate Limiting](#rate-limiting)
- [Endpoints by Module](#endpoints-by-module)
  - [Module 1 — Health](#module-1--health)
  - [Module 2 — Authentication & RBAC](#module-2--authentication--rbac)
  - [Module 4 — Orchestrator (Query)](#module-4--orchestrator-query)
  - [Module 6 — Document Drafter](#module-6--document-drafter)
  - [Module 7 — Document Analyzer](#module-7--document-analyzer)
  - [Module 8 — Scam Detection](#module-8--scam-detection)
  - [Module 9 — Complaint Filing Guide](#module-9--complaint-filing-guide)
  - [Module 10 — Vault & Deadlines](#module-10--vault--deadlines)
- [Common Types](#common-types)
- [Interactive Documentation](#interactive-documentation)

---

## Quick Start

```bash
# 1. Start the backend (from /backend)
uvicorn main:app --reload

# 2. Send OTP and log in
curl -X POST http://localhost:8000/api/v1/auth/send-otp \
  -H "Content-Type: application/json" \
  -d '{"phone": "+919876543210"}'

# 3. Verify OTP (OTP printed in dev console)
curl -X POST http://localhost:8000/api/v1/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"phone": "+919876543210", "otp": "123456"}'
# → returns { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }

# 4. Use the access_token in subsequent requests
curl -H "Authorization: Bearer <access_token>" \
  http://localhost:8000/api/v1/auth/me
```

---

## Authentication

All endpoints (except `/health` variants) require a valid JWT Bearer token in the `Authorization` header.

```
Authorization: Bearer <access_token>
```

| Token type | Lifetime | Issued by |
|---|---|---|
| `access_token` | 15 minutes | `POST /api/v1/auth/verify-otp` |
| `refresh_token` | 7 days | `POST /api/v1/auth/verify-otp` |
| `anonymous_token` | 15 minutes | `POST /api/v1/auth/anonymous` |

### Role hierarchy

| Role | Capabilities |
|---|---|
| `user` | All 6 feature agents, own history, anonymous mode |
| `admin` | All `user` capabilities + analytics, user management (Module 12) |
| `lawyer` | Scaffolded — functional in Module 13 |
| `anonymous` | Feature agents only — no history, no Vault |

---

## Error Handling

All errors return a JSON body:

```json
{
  "detail": "Human-readable error description"
}
```

| HTTP Code | Meaning |
|---|---|
| `400 Bad Request` | Invalid input (validation failure, bad file type, etc.) |
| `401 Unauthorized` | Missing or expired JWT token |
| `403 Forbidden` | Authenticated but wrong role |
| `404 Not Found` | Resource not found (or intentionally hidden for security) |
| `422 Unprocessable Entity` | Pydantic request schema validation failure |
| `429 Too Many Requests` | Rate limit exceeded. Response includes `Retry-After` header |
| `500 Internal Server Error` | Unexpected server error — retry or contact support |

---

## Rate Limiting

OTP issuance is rate-limited per phone number:

| Limit | Window | Behaviour on breach |
|---|---|---|
| 3 OTP requests | 60 seconds | HTTP 429 + `Retry-After` header |

General API rate limiting is handled at the infrastructure layer (Module 14).

---

## Endpoints by Module

---

### Module 1 — Health

Health check endpoints for liveness and readiness probes. These endpoints do **not** require authentication.

---

#### `GET /api/v1/health`

Liveness probe. Returns immediately without touching any external service.

**Response `200 OK`**
```json
{
  "status": "ok",
  "service": "LEXIS API",
  "version": "1.0.0",
  "environment": "development"
}
```

---

#### `GET /api/v1/health/db`

Readiness probe. Pings MongoDB and Redis and reports per-service status.

**Response `200 OK` — all services healthy**
```json
{
  "status": "ok",
  "mongodb": { "status": "ok", "message": "Ping successful" },
  "redis":   { "status": "ok", "message": "Ping successful" }
}
```

**Response `200 OK` — partial failure** *(individual service degraded)*
```json
{
  "status": "degraded",
  "mongodb": { "status": "ok", "message": "Ping successful" },
  "redis":   { "status": "error", "message": "Connection refused" }
}
```

---

### Module 2 — Authentication & RBAC

OTP-based phone authentication with JWT access + refresh tokens. SMS is handled by an abstract provider — in development, OTPs are printed to the server console.

---

#### `POST /api/v1/auth/send-otp`

Request a one-time password for the given phone number.

**Request body**
```json
{ "phone": "+919876543210" }
```

| Field | Type | Rules |
|---|---|---|
| `phone` | `string` | E.164 format, required |

**Response `200 OK`**
```json
{ "message": "OTP sent to +919876543210" }
```

**Response `429 Too Many Requests`** — rate limit hit
```json
{ "detail": "Too many OTP requests. Retry after 60 seconds." }
```

> **Development note:** In `ENVIRONMENT=development`, the OTP is logged to the server console instead of being sent via SMS. Look for a line like `"message": "OTP for +91... is 123456"` in the uvicorn terminal.

---

#### `POST /api/v1/auth/verify-otp`

Verify the OTP and receive JWT tokens.

**Request body**
```json
{
  "phone": "+919876543210",
  "otp": "123456"
}
```

**Response `200 OK`**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Response `401 Unauthorized`** — wrong OTP
```json
{ "detail": "Invalid OTP" }
```

---

#### `POST /api/v1/auth/refresh`

Exchange a valid refresh token for a new access token.

**Request body**
```json
{ "refresh_token": "<refresh_token>" }
```

**Response `200 OK`**
```json
{ "access_token": "...", "token_type": "bearer" }
```

---

#### `POST /api/v1/auth/anonymous`

Issue a signed anonymous session JWT. No phone number required. Expires with the access token (15 minutes). Vault and history require a real account.

**Request body** — empty `{}`

**Response `200 OK`**
```json
{
  "access_token": "...",
  "token_type": "bearer",
  "session_id": "uuid4-string"
}
```

---

#### `GET /api/v1/auth/me` 🔒

Return the authenticated user's profile.

**Response `200 OK`**
```json
{
  "sub": "user_mongo_id",
  "phone": "+919876543210",
  "role": "user",
  "created_at": "2026-08-19T14:31:00Z"
}
```

---

### Module 4 — Orchestrator (Query)

The central entry point for all natural-language queries. The Orchestrator classifies the query into one or more intents, fans out to specialist agents in parallel, and returns a compiled response.

---

#### `POST /api/v1/query` 🔒

Submit a natural-language legal query. The orchestrator automatically routes it to the appropriate specialist agent(s).

**Request body**
```json
{
  "query": "My landlord is refusing to return my security deposit. What are my rights and how do I file a complaint?"
}
```

| Field | Type | Rules |
|---|---|---|
| `query` | `string` | 1–2000 characters, required |

**Response `200 OK`**
```json
{
  "status": "ok",
  "intents": ["rights", "filing"],
  "final_response": "Based on Indian tenancy law...\n\n---\n\nTo file a complaint...",
  "scratchpad": [
    {
      "intent": "rights",
      "status": "ok",
      "output": "Based on Indian tenancy law...",
      "metadata": { "agent": "RightsExplainerAgent", "citations": ["..."], "latency_ms": 420 }
    },
    {
      "intent": "filing",
      "status": "ok",
      "output": "To file a complaint...",
      "metadata": { "agent": "placeholder_filing", "latency_ms": 11 }
    }
  ],
  "llm_calls_used": 1
}
```

**Status values**

| Value | Meaning |
|---|---|
| `ok` | All dispatched agents succeeded |
| `partial` | Some agents succeeded, others failed or timed out |
| `unclear` | No intent was confidently detected |
| `error` | All agents failed |

**Supported intents** (detected automatically)

| Intent | Routed to |
|---|---|
| `rights` | Rights Explainer Agent (Module 5) — RAG via Qdrant + BGE-M3 |
| `draft` | Document Drafter Agent (Module 6) — Template Clause Engine |
| `analyze` | Document Analyzer Agent (Module 7) — text-only path |
| `scam` | Scam Detection Agent (Module 8) — DB-grounded alert |
| `filing` | Filing Guide Agent (Module 9) — exact-match authority lookup |
| `vault` | Vault & Deadline Agent (Module 10) — Placeholder |

> **Prompt injection guard:** Queries containing SQL/script injection patterns are rejected with `400 Bad Request`.

---

### Module 6 — Document Drafter

Multi-turn conversational document drafting. Generates RTI Applications, Legal Demand Notices, and Consumer Complaints using a Clause Template Engine. Documents are exportable as PDF or DOCX.

---

#### `POST /api/v1/drafts/session` 🔒

Start a new document drafting session.

**Request body**
```json
{ "document_type": "rti_application" }
```

| `document_type` value | Document |
|---|---|
| `rti_application` | RTI Application under RTI Act 2005 |
| `legal_notice` | Legal Demand Notice |
| `consumer_complaint` | Consumer Complaint under CPA 2019 |

**Response `200 OK`**
```json
{
  "session_id": "uuid4-string",
  "document_type": "rti_application",
  "status": "in_progress",
  "current_question": "What is the name of the Public Authority you are addressing?",
  "questions_remaining": 5
}
```

---

#### `POST /api/v1/drafts/session/{session_id}/answer` 🔒

Submit an answer to the current question in the drafting session.

**Request body**
```json
{ "answer": "Ministry of Railways, New Delhi" }
```

**Response `200 OK` — more questions**
```json
{
  "session_id": "uuid4-string",
  "status": "in_progress",
  "current_question": "Describe the specific information you are requesting...",
  "questions_remaining": 4
}
```

**Response `200 OK` — session complete**
```json
{
  "session_id": "uuid4-string",
  "status": "completed",
  "draft_preview": "APPLICATION UNDER THE RIGHT TO INFORMATION ACT, 2005\n\nTo,\nThe Public Information Officer...",
  "download_available": true
}
```

---

#### `GET /api/v1/drafts/{draft_id}/download/{format}` 🔒

Download the completed draft as PDF or DOCX.

| Parameter | Values |
|---|---|
| `format` | `pdf` or `docx` |

**Response `200 OK`** — binary file stream with appropriate `Content-Type` header.

> **Access control:** Only the owning user can download their own drafts. Other users receive `404 Not Found`.

---

#### `GET /api/v1/drafts` 🔒

List all draft sessions for the current user.

**Response `200 OK`**
```json
{
  "drafts": [
    {
      "draft_id": "uuid4-string",
      "document_type": "rti_application",
      "status": "completed",
      "created_at": "2026-08-20T17:10:00Z"
    }
  ]
}
```

---

### Module 7 — Document Analyzer

Upload a legal document (PDF, JPEG, PNG) for OCR extraction and AI-powered clause risk analysis. Clauses are classified as 🟢 GREEN (safe), 🟡 YELLOW (review needed), or 🔴 RED (high risk), with plain-language Hindi+English rewrites.

---

#### `POST /api/v1/analysis/upload` 🔒

Upload a document for analysis.

**Request** — `multipart/form-data`

| Field | Type | Rules |
|---|---|---|
| `file` | `File` | PDF, JPEG, or PNG · max 10 MB |

**Validation steps (before processing):**
1. File size check (max `UPLOAD_MAX_SIZE_MB` MB)
2. MIME type allowlist (PDF, JPEG, PNG)
3. Magic-byte content verification (prevents extension spoofing)

**Response `200 OK`**
```json
{
  "analysis_id": "uuid4-string",
  "status": "completed",
  "filename": "rental_agreement.pdf",
  "total_clauses": 12,
  "risk_summary": { "green": 7, "yellow": 3, "red": 2 },
  "clauses": [
    {
      "clause_text": "The landlord may terminate this agreement with 24 hours notice...",
      "risk_level": "RED",
      "risk_reason": "Unilateral termination clause — extremely short notice period",
      "plain_english": "The landlord can throw you out with just 1 day's warning — this is very unfair.",
      "hindi_rewrite": "मकान मालिक सिर्फ 24 घंटे की नोटिस देकर अनुबंध समाप्त कर सकता है — यह बहुत अनुचित है।",
      "confidence": "high"
    }
  ]
}
```

**Response `400 Bad Request`** — validation failure
```json
{ "detail": "File content does not match claimed MIME type (magic byte mismatch)." }
```

---

#### `GET /api/v1/analysis/` 🔒

List all analyses for the current user.

**Response `200 OK`**
```json
{
  "analyses": [
    {
      "analysis_id": "uuid4-string",
      "filename": "rental_agreement.pdf",
      "status": "completed",
      "risk_summary": { "green": 7, "yellow": 3, "red": 2 },
      "created_at": "2026-08-25T16:00:00Z"
    }
  ]
}
```

---

#### `GET /api/v1/analysis/{analysis_id}` 🔒

Retrieve a specific analysis result.

**Response `200 OK`** — same structure as upload response.

> **Access control:** Only the owning user can retrieve their own analysis. Other users receive `404 Not Found`.

---

### Module 8 — Scam Detection

Detects common scams targeting Indian citizens using a two-layer pipeline: keyword fast-path + BGE-M3 semantic search against a curated Qdrant collection. **All alert content (legal reality, recommended action) is fetched exclusively from the MongoDB `scam_patterns` collection — no LLM fabrication.**

Every matched alert includes a `db_id` field (e.g., `"SCAM_001"`) that uniquely identifies the source database record, providing full traceability.

---

#### `POST /api/v1/scam/check` 🔒

Submit a natural-language description of a suspicious situation for scam pattern matching.

**Request body**
```json
{
  "description": "A person called claiming to be from CBI and said I am under digital arrest. They asked me to stay on a video call and pay ₹50,000."
}
```

| Field | Type | Rules |
|---|---|---|
| `description` | `string` | 10–2000 characters, required |

**Response `200 OK` — pattern matched**
```json
{
  "status": "matched",
  "message": "⚠️ Recognised scam: 'Digital Arrest Scam' (Severity: CRITICAL). Read the alert carefully and follow the recommended steps.",
  "alert": {
    "matched": true,
    "db_id": "SCAM_001",
    "pattern_name": "Digital Arrest Scam",
    "severity": "CRITICAL",
    "match_method": "keyword",
    "confidence_score": 1.0,
    "description": "The caller claims to be a police officer, CBI agent... and tells the victim they are under 'digital arrest'...",
    "legal_reality": "There is NO concept of 'digital arrest' in Indian law. The Indian Penal Code (IPC), Code of Criminal Procedure (CrPC), and the Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023 do not recognise any form of video-call-based arrest...",
    "recommended_action": "1. Disconnect the call immediately...\n2. Note the number and screenshot any correspondence...\n3. File a cybercrime complaint at cybercrime.gov.in or call helpline 1930...",
    "reporting_channels": [
      "cybercrime.gov.in",
      "Helpline: 1930",
      "Nearest police station"
    ],
    "source_ref": "MHA Cybercrime Awareness Advisory 2024; I4C Digital Arrest Alert; BNSS 2023",
    "checked_at": "2026-08-26T07:30:00.000Z"
  }
}
```

**Response `200 OK` — no pattern matched**
```json
{
  "status": "no_match",
  "message": "This description did not match a known scam pattern in our database. If you suspect fraud, call 1930 immediately.",
  "alert": {
    "matched": false,
    "match_method": "none",
    "safe_fallback_message": "⚠️ This situation was not matched against any known scam pattern...",
    "checked_at": "2026-08-26T07:30:00.000Z"
  }
}
```

**Alert field reference**

| Field | Description | Source |
|---|---|---|
| `db_id` | Traceability key (e.g., `SCAM_001`) | MongoDB `scam_patterns._id` |
| `pattern_name` | Human-readable scam name | MongoDB |
| `severity` | `CRITICAL` / `HIGH` / `MEDIUM` | MongoDB |
| `match_method` | `keyword` or `semantic` | Agent pipeline |
| `confidence_score` | `1.0` for keyword; `0.30–1.0` for semantic | Cosine similarity |
| `description` | What this scam is | MongoDB (admin-curated) |
| `legal_reality` | Factual legal position under Indian law | MongoDB (admin-curated, cited to official sources) |
| `recommended_action` | Numbered action steps | MongoDB (admin-curated) |
| `reporting_channels` | Official reporting channels | MongoDB (admin-curated) |
| `source_ref` | Official legal/government references | MongoDB (admin-curated) |

> ⚠️ **Safety note:** `legal_reality` and `recommended_action` are **never LLM-generated**. They are fetched verbatim from the admin-curated database. The `source_ref` field documents the official Indian law or government advisory that each fact is grounded in.

---

#### `GET /api/v1/scam/patterns` 🔒

List all seeded scam pattern names, severities, and keywords. Useful for admin verification that seeding completed correctly.

**Response `200 OK`**
```json
{
  "total": 17,
  "patterns": [
    {
      "id": "SCAM_001",
      "name": "Digital Arrest Scam",
      "severity": "CRITICAL",
      "keywords": ["digital arrest", "arrested", "digitally arrested", "..."]
    },
    {
      "id": "SCAM_002",
      "name": "Fake CBI / ED / Income Tax Officer Call",
      "severity": "CRITICAL",
      "keywords": ["cbi officer", "enforcement directorate", "..."]
    }
  ]
}
```

**Seeded scam patterns (current v1 seed dataset)**

| ID | Pattern Name | Severity |
|---|---|---|
| SCAM_001 | Digital Arrest Scam | 🔴 CRITICAL |
| SCAM_002 | Fake CBI / ED / Income Tax Officer Call | 🔴 CRITICAL |
| SCAM_003 | Fake Courier / Customs Package Scam | 🟠 HIGH |
| SCAM_004 | UPI QR Code Payment Reversal Scam | 🟠 HIGH |
| SCAM_005 | KYC Expiry / Aadhaar Suspension Scam | 🟠 HIGH |
| SCAM_006 | Fake Job Offer / Work-from-Home Scam | 🟠 HIGH |
| SCAM_007 | Lottery / Prize Money Scam | 🔵 MEDIUM |
| SCAM_008 | Loan App Data Extortion Scam | 🔴 CRITICAL |
| SCAM_009 | Fake NGO / PM Relief Fund Donation Scam | 🔵 MEDIUM |
| SCAM_010 | Fake Investment / Trading App Scam (Pig Butchering) | 🔴 CRITICAL |
| SCAM_011 | OTP Sharing / SIM Swap Scam | 🔴 CRITICAL |
| SCAM_012 | Fake Tech Support Scam (Microsoft / Google) | 🟠 HIGH |
| SCAM_013 | Romance / Honey Trap Scam | 🟠 HIGH |
| SCAM_014 | Fake E-Commerce Seller / OLX Scam | 🔵 MEDIUM |
| SCAM_015 | Bank Account Freeze / Legal Threat Scam | 🟠 HIGH |
| SCAM_016 | Fake Electricity / Utility Disconnect Threat Scam | 🔵 MEDIUM |
| SCAM_017 | Sextortion / Deepfake Threat Scam | 🔴 CRITICAL |

---

### Module 9 — Complaint Filing Guide

Tells citizens **where to file** a complaint or legal document. Returns the correct government authority, verified portal URL, fee schedule, and required documents checklist for each supported document type.

**Architecture:** Exact-match MongoDB lookup by `doc_type` key. No LLM, no semantic search — a "close enough" authority is a wrong authority for a real filing. All authority data is sourced from verified statute and official government portals. Fields that cannot be verified without state-specific knowledge are explicitly marked `"needs_verification"` rather than fabricated.

**Supported document types:** `rti_application` · `consumer_complaint` · `legal_notice`

**Data sources (verified):**

| Document Type | Authority | Legal Basis | Fee Source |
|---|---|---|---|
| RTI Application | PIO → FAA → CIC / SIC | RTI Act 2005 | RTI (Fee and Cost) Rules 2005 |
| Consumer Complaint | District / State / NCDRC Commission | Consumer Protection Act 2019 | CPC (Commissions) Rules 2020 |
| Legal Demand Notice | Direct postal service (RPAD) | Transfer of Property Act / Contract Act | Court Fees Act 1870 (state-specific) |

**Module 6 → Module 9 handoff:** When a citizen completes a draft in the Document Drafter, a “📋 Where to File →” button appears on the preview card. It passes `draft_id` to this module’s lookup endpoint, which reads `doc_type` from the draft record in MongoDB — no re-entry required, no risk of misclassification from re-typed natural language.

---

#### `GET /api/v1/filing/lookup` 🔒

Look up the filing authority for a document type. Accepts either a direct `doc_type` parameter or a `draft_id` from a completed draft session (Module 6 handoff).

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `doc_type` | `string` | One of: `rti_application`, `consumer_complaint`, `legal_notice` |
| `draft_id` | `string` | UUID of a completed draft session. Backend reads `doc_type` from the draft record. Takes precedence over `doc_type` when both are provided. |

> At least one of `doc_type` or `draft_id` must be provided.

**Module 6 → Module 9 handoff example**

```bash
# After completing a draft, the frontend calls:
GET /api/v1/filing/lookup?draft_id=abc-123-rti-draft

# Backend reads doc_type from db.user_drafts.find_one({"draft_id": "abc-123-rti-draft", "user_id": "<me>"})
# Returns the RTI authority record without the citizen re-entering anything.
```

**Direct lookup example**

```bash
GET /api/v1/filing/lookup?doc_type=rti_application
```

**Response `200 OK` — authority found**

```json
{
  "found": true,
  "doc_type": "rti_application",
  "id": "FILING_RTI_001",
  "doc_type_name": "RTI Application",
  "authority_name": "Public Information Officer (PIO) of the concerned Public Authority",
  "authority_short": "PIO / First Appellate Authority / Central Information Commission",
  "description": "RTI Applications under the Right to Information Act, 2005 are filed in a three-tier system...",
  "portal_url": "https://rtionline.gov.in",
  "portal_name": "RTI Online (Government of India)",
  "portal_scope": "Central Government public authorities only. For state authorities, file with the respective state RTI portal or physically.",
  "fee": {
    "amount_central": "₹10 (ten rupees)",
    "payment_methods_central": ["Demand Draft", "Banker's Cheque", "Indian Postal Order", "Online payment via RTI Online portal"],
    "fee_exemption": "Persons below poverty line (BPL) are exempt from fee — attach BPL card copy",
    "state_fees": "needs_verification — state RTI fees vary; most states charge ₹10–₹50",
    "source": "RTI Act 2005, Section 6(1) and RTI (Regulation of Fee and Cost) Rules, 2005"
  },
  "filing_tiers": [
    {
      "tier": 1,
      "name": "Public Information Officer (PIO)",
      "description": "File your RTI application directly to the PIO...",
      "deadline_to_respond": "30 days (10 days if life/liberty is involved — RTI Act 2005, Section 7)",
      "how_to_file": "In writing (physical / postal) or online via RTI Online portal"
    }
  ],
  "required_documents": [
    "Written RTI application (in English, Hindi, or official language of the state)",
    "Clear statement of information sought",
    "Applicant name, address, and contact details",
    "Application fee (Demand Draft / IPO / postal order / online payment)",
    "BPL card copy (if claiming fee exemption)"
  ],
  "response_timeline": "30 days from receipt by PIO (10 days if the matter involves life or liberty)",
  "legal_basis": "Right to Information Act, 2005 (Act 22 of 2005)",
  "important_notes": [
    "RTI does not apply to certain exempt organisations listed in the Second Schedule of the RTI Act...",
    "You do not need to give any reason for seeking information."
  ],
  "source_ref": "Right to Information Act 2005 (Act 22 of 2005); RTI (Regulation of Fee and Cost) Rules 2005; CIC website cic.gov.in",
  "verified": true,
  "last_verified": "2026-08-26"
}
```

**Response `200 OK` — not found**
```json
{
  "found": false,
  "doc_type": "unknown_type",
  "message": "No filing authority information is available for document type 'unknown_type'. Currently supported types: consumer_complaint, legal_notice, rti_application."
}
```

**Response `400 Bad Request`** — neither parameter provided
```json
{ "detail": "Provide either 'doc_type' (rti_application | consumer_complaint | legal_notice) or 'draft_id' (to auto-read doc_type from a completed draft session)." }
```

**Response `404 Not Found`** — invalid or unauthorized `draft_id`
```json
{ "detail": "Draft not found or unauthorized access." }
```

> **Access control:** When using `draft_id`, only the owning user can access their draft. Other users receive `404 Not Found` (not `403 Forbidden`) to avoid leaking the existence of the `draft_id`.

**`FilingAuthorityResponse` field reference**

| Field | Description | Notes |
|---|---|---|
| `found` | `true` when a record was found | Always present |
| `doc_type` | Internal key: `rti_application` \| `consumer_complaint` \| `legal_notice` | Always present |
| `id` | Seed database ID (e.g., `FILING_RTI_001`) | DB traceability key |
| `authority_name` | Full authority name | From verified seed |
| `authority_short` | Short tier summary | From verified seed |
| `portal_url` | Verified government portal URL | `null` if no portal exists (legal notice) |
| `fee` | Fee object with `amount_central`, `fee_schedule`, `source`, etc. | State-specific amounts marked `needs_verification` |
| `filing_tiers` | Array of tier objects (name, description, deadline, jurisdiction) | Explains the escalation path |
| `required_documents` | Checklist of documents to prepare | From statute / official guidelines |
| `response_timeline` | Statutory response deadline | Cited to Act/Section |
| `legal_basis` | Authorising statute | Always non-empty |
| `important_notes` | Citizen-facing caveats and exceptions | From statute |
| `source_ref` | Official legal/government references | Used for verification |
| `verified` | `true` for admin-verified entries | Unverified entries will be `false` |

> ⚠️ **Safety note:** Fields with value `"needs_verification"` (e.g., state-specific court fees, district court addresses) are explicitly left unresolved rather than filled with plausible but unverified values. Citizens relying on this system to file real complaints must not receive fabricated government data.

---

#### `GET /api/v1/filing/authorities` 🔒

List all filing authorities in the database. Useful for populating the Filing Guide UI dropdown and for verifying that MongoDB seeding completed correctly.

**Response `200 OK`**
```json
[
  {
    "id": "FILING_RTI_001",
    "doc_type": "rti_application",
    "doc_type_name": "RTI Application",
    "authority_short": "PIO / First Appellate Authority / Central Information Commission",
    "portal_url": "https://rtionline.gov.in",
    "verified": true
  },
  {
    "id": "FILING_CONSUMER_001",
    "doc_type": "consumer_complaint",
    "doc_type_name": "Consumer Complaint",
    "authority_short": "District / State / National Consumer Commission (DCDRC / SCDRC / NCDRC)",
    "portal_url": "https://edaakhil.nic.in",
    "verified": true
  },
  {
    "id": "FILING_LEGAL_NOTICE_001",
    "doc_type": "legal_notice",
    "doc_type_name": "Legal Demand Notice",
    "authority_short": "Direct Service + Civil Court (if unresolved)",
    "portal_url": null,
    "verified": true
  }
]
```

> **Note:** If MongoDB `filing_authorities` collection is empty (seeding not yet run), this endpoint falls back to the seed file contents directly so the UI remains functional.

---

## Common Types

### `AgentOutput`

```typescript
{
  intent:   string;         // "rights" | "draft" | "analyze" | "scam" | "filing" | "vault"
  status:   "ok" | "error" | "timeout";
  output:   string;         // Human-readable text response
  metadata: {
    agent:      string;     // e.g., "FilingGuideAgent"
    latency_ms: number;
    [key: string]: any;     // Agent-specific metadata
  }
}
```

### `ScamAlertCard`

```typescript
{
  matched:             boolean;
  db_id?:              string;          // e.g., "SCAM_001" (traceability key)
  pattern_name?:       string;
  severity?:           "CRITICAL" | "HIGH" | "MEDIUM";
  match_method?:       "keyword" | "semantic" | "none";
  confidence_score?:   number;          // 0.0–1.0
  description?:        string;          // DB-sourced
  legal_reality?:      string;          // DB-sourced, admin-verified
  recommended_action?: string;          // DB-sourced, admin-verified
  reporting_channels?: string[];        // DB-sourced
  source_ref?:         string;          // Official legal reference
  safe_fallback_message?: string;       // Set when matched=false
  checked_at:          string;          // ISO 8601 timestamp
}
```

### `FilingAuthorityResponse`

```typescript
{
  found:               boolean;
  doc_type:            string;          // "rti_application" | "consumer_complaint" | "legal_notice"
  id?:                 string;          // e.g., "FILING_RTI_001" (DB traceability key)
  doc_type_name?:      string;
  authority_name?:     string;          // Full authority name (from verified seed)
  authority_short?:    string;          // Short tier summary
  portal_url?:         string | null;   // Verified government portal URL (null if not applicable)
  portal_name?:        string;
  portal_scope?:       string;          // Scope note (e.g., "Central Govt only")
  fee?:                object;          // Fee info; state-specific fields marked "needs_verification"
  filing_tiers?:       object[];        // Escalation path (tier 1 → tier 2 → tier 3)
  required_documents?: string[];        // Documents checklist
  response_timeline?:  string;          // Statutory deadline (Act/Section cited)
  legal_basis?:        string;          // Authorising statute
  important_notes?:    string[];        // Caveats and exceptions
  source_ref?:         string;          // Official references
  verified?:           boolean;
  last_verified?:      string;          // ISO date (YYYY-MM-DD)
  message?:            string;          // Set when found=false
}
```

---

## Interactive Documentation

When the backend is running locally, full interactive API documentation is available at:

| URL | Interface |
|---|---|
| [`http://localhost:8000/api/docs`](http://localhost:8000/api/docs) | **Swagger UI** — try every endpoint in-browser |
| [`http://localhost:8000/api/redoc`](http://localhost:8000/api/redoc) | **ReDoc** — clean, printable reference |
| [`http://localhost:8000/api/openapi.json`](http://localhost:8000/api/openapi.json) | Raw OpenAPI 3.1 schema |

> All request schemas, response examples, and field validations in Swagger UI are auto-generated from the FastAPI Pydantic models — this document supplements Swagger with contextual explanations, design rationale, and security notes that are not captured in code annotations alone.

*This document covers API endpoints through Module 9 (Complaint Filing Guide). It will be updated as Modules 10–16 are completed.*

---

## Module 10 — Vault & Deadlines

> **Base path:** `/api/v1/vault`  
> **Authentication:** All endpoints require a valid JWT Bearer token.  
> **Anonymous mode:** All endpoints return `403 Forbidden` for anonymous sessions (role = `"anonymous"`) with a user-friendly explanation message.  
> **Encryption:** All stored files are AES-256-GCM encrypted at upload time. Files are decrypted on-demand during download. The encryption key is never stored alongside file data.

---

### `POST /api/v1/vault/upload`

Upload a document to the encrypted vault.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | File | ✓ | PDF, JPEG, or PNG. Maximum 10 MB. |

**Pipeline (in order):**
1. Magic-byte file type validation (Module 7 reuse — rejects misnamed files)
2. OCR text extraction (Module 7 reuse — PyMuPDF for digital PDFs, Tesseract for scans)
3. AES-256-GCM encryption of file bytes
4. Encrypted bytes written to disk via Module 7 `SecureStorageService`
5. LLM-based date extraction from OCR text
6. Metadata (including unconfirmed extracted dates) written to MongoDB

**Response `200 OK`:**
```json
{
  "file_id": "uuid4-string",
  "original_name": "lease.pdf",
  "content_type": "application/pdf",
  "size_bytes": 245760,
  "created_at": "2026-08-26T13:30:00+00:00",
  "encrypted": true,
  "extracted_dates": [
    {
      "label": "Lease End Date",
      "date_str": "2027-03-31",
      "confidence": 0.92,
      "raw_snippet": "The lease expires on 31 March 2027",
      "needs_confirmation": false
    },
    {
      "label": "Security Deposit Return",
      "date_str": "2027-04-15",
      "confidence": 0.55,
      "raw_snippet": "15/04/2027",
      "needs_confirmation": true
    }
  ],
  "extraction_summary": {
    "total_dates_found": 2,
    "needs_confirmation_count": 1,
    "all_auto_confirmed": false
  },
  "message": "Document uploaded and encrypted. Found 2 date(s). 1 date(s) require your verification before a deadline is created."
}
```

**Date confidence model:**

| Confidence | `needs_confirmation` | Meaning |
|---|---|---|
| ≥ 0.85 | `false` | Date is explicit and unambiguous |
| 0.70–0.84 | `false` | Date is explicit; label requires interpretation |
| 0.50–0.69 | `true` | Date is present but format is ambiguous |
| < 0.50 | `true` | Date is inferred or highly uncertain |

> **Safety note:** `needs_confirmation: true` means the citizen MUST verify this date against the source document before a deadline is created. Extracted dates are NOT automatically converted to deadlines — a separate `/confirm-dates` call is required.

**Error responses:**

| Code | Condition |
|---|---|
| `400` | File is empty, wrong type, too large, or fails magic-byte check |
| `403` | Anonymous session |
| `500` | Internal error (encryption key missing, disk error) |

---

### `POST /api/v1/vault/{doc_id}/confirm-dates`

Confirm extracted dates and create deadline records.

This is the second step after upload. The citizen reviews the extracted dates (correcting any with `needs_confirmation: true`), and submits the dates they want to track. Only confirmed dates create deadline records.

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `doc_id` | string | `file_id` from the upload response |

**Request body:**
```json
{
  "confirmed_dates": [
    {
      "label": "Lease End Date",
      "date_str": "2027-03-31",
      "doc_type": "legal_notice"
    }
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `label` | string | ✓ | Human-readable label for the deadline |
| `date_str` | string | ✓ | Date in `YYYY-MM-DD` format (citizen-corrected if needed) |
| `doc_type` | string | — | Document type for proactive drafter: `legal_notice` (default), `rti_application`, `consumer_complaint` |

**Response `200 OK`:**
```json
{
  "created": 1,
  "errors": [],
  "deadlines": [
    {
      "deadline_id": "uuid4-string",
      "user_id": "user-sub",
      "vault_doc_id": "file-uuid",
      "label": "Lease End Date",
      "deadline_date": "2027-03-31",
      "doc_type": "legal_notice",
      "reminders_sent": [],
      "created_at": "2026-08-26T13:35:00+00:00",
      "last_draft_text": null
    }
  ]
}
```

---

### `GET /api/v1/vault/documents`

List all vault documents for the authenticated user.

**Response `200 OK`:**
```json
{
  "documents": [ /* VaultDocument objects, newest first */ ],
  "count": 3
}
```

Each document object matches the upload response schema. `extracted_dates` contains the LLM-extracted dates (may include unconfirmed dates).

---

### `GET /api/v1/vault/documents/{doc_id}/download`

Download a vault document (decrypted).

Returns the original file bytes with the correct `Content-Type` header. Access is strictly limited to the document owner (user_id must match).

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `doc_id` | string | `file_id` from the upload or list response |

**Response:** Binary file bytes with `Content-Disposition: attachment`.

**Error responses:**

| Code | Condition |
|---|---|
| `404` | Document not found, or belongs to a different user |
| `500` | Decryption error (key mismatch or data corruption) |

---

### `DELETE /api/v1/vault/documents/{doc_id}`

Permanently delete a vault document.

> **Hard delete — unrecoverable.** Removes the encrypted file from disk, the MongoDB metadata record, and all associated deadline records. There is no soft-delete or trash mechanism.

**Response `200 OK`:**
```json
{
  "deleted": true,
  "file_id": "uuid4-string",
  "message": "Document permanently deleted."
}
```

---

### `GET /api/v1/vault/deadlines`

List upcoming deadlines for the authenticated user.

**Response `200 OK`:**
```json
{
  "deadlines": [
    {
      "deadline_id": "uuid4-string",
      "vault_doc_id": "file-uuid",
      "label": "Lease End Date",
      "deadline_date": "2027-03-31",
      "doc_type": "legal_notice",
      "reminders_sent": [30],
      "created_at": "2026-08-26T13:35:00+00:00",
      "last_draft_text": "Date: 26 August 2026\n\nTo: [FILL IN: Recipient Name]...",
      "days_remaining": 217,
      "urgency": "low"
    }
  ],
  "count": 1
}
```

**`urgency` field values:**

| Value | Condition | Frontend indicator |
|---|---|---|
| `critical` | ≤ 3 days remaining | 🔴 Pulsing red badge |
| `high` | 4–15 days remaining | 🟠 Orange badge |
| `medium` | 16–30 days remaining | 🟡 Yellow badge |
| `low` | > 30 days remaining | 🟢 Indigo badge |

**`reminders_sent` field:** An array of T-minus intervals (in days) for which reminders have already been sent. Possible values: `[30]`, `[15]`, `[3]`, or any combination. Used by the scheduler to prevent duplicate notifications.

**Scheduler behaviour:**
- APScheduler runs daily at 09:00 server-local time
- Checks all deadlines where `days_remaining` ∈ `{30, 15, 3}`
- For each matching deadline: invokes `DocumentDrafterAgent` to generate a proactive draft → sends email notification (SMTP in production, console log in development) → adds interval to `reminders_sent`
- A reminder fires exactly once per interval, regardless of daily runs

---

### `GET /api/v1/vault/deadlines/{deadline_id}/draft`

Get the proactively generated document draft for a deadline.

Returns the draft text generated by the Document Drafter Agent when the most recent reminder fired. Returns `draft_available: false` if no reminder has fired yet.

**Response `200 OK` (draft available):**
```json
{
  "deadline_id": "uuid4-string",
  "draft_available": true,
  "label": "Lease End Date",
  "deadline_date": "2027-03-31",
  "reminders_sent": [30],
  "draft_text": "Date: 26 August 2026\n\nTo: [FILL IN: Recipient Name]\n..."
}
```

**Response `200 OK` (no draft yet):**
```json
{
  "deadline_id": "uuid4-string",
  "draft_available": false,
  "message": "No draft yet. A draft will be created when the first reminder fires (T-30, T-15, or T-3 days)."
}
```

---

### Vault-specific Error Reference

| Code | Body `detail` contains | Meaning |
|---|---|---|
| `403` | `"real LEXIS account"` + `"phone number"` | Anonymous session — vault requires authenticated account |
| `400` | `"magic bytes"` or `"not allowed"` | File type rejected |
| `400` | `"YYYY-MM-DD"` | Submitted date string has wrong format |
| `404` | `"access denied"` | File not found, or belongs to a different user |

---

### Vault Security Model

| Property | Implementation |
|---|---|
| **Encryption** | AES-256-GCM. Key in `VAULT_ENCRYPTION_KEY` env var only — never on disk with data |
| **Access control** | Every file lookup/download/delete is scoped to `{file_id, user_id}` — no cross-user access |
| **Anonymous block** | All 7 vault endpoints reject anonymous JWTs at the route layer |
| **Hard delete** | `DELETE` removes file from disk + MongoDB + deadline records — no soft flag |
| **Nonce** | 12 random bytes generated fresh per encryption call — nonce reuse is impossible |
| **Auth tag** | 16-byte GCM tag — tampered ciphertext fails decryption with `InvalidTag`, not silently |

---

## Interactive Documentation

When the backend is running locally, full interactive API documentation is available at:

| URL | Interface |
|---|---|
| [`http://localhost:8000/api/docs`](http://localhost:8000/api/docs) | **Swagger UI** — try every endpoint in-browser |
| [`http://localhost:8000/api/redoc`](http://localhost:8000/api/redoc) | **ReDoc** — clean, printable reference |
| [`http://localhost:8000/api/openapi.json`](http://localhost:8000/api/openapi.json) | Raw OpenAPI 3.1 schema |

> All request schemas, response examples, and field validations in Swagger UI are auto-generated from the FastAPI Pydantic models — this document supplements Swagger with contextual explanations, design rationale, and security notes that are not captured in code annotations alone.

---

*This document covers API endpoints through Module 10 (Vault & Deadlines). It will be updated as Modules 11–16 are completed.*
