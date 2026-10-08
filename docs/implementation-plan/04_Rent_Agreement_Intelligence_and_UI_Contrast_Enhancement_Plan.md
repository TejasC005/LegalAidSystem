# 04. Rent Agreement Intelligence, LLM Cascade Resilience & UI Contrast Enhancement Plan

**Prepared:** 2026-10-08  
**Scope:** Document Analyzer (Module 7), Document Intelligence, Clause Classification, UI Accessibility  
**Target Files:**
- `backend/services/analysis/clause_classifier.py`
- `backend/services/analysis/doc_intelligence.py`
- `backend/agents/document_analyzer/agent.py`
- `frontend/src/pages/DocumentAnalyzer.jsx`
- `frontend/src/pages/DocumentAnalyzer.css`
- `backend/tests/unit/test_document_analyzer.py`
- `docs/Test/04_Project_Walkthrough.md`

---

## 1. Executive Summary & Root Cause Breakdown

### A. Why did "Could not determine risk level — LLM call failed" occur?
1. **Isolated Single-Model Invocation:**  
   In [`backend/services/analysis/clause_classifier.py`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/backend/services/analysis/clause_classifier.py#L376-L389), `_classify_single_clause_llm()` called `client.aio.models.generate_content(model=model_name)` targeting only `settings.GEMINI_MODEL_DEV` (`gemini-2.5-flash`).
2. **Free-Tier Quota Depletion (`429 RESOURCE_EXHAUSTED`):**  
   Google AI Studio's free tier imposes a strict 20 requests/day per-model quota. Once `gemini-2.5-flash` reached its cap, `client.aio.models.generate_content` threw `429 RESOURCE_EXHAUSTED`.
3. **No Cascade or Retry Fallback:**  
   Unlike `extractor.py`, `clause_classifier.py` lacked a multi-model cascade or retry logic. The `except Exception as exc:` block caught the error and defaulted each of the 7 clauses to:
   ```
   🟢 Low Risk | Confidence: low
   Could not determine risk level — LLM call failed. Please review manually.
   ```
4. **Stale Model List in `doc_intelligence.py`:**  
   `_call_llm_json()` was also referencing an outdated model candidate list containing exhausted and 404 models.

### B. Why was the document classified as generic "Legal Contract" instead of "Rental Agreement"?
1. **Restrictive Keyword Threshold:**  
   In [`doc_intelligence.py`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/backend/services/analysis/doc_intelligence.py#L261-L278), `rental_keywords` required `rental_hits >= 2` distinct keyword matches.
2. **Page 1 Limitation of Indian Stamp Paper Agreements:**  
   The uploaded image is **Page 1 of 3** of an Andhra Pradesh Non-Judicial Stamp Paper Rent Agreement.
   - It prominently features `"RENT AGREEMENT"`.
   - The parties are styled as `"First Party / Owner"` and `"Second Party"`.
   - Covenants such as `"monthly rent"`, `"security deposit"`, and `"lock-in period"` reside on Pages 2 and 3.
   - Because only `"rent agreement"` matched (1 hit), it fell below the threshold of 2, dropped into general contract heuristics (`"agreement"`, `"this agreement is made"`, `"terms and conditions"` -> 3 hits), and was misclassified as `"contract"` / `"Legal Contract / Agreement"`.
3. **Missed Specialized Extraction:**  
   Because it was classified as a generic contract, `extract_rental_agreement_info()` was bypassed, preventing the extraction of Landlord, Tenant, Leased Property, Stamp Paper details, and the dedicated Tenancy Intelligence View.

### C. Why was the text in the UI not properly visible?
1. **Low WCAG Contrast Ratios in Dark Mode:**  
   In [`DocumentAnalyzer.css`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/frontend/src/pages/DocumentAnalyzer.css#L404-L450):
   - `.clause-panel-label` used `#64748b` (dark slate on dark navy background `rgba(15, 23, 42, 0.6)`), yielding a contrast ratio of ~2.2:1 (failing the WCAG AA minimum of 4.5:1).
   - `.confidence-tag` used `#475569` (almost black on dark navy), making it virtually unreadable.
   - `.clause-text-original` used `#94a3b8` in italics, resulting in a washed-out, blurry appearance.
   - `.clause-explanation` used `#94a3b8` instead of bright high-contrast text.

---

## 2. Proposed Architecture & Solutions

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       DOCUMENT ANALYZER PIPELINE                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                         OCR Verbatim Text Extracted
                                      │
              ▼                                             ▼
┌───────────────────────────────┐             ┌───────────────────────────────┐
│ DOCUMENT CLASSIFICATION &     │             │ RESILIENT CLAUSE CLASSIFIER   │
│ STAMP PAPER INTELLIGENCE      │             │ & HEURISTIC PRE-SCORING       │
├───────────────────────────────┤             ├───────────────────────────────┤
│ • Heuristic: "rent agreement" │             │ • Rule 1-13 deterministic     │
│   or "lease deed" = 100%      │             │ • Preamble/Stamp paper = Safe │
│   Rental Agreement.           │             │ • LLM Multi-Model Cascade:    │
│ • Detect Non-Judicial Stamp   │             │   gemini-3.5-flash            │
│   (State, ₹ Value, Vendor,    │             │   gemini-3.1-flash-lite       │
│   Serial, Purchaser, Date).   │             │   gemini-3.5-flash-lite       │
│ • Extract Parties & Property: │             │   gemini-2.5-flash            │
│   - Landlord / First Party    │             │   gemini-3.7-flash            │
│   - Tenant / Corporate Entity │             │ • 1s backoff retry on 429/503 │
│   - Demised Premises Address  │             │ • OpenAI GPT-4o-mini fallback │
│ • Page Marker (Page 1 of 3)   │             │                               │
│ • Document Completeness &     │             │                               │
│   Legal Validity Assessment   │             │                               │
└───────────────────────────────┘             └───────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ACCESSIBLE, HIGH-CONTRAST UI VIEW                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Executive Intelligence & Validity Card:                                  │
│    - Document type & stamp paper authenticity                               │
│    - Verified parties (Owner vs Corporate Tenant)                           │
│    - Property address details                                               │
│    - Legal validity & missing terms notice (Page 1 of 3 guidance)           │
│ 2. High-Contrast Typography:                                                │
│    - Crisp `#f1f5f9` clause text in framed quote boxes                      │
│    - `#93c5fd` radiant section labels with emoji badges                     │
│    - High-visibility `#cbd5e1` explanation text & pill tags                 │
│ 3. Dual-Tab Tenancy View:                                                   │
│    - Tab 1: Key Lease Terms, Parties, Property & Validity Assessment        │
│    - Tab 2: Clause-by-Clause Risk Review                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Implementation Phases

### Phase 1: Robust Document Classification & Stamp Paper Parsing
- **File:** [`backend/services/analysis/doc_intelligence.py`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/backend/services/analysis/doc_intelligence.py)
1. **Single-Hit Decisive Rental Heuristic:**
   - If document text contains `"rent agreement"`, `"tenancy agreement"`, `"residential lease"`, or `"lease deed"`, immediately categorize as:
     `category="agreement_contract"`, `doc_type="rental_agreement"`, `title="Residential Tenancy Agreement"`.
   - Also match combinations of `"rent"` / `"lease"` with `"let out"`, `"property"`, or `"first party/owner"`.
2. **Indian Non-Judicial Stamp Paper Extractor:**
   - Extract stamp metadata: State (`ANDHRA PRADESH`), Stamp Value (`₹50`), Serial Number (`AY 673858`), Date (`28-1-23`), Stamp Vendor (`Y. Krishna Veni`), and Purchaser (`Dasaripalli Dinesh Kumar s/o Chennappa`).
3. **Multi-Page & Completeness Detection:**
   - Detect page footers like `1 of 3`, `Page 1 of 3`, or `1/3`.
   - If only Page 1 is present, set `is_partial_document=True`, `total_pages=3`, `current_page=1`.
   - Provide an explicit validity assessment:
     *"Non-judicial stamp paper verified. Landlord, tenant, and property recitals are legally consistent. However, financial terms (rent amount, security deposit), termination covenants, and execution signatures reside on subsequent pages (Page 1 of 3 uploaded). Upload Pages 2 & 3 to verify financial obligations and signature validity."*

### Phase 2: Resilient Clause Classifier with Multi-Model Cascade
- **Files:** [`backend/services/analysis/clause_classifier.py`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/backend/services/analysis/clause_classifier.py), [`backend/services/analysis/doc_intelligence.py`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/backend/services/analysis/doc_intelligence.py)
1. **Deterministic Preamble & Stamp Recital Filtering:**
   - Clauses that are purely non-judicial stamp paper headers, title recitals, or party definitions (e.g. `"भारतीय गैर न्यायिक पचास रुपये FIFTY RUPEES..."` or `"This agreement is made and executed on..."`) should be pre-classified deterministically:
     `risk_level=RiskLevel.GREEN`, `confidence="high"`, `explanation="Standard introductory recital and official stamp paper header. Establishes legal jurisdiction and party identities."`.
   - This eliminates redundant LLM calls on boilerplate headers and guarantees instant, accurate scoring!
2. **Multi-Model Cascade in `_classify_single_clause_llm`:**
   - Implement the active Gemini model cascade:
     `gemini-3.5-flash` ➔ `gemini-3.1-flash-lite` ➔ `gemini-3.5-flash-lite` ➔ `gemini-2.5-flash` ➔ `gemini-3.7-flash` ➔ `gemini-3.6-flash` ➔ `gemini-3.8-flash`.
   - Add a 1.0s backoff retry on `429` / `503` before advancing to the next model.
   - Include OpenAI `gpt-4o-mini` fallback if configured.
3. **Synchronize `_call_llm_json` in `doc_intelligence.py`:**
   - Update model candidate list to match the active high-headroom models.

### Phase 3: High-Contrast Accessible UI & Executive Validity View
- **Files:** [`frontend/src/pages/DocumentAnalyzer.jsx`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/frontend/src/pages/DocumentAnalyzer.jsx), [`frontend/src/pages/DocumentAnalyzer.css`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/frontend/src/pages/DocumentAnalyzer.css)
1. **Executive Intelligence & Legal Validity Card:**
   - Position a new top-level card for Agreements and Contracts displaying:
     - 📜 **Document Nature:** Non-Judicial Stamp Paper Rent Agreement (₹50, AP).
     - 👥 **Parties:** First Party/Owner (`K Srinivasulu`) & Second Party/Tenant (`Future Bright Communications (OPC) Private Limited` / `Dasaripalli Dinesh Kumar`).
     - 📍 **Property:** D.No. 8-19-105/10, Ganesh Nagar, Giddalur, Prakasam Dist, AP.
     - ⚠️ **Legal Validity & Completeness Alert:** Notice explaining that Page 1 of 3 is uploaded, highlighting what is verified vs. what requires Pages 2 & 3.
     - 💡 **Plain-Language Summary:** Clear English and Hindi summaries.
2. **CSS High-Contrast Overhaul:**
   - Update `.clause-panel-label`: `#93c5fd` with bright font weight (`600`) and clear spacing.
   - Update `.clause-text-original`: `#f8fafc` (high-contrast off-white), normal weight, font-size `0.92rem`, with dark glass background `rgba(15, 23, 42, 0.8)` and left accent border.
   - Update `.confidence-tag`: Distinct badge styling with `#94a3b8` / `#cbd5e1` on subtle pill background.
   - Update `.clause-explanation`: `#f1f5f9` (clean legible contrast).
   - Update `.summary-stat-card .stat-label`: `#cbd5e1` for clear readability.
   - Ensure WCAG AA compliance across all clause cards and metadata panels.

### Phase 4: Automated Testing & Verification
- **File:** [`backend/tests/unit/test_document_analyzer.py`](file:///d:/Tejas%20Class%20Projects/LEXIS_project_structure/LEXIS/backend/tests/unit/test_document_analyzer.py)
1. **Test 20 (Rent Agreement Single-Hit & Stamp Paper Classification):**
   - Verify that text containing `"RENT AGREEMENT"` and Stamp Paper details is classified as `agreement_contract / rental_agreement`.
2. **Test 21 (Stamp Paper & Multi-Page Extractor):**
   - Verify extraction of Landlord, Corporate Tenant, Property Address, and `is_partial_document` detection on 1-of-3 page agreements.
3. **Test 22 (Clause Classifier Cascade on Quota Exhaustion):**
   - Verify that `_classify_single_clause_llm` cascades past models returning 429 and successfully scores clauses.
4. **Test 23 (Preamble / Stamp Header Heuristic Pre-Scoring):**
   - Verify deterministic `GREEN` high-confidence scoring on Indian Non-Judicial Stamp Paper preamble clauses.
5. **Regression Verification:** Run full test suite (all 136+ unit tests passing).

---

## 4. Expected Deliverables & User Experience

| Metric / Feature | Current State | Target State After Implementation |
|---|---|---|
| **Document Classification** | Generic `contract` (`Legal Contract / Agreement`) | `rental_agreement` (`Residential Tenancy Agreement on Stamp Paper`) |
| **Clause LLM Resilience** | Fails with `Could not determine risk level — LLM call failed` | Cascades across 7+ models + quick retries; 0% unhandled failures |
| **Preamble Recitals** | Generic failure on stamp paper text | Deterministically recognized as Safe stamp header & recitals |
| **Summary & Validity** | None (only 7 raw clause cards) | Executive Summary Card with Parties, Property, Stamp Paper Details & Legal Validity Check |
| **Partial Document Notice** | None (silent omission of rent/deposit) | Explicit advice: *"Page 1 of 3 uploaded. Upload Pages 2 & 3 to analyze financial commitments."* |
| **UI Contrast & Readability** | Low-contrast `#64748b` and `#475569` on dark background | WCAG AA compliant: `#f1f5f9` / `#93c5fd` / `#cbd5e1` high-contrast styling |

---

## 5. Review & Approval

Please review this plan. Upon your confirmation, implementation will proceed systematically across the backend extraction services, frontend UI styling, and automated test suite.
