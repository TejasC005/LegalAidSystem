# LEXIS
### Autonomous Multi-Agent Legal Aid System for Indian Citizens

Final-year capstone project — Sanjivani College of Engineering, Kopargaon.

LEXIS helps Indian citizens understand their legal rights, draft legal documents, analyze contracts for risk, detect common scams, find the correct authority to file a complaint with, and safely store important documents with proactive deadline reminders — through a coordinated system of AI agents that plan, act **in parallel where needed**, check their own work, and correct themselves, rather than a single prompt-and-response tool.

> This README is the single source of truth for project status. Every module is checked off here as it's completed, with a one-line changelog entry. Keep it current — it doubles as your academic progress record.

---

## Project status

| # | Module | Status | Notes |
|---|---|---|---|
| 0 | Project Structure & Scaffolding | ✅ Done | |
| 1 | Core Backend Foundation | ✅ Done | FastAPI app factory, Motor/Redis lifespan, Pydantic Settings, structured JSON logging, CORS from env, /api/v1/health + /health/db, 5 unit tests passing |
| 2 | Authentication & Role-Based Access Control | ✅ Done | OTP auth (phone-based), JWT access+refresh tokens, role guard dependency, anonymous mode, Redis-keyed OTP rate limit, 5 unit tests passing |
| 3 | Frontend Foundation (React) | ✅ Done | React 18 + Vite + React Router v6, Axios instance with JWT interceptors, two-step OTP login flow, AuthContext (localStorage persistence), ProtectedRoute guard, shared AppLayout (header/sidebar/footer), 6 placeholder feature pages |
| 4 | Orchestrator Agent Core | ✅ Done | LangGraph state machine, multi-intent classification, concurrent fan-out, partial failure isolation, 21 unit tests passing |
| 5 | Agent 1 — Rights Explainer | ✅ Done | Reference template implementation for Modules 6–10; Qdrant + BGE-M3 RAG pipeline, starter dataset (8 topics), hallucination safeguard, citation verification check, interactive React chat UI |
| 6 | Agent 2 — Document Drafter | ✅ Done | Clause-based templates (RTI, Legal Notice, Consumer Complaint), multi-turn questionnaire, PDF/DOCX export, per-user access control, validated parallel execution milestone |
| 7 | Agent 3 — Document Analyzer | ✅ Done | Secure file upload (allowlist + magic-byte validation), PyMuPDF + Tesseract OCR pipeline, rule-based + LLM-assisted clause risk classifier (GREEN/YELLOW/RED), bilingual Hindi/English rewriter, reusable per-user secure storage, orchestrator ANALYZE intent wired, side-by-side frontend UI, 42 unit tests passing |
| 8 | Agent 4 — Scam Detection Engine | ✅ Done | 17-pattern seed DB (MongoDB + Qdrant `scam_patterns`), keyword fast-path + BGE-M3 semantic search, DB-grounded alert generation (0 LLM fabrication), orchestrator SCAM intent wired, premium alert-card frontend UI, 5 unit tests — 47 total passing |
| 9 | Agent 5 — Complaint Filing Guide | ✅ Done | Exact-match filing authority DB (RTI, Consumer, Legal Notice), Module 6 → 9 handoff via draft_id (no re-entry), orchestrator FILING intent wired, premium "Where to File" frontend UI, 5 unit tests — 52 total passing. All 5 originally-scoped core feature agents are live end-to-end. |
| 10 | Agent 6 — Vault & Deadline Agent | ✅ Done | AES-256-GCM encryption at rest, OCR/date extraction (Module 7 reuse), LLM date extraction with confidence flagging, citizen confirmation flow, APScheduler daily job, proactive Document Drafter invocation at T-30/15/3, email notifications, hard delete, 13 unit tests — 65 total passing. **See deviation note below.** |
| 11 | Memory & Reflection Layer | ✅ Done | Redis session store (concurrent-safe, UUID-keyed, PII-free), Confirmation Agent (per-agent validation criteria), bounded retry loop (max 3 retries → honest fallback), cross-agent contradiction check (Rule C1: Legal Act Mismatch), PII-scrubbed MongoDB reflection log, 8 new unit tests — 73 total passing |
| 12 | Admin Panel | ✅ Done | Admin-only protected routes (`require_role(["admin"])`), real reflection log analytics (all 6 agents, zero dummy numbers), user management (suspend/reactivate), moderation queue (Confirmation Agent fallbacks), dark React dashboard (`/admin`), 18 unit tests — 91 total passing |
| 13 | Lawyer Role Scaffold | ✅ Done | `GET /api/v1/lawyer/dashboard` protected by `require_role(["lawyer"])`, Coming Soon UI, role-isolation tests (lawyer→admin 403, admin/user/anon→lawyer 403), 8 new tests — 99 total passing |
| 13B | Enhanced Auth & Profile | ✅ Done | Secondary Email OTP, profile sub-document (full_name, address, preferred_language, DOB, picture_url, notification_preference), GET/PATCH profile, image-restricted picture upload via SecureStorageService, ProfileSetup & Settings UI, notification_preference wired to deadline scheduler, cascading hard delete & JSON export, 8 new unit tests — 107 total passing |
| 14 | Security Hardening Pass | ⬜ Not started | Includes Vault encryption verification — see Security Checklist below |
| 15 | Testing, QA, Containerization & Deployment | ⬜ Not started | Includes parallel-execution regression test |
| 16 | Final Polish, Demo Prep & Documentation | ⬜ Not started | |

*(17 modules total, 0–16. Update the Status column to `✅ Done` and fill Notes as each module completes — this table is read by later Antigravity sessions as project context.)*

---

## Architecture

LEXIS uses **LangGraph** as its core orchestration layer to build an autonomous multi-agent state machine.

### What is a LangGraph State Machine?
A **state machine** is a computational model that maintains a central data structure (the **State**) and moves it through a graph of discrete processing steps (**Nodes**). In LEXIS:
1. **Shared State (`OrchestratorState`):** A `TypedDict` containing the citizen's query, conversation history, detected intent(s), a shared `scratchpad` list for specialist output, final compiled response, status flags, and LLM call counters.
2. **Nodes:** Isolated Python functions (e.g. `classify_intent_node`, `specialist_node`, `compile_response_node`) that receive state, execute work, and return state updates.
3. **Edges & Routers:** Logic that determines which node(s) execute next based on current state.

### Why Routing via Graph vs. `if/else` in a Single Function?
In traditional code, handling multiple intents with `if/else` leads to **sequential execution**:
```python
# Traditional sequential approach (Slow & Brittle)
if "rights" in intents:
    res1 = run_rights_agent(query)      # Wait 3s
if "filing" in intents:
    res2 = run_filing_agent(query)      # Wait 3s -> Total 6s
```
Using a **LangGraph state machine with conditional fan-out edges**:
- **Declarative & Modular:** Agent execution paths are decoupled from business logic.
- **Concurrent Supersteps:** Instead of calling functions linearly, the router returns a list of `Send` objects. LangGraph executes all matched nodes in the **same superstep in parallel**.
- **State Merging via Reducers:** When parallel nodes write to the shared `scratchpad` key simultaneously, LangGraph uses an append reducer (`Annotated[List[AgentOutput], operator.add]`) to combine results safely without race conditions or state corruption.

### Concurrent Node Execution vs. Sequential Execution
- **Sequential Execution:** Agents execute one after another ($T_{total} = T_1 + T_2 + \dots + T_n$). If 3 agents take 3 seconds each, the user waits 9 seconds.
- **Concurrent Fan-Out Execution:** All matched specialist nodes trigger simultaneously in parallel ($T_{total} = \max(T_1, T_2, \dots, T_n)$). The request completes as fast as the single slowest agent (~3 seconds total).

### Why This Differs from "Just Calling an LLM"
A raw LLM call is a single prompt-and-response text completion. LEXIS is a **genuinely agentic system**:
1. **Dynamic Intent Decomposition:** An intent classifier decomposes complex queries into one or multiple specialist agent domains.
2. **Parallel Specialist Delegation:** Multiple domain-specific agents run in parallel with isolated state and dedicated prompts/tools.
3. **Partial-Result Resilience:** Individual node timeouts and failures are caught internally so that if one agent fails, the orchestrator still delivers a partial response from succeeding agents rather than crashing the request.
4. **Cost & Latency Guardrails:** Hard caps (`MAX_LLM_CALLS_PER_REQUEST`) protect against runaway costs and infinite loops.
5. **Loopback & Self-Correction (Module 11):** Confirmation Agent validates every specialist output before compilation, using concrete per-agent criteria (citation check, template completeness, DB grounding). Bounded retry loop (max 3 attempts) with honest fallback and cross-agent contradiction detection (Rule C1: Legal Act Mismatch). All validation is code-checkable — no vague LLM quality judgements.

**Core agentic design principles (non-negotiable, per project spec):**
- Goal decomposition and routing through a central Orchestrator Agent (LangGraph)
- **Concurrent multi-agent execution** — more than one specialist agent can be active on a single query at once, not strictly sequential (validated at Module 4 & 6)
- Shared scratchpad/state across agents within a session, safe under concurrent writes via `operator.add` reducers
- Tool use per specialist agent (RAG, OCR, structured directories, scheduler)
- Bounded self-correction: a Confirmation Agent checks every output — including cross-agent contradictions — max 3 retries before an honest fallback
- One agent (Vault & Deadline) acts **proactively**, without the citizen re-initiating a query

---

## Roles

| Role | MVP Status | Capabilities |
|---|---|---|
| User (citizen) | Functional | All 6 features, own history, anonymous mode (Vault requires a real account) |
| Admin | Functional | Analytics, user management, moderation |
| Lawyer | ✅ Scaffolded (Module 13) | `GET /api/v1/lawyer/dashboard` + `/lawyer` frontend route, both guarded by `require_role(["lawyer"])`. Coming Soon screen with honest static text. Role isolation verified by 8 unit tests. No functional features — by design. |

---

## Tech stack

- **Frontend:** React 18 / Vite, React Router, Axios
- **Backend:** FastAPI (Python), LangGraph, MongoDB, Redis
- **AI / RAG:** GPT-4o (demo) / GPT-4o-mini (dev), Qdrant + BGE-M3, Sarvam AI (STT)
- **Infrastructure:** Docker, Render / Railway, GitHub Actions
- **Security:** JWT rotation, OTP auth (custom, provider-agnostic), anonymous mode, encryption-at-rest, prompt-injection hardening

---

## Project Structure

```
LEXIS/
├── backend/                  # FastAPI backend — agents, orchestration, API
│   ├── agents/                # Orchestrator + 6 feature agents + confirmation agent
│   │   ├── orchestrator/          # Coordinates all agent execution
│   │   ├── rights_agent/
│   │   ├── document_drafter/
│   │   ├── document_analyzer/
│   │   ├── scam_detection/
│   │   ├── filing_guide/
│   │   ├── vault_deadline/
│   │   └── confirmation_agent/    # Bounded retry/loopback verification
│   ├── core/
│   │   ├── scratchpad/            # Shared per-request scratchpad
│   │   ├── memory/                # Persistent memory layer
│   │   ├── llm_client/            # OpenAI client wrapper (mini/full switch)
│   │   └── config/                # Settings, model selection logic
│   ├── api/
│   │   ├── routes/                # chat, vault, auth, agents endpoints
│   │   └── middleware/            # auth, rate limiting, prompt-injection guard
│   ├── services/
│   │   ├── vault/                 # Vault & Deadline Agent — document storage + deadline reminders (NOT the excluded future-scope forensic Evidence Vault — see Future Scope section)
│   │   ├── notifications/         # Deadline notification service
│   │   └── auth/                  # Custom OTP + JWT auth service
│   ├── security/               # Track A: encryption, API hardening, injection defense
│   ├── models/                 # Pydantic schemas
│   ├── db/                     # DB session/engine setup
│   ├── tests/
│   ├── utils/
│   ├── main.py                 # FastAPI entrypoint
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/                 # React (Vite) frontend
│   ├── src/
│   │   ├── components/         # chat/, vault/, dashboard/, common/
│   │   ├── pages/               # Home, Chat, Vault, Login
│   │   ├── hooks/
│   │   ├── services/            # api.js, firebase.js
│   │   ├── context/             # AuthContext
│   │   └── styles/
│   ├── package.json
│   └── .env.example
│
├── docs/
│   ├── architecture/           # System architecture docs
│   ├── implementation-plan/    # 17 modules total (0–16), no fixed weekly timeline
│   ├── cost-estimates/         # Service-by-service cost breakdown
│   └── api-docs/
│
├── scripts/                  # Setup/deploy helper scripts
└── .github/workflows/        # CI config (placeholder)
```

---

## Local setup

### Local databases (Docker — current default for local dev)
```bash
# Start MongoDB and Redis as local Docker containers (one-time image pull, then instant)
docker compose up mongo-local redis-local -d

# Verify containers are running:
docker compose ps
# Expected: lexis_mongo_local (Up, 0.0.0.0:27017->27017) + lexis_redis_local (Up, 0.0.0.0:6379->6379)

# Stop containers (data in named volumes is preserved):
docker compose down

# Full reset (wipes data volumes too):
docker compose down -v
```

Docker Desktop must be running before these commands. On Windows, open Docker Desktop from the Start menu and wait for the whale icon in the system tray to stop animating (~30s).

**Staging/cloud alternative:** To use MongoDB Atlas + Redis Cloud instead, swap `MONGODB_URI` and `REDIS_URL` in `backend/.env` with your Atlas/Redis Cloud connection strings. No code changes needed — just the two URI values.

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # then set SECRET_KEY, check MONGODB_URI + REDIS_URL match your chosen DB environment
uvicorn main:app --reload 
# → http://localhost:8000/api/v1/health
```

> **Module 7 — One-time setup: Tesseract OCR binary**
> `pytesseract` (installed via `requirements.txt`) is a Python wrapper — it needs the **Tesseract binary** installed separately on your OS.
> This is only required for OCR on **scanned images or image-based PDFs**. Digital PDFs (Word → Save as PDF) use PyMuPDF directly and do **not** need Tesseract. Unit tests mock all OCR calls and run without it.
>
> ```powershell
> # Windows — download the installer from:
> # https://github.com/UB-Mannheim/tesseract/wiki
> # After installing, add Tesseract to your PATH (or set the path in .env)
> ```
> ```bash
> # Linux / WSL
> sudo apt install tesseract-ocr
> # Docker (add to your Dockerfile)
> # RUN apt-get install -y tesseract-ocr
> ```

### Frontend
```bash
cd frontend
npm install

# Create your .env from the example (one-time setup):
copy .env.example .env     # Windows
# cp .env.example .env     # Linux/macOS
# The default VITE_API_BASE_URL=http://localhost:8000 matches the local backend — no edits needed.

npm run dev
# → http://localhost:5173
#   Navigating to / redirects to /login (ProtectedRoute working)
#   After OTP login, dashboard shows 6 feature cards with sidebar navigation
```

---

## Team Tracks

- **Track A** — Security: auth, encryption, API hardening, prompt-injection defense
- **Track B** — (TBD per member assignment)
- **Track C** — (TBD per member assignment)
- **Track D** — (TBD per member assignment)

See `docs/implementation-plan/` for the full 17-module (0–16) breakdown.

---

## Security checklist

- [ ] Prompt-injection hardening on all agents
- [ ] Encryption at rest for sensitive fields
- [x] Vault (Module 10) encryption verified — raw DB read confirmed as ciphertext, not plaintext
- [ ] API-wide rate limiting
- [ ] Audit logging for admin actions and cross-user document access
- [ ] Dependency vulnerability scanning wired into CI
- [ ] Security headers (CSP, HSTS, X-Content-Type-Options, X-Frame-Options)
- [ ] Secrets rotation policy documented, dev/prod fully separated

---

## Future scope (explicitly out of MVP)

- Shield Mode
- Forensic Evidence Vault *(distinct from the Module 10 Vault & Deadline Agent, which is in MVP scope — this excluded item is a full legal-evidence chain-of-custody system, not simple encrypted document storage with reminders)*
- Travel Law Diff Engine
- Digital Legal Twin
- Court portal polling
- ML-based outcome prediction
- Full Lawyer-role feature set (case referrals, verification, consultation booking)

---

## Future Scope — Lawyer Role (Module 13 boundary)

Module 13 scaffolds the lawyer role's permission boundary. The following is a precise account of what is and is not built:

### What IS scaffolded (exists in code today)

| Item | Detail |
|---|---|
| Backend route | `GET /api/v1/lawyer/dashboard` — protected by `require_role(["lawyer"])` |
| Frontend route | `/lawyer` — wrapped in `<ProtectedRoute allowedRoles={['lawyer']} />` |
| Sidebar link | Conditional `⚖️ Lawyer Portal` link, visible only to `role='lawyer'` users |
| Coming Soon UI | `LawyerDashboard.jsx` — amber-accented premium static screen |
| Role-isolation tests | 8 unit tests in `test_lawyer_scaffold.py` verifying the full access matrix |

### What is explicitly NOT built (deferred to a future phase)

| Feature | Why deferred |
|---|---|
| Case referrals | Requires citizen-to-lawyer data pipeline and consent model — out of MVP scope |
| Lawyer verification | Requires admin review workflow and Bar Council API integration |
| Consultation booking | Requires calendar system, notification service, and slot management |

### Why scaffold an empty permission boundary? (architectural rationale)

Establishing the permission boundary in code *before* the feature exists is a deliberate architecture discipline:

1. **Closes the gap now**: The `lawyer` role has been issuable since Module 2. Without a route, a lawyer JWT had no defined landing page — undefined behaviour in an auth system is a security concern.
2. **Single extension point**: Adding real lawyer features later means filling in the route handler body. Without this scaffold, a future session would also need to add the router, register it in `main.py`, add the frontend route, update the auth dependency, write tests, and update docs — a risky multi-file refactor instead of a one-function addition.
3. **Tests run today**: Role-isolation tests are machine-verifiable now and will catch regressions if anyone accidentally grants lawyers access to admin endpoints or vice versa.
4. **Honest documentation**: The README and the Coming Soon screen both state exactly what is and is not built. No evaluator or user can mistake the scaffold for a working feature.

---

## Implementation Deviations from Original Plan

The original `docs/implementation-plan/01_LEXIS_Implementation_Plan.md` was written before the Vault & Deadline Agent was added as Agent 6. Two decisions made during Module 10 intentionally deviate from that original plan. They are documented here so evaluators and future sessions understand these are deliberate, justified choices — not oversights.

### Deviation 1 — Module Numbering Shift

| Original Plan | As-Built |
|---|---|
| Module 10 = Memory & Reflection Layer | Module 10 = Vault & Deadline Agent |
| Module 11 = Admin Panel | Module 11 = Memory & Reflection Layer |
| All subsequent modules shifted by +1 | Total: 17 modules (0–16) instead of 16 |

**Reason:** The Vault & Deadline Agent was added as a 6th core feature agent after the original plan was written. The module table in this README already reflects the as-built numbering.

### Deviation 2 — Encryption Added in Module 10, Not Module 14

The original plan (`§1.2`) explicitly said: *"encryption-at-rest for sensitive documents deferred to Module 13 (Security Hardening Pass)."*

**This was overridden for Module 10, deliberately and for a principled reason:**

Module 14 (Security Hardening) is a *verification and audit pass* — it reviews and proves that security controls already exist. It is not the first moment security is applied. The Vault stores Aadhaar cards, passports, and legal notices — the most sensitive personal data in LEXIS. A document uploaded **today** is stored **today**. If we deferred encryption to Module 14, every vault document uploaded between Modules 10 and 14 would sit as plaintext on disk — readable by anyone with server filesystem access (a compromised host, a cloud provider employee, an attacker with a foothold). There is no safe "encrypt it later" window for data of this sensitivity.

**Module 14 will:**
- Read a raw vault file from disk and verify it is ciphertext, not plaintext ✓
- Audit that the VAULT_ENCRYPTION_KEY is not stored alongside the files ✓
- Check that deleted files are truly gone (hard delete) ✓

Module 14 did **not** enable encryption for the first time — Module 10 did.

### Deviation 3 — Agent Count

The original plan describes "5 core feature agents (Modules 5–9)." LEXIS now has **6 agents** — the Vault & Deadline Agent (Agent 6, Module 10) was added after the original plan was written. This is already reflected throughout the README.

---

## Reflection & Self-Correction (Module 11)

LEXIS performs **bounded self-correction** on every specialist agent output before it reaches the citizen.

### What Self-Correction Means in LEXIS

After a specialist agent (e.g. Rights Explainer) produces a draft answer, the **Confirmation Agent** (a separate LangGraph node) applies a concrete, type-specific validation criterion:

| Agent | Criterion | What a Failure Looks Like |
|---|---|---|
| Rights Explainer | Output contains `[Source: <non-empty>]` citation | Plausible-sounding legal answer with no source — could be hallucinated |
| Document Drafter | No `[FILL IN: ...]` placeholders remaining | Template partially completed — citizen cannot use it as-is |
| Document Analyzer | At least one clause has GREEN/YELLOW/RED label | Analysis ran but produced no actionable risk classification |
| Scam Detection | `SCAM_XXX` pattern ID present OR standard no-match fallback | Alert content generated without DB grounding — may be fabricated |
| Filing Guide | Verified `.gov.in`/`.nic.in` portal URL OR `needs_verification` flag | Filing guidance with no authority URL — citizen has nowhere to go |
| Vault Agent | All dates confidence ≥ 0.70, OR `needs_confirmation: True` | Low-confidence date silently stored as a deadline — could miss a real filing |

### Retry Loop (Max 3 Attempts)

If a criterion fails, the Confirmation Agent returns actionable feedback to the specialist ("Your answer lacks a citation — add `[Source: RTI Act 2005, Section 7]`."). The agent retries. After **3 total attempts**, `retry_counts[intent] >= MAX_RETRIES` → no further retry is requested. The output is wrapped with the honest fallback prefix: *"I wasn't able to fully verify this response — here's what I found, please verify independently."*

This prevents infinite loops while ensuring at least 3 genuine attempts before giving up.

### Cross-Agent Contradiction Detection (Rule C1)

When 2+ agents contribute to the same response (the Module 6 concurrent scenario), the Confirmation Agent runs a cross-agent contradiction check **after** both outputs pass their individual validation. 

**Rule C1 — Legal Act Mismatch:** Extract the primary Indian Act citation from both Rights Explainer and Filing Guide outputs using `r'\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*){0,3}\s+Act\s+\d{4})\b'`. If the first matched Act from each output is different AND neither output uses additive context ("in addition to", "alongside"), flag a contradiction and append an advisory note to the final response.


Example: Rights Agent cites `Consumer Protection Act 2019`, Filing Guide cites `RTI Act 2005` -> contradiction advisory appended.
Both citing `RTI Act 2005` -> no flag.

### Session Memory (Redis)

Every request gets a random UUID `session_id` (not derived from user_id or phone number). The `SessionStore` uses Redis hashes (`lexis:session:{session_id}`) with a 24-hour TTL. `asyncio.Lock` per session prevents concurrent write corruption when parallel agents update the same session. The store degrades gracefully to no-op when Redis is unavailable (agents work without session memory -- just without cross-turn context).

### Reflection Logging (MongoDB, PII-Scrubbed)

Every Confirmation Agent validation pass writes a structured log entry to `reflection_logs` collection:
- `session_id` (random UUID), `timestamp`, `agents_checked`, `pass_fail`, `retry_count`, `rejection_reason`, `contradiction_caught`, `query_length`, `response_length`
- **Never stored:** phone numbers, user_id, query text, agent output text

Queryable by the Admin Dashboard (Module 12) for quality analytics.


---

## Changelog

- `[Module 0]` Project structure scaffolded.
- `[Module 1]` Core Backend Foundation: FastAPI app-factory pattern, async Motor (MongoDB) + Redis connections via lifespan lifecycle, Pydantic Settings config (all values from .env, zero hardcoded secrets), structured JSON logging, CORS restricted to env-configured frontend origin, versioned `/api/v1` router, `GET /health` liveness + `GET /health/db` readiness endpoints, `.env.example` with all required vars documented, venv + `requirements.txt` updated (motor 3.6, redis 5.2, python-json-logger), 5 unit tests — all passing (exit 0).
- `[Module 2]` Authentication & RBAC: OTP-based phone auth with abstract SMS provider (DevLogOTPProvider dev stub, ready for Twilio/MSG91 swap), 6-digit cryptographically random OTP with Redis storage + TTL + constant-time verification, JWT access token (15 min) + refresh token (7 days) via python-jose, FastAPI `get_current_user` dependency + `require_role(["admin"])` factory guard, anonymous session mode (signed JWT, no DB record), Redis-keyed OTP rate limiter (per phone, not per IP), 5 new unit tests (OTP success, wrong-role 403, rate-limit 429, anonymous session, token refresh) — 10/10 tests passing (exit 0).
- `[Local Docker Environment]` Added `docker-compose.override.yml` with `mongo:7` (lexis_mongo_local, port 27017) and `redis:7-alpine` (lexis_redis_local, port 6379) services — named volumes for persistence, no auth (local dev only). Auto-merges with `docker-compose.yml` via Docker Compose override mechanism. Backend `.env` set to local Docker URIs. End-to-end verified 2026-08-20: containers healthy (`docker compose ps`), `/api/v1/health/db` returns `{"status":"ok","mongodb":{"status":"ok"},"redis":{"status":"ok"}}`, full OTP→JWT auth flow completed against real local Mongo/Redis (user document persisted, JWT decoded correctly), 10/10 unit tests passing (exit 0). Local Docker is now the default environment for day-to-day development; Atlas/Redis Cloud remains available for staging by swapping URIs in `.env`.
- `[Module 3]` Frontend Foundation: React 18 + Vite scaffolded (existing placeholder filled), React Router v6 with 8 routes (login + 7 protected pages), Axios instance with `VITE_API_BASE_URL` env variable + request interceptor (JWT Bearer header from localStorage) + response interceptor (401 → logout + redirect), two-step OTP login flow wired to real Module 2 backend endpoints, `AuthContext` (React Context + localStorage persistence), `ProtectedRoute` component, shared `AppLayout` (sticky header, dark sidebar, main content `<Outlet>`, footer), `Home` dashboard with 6 feature cards, 6 placeholder feature pages. Vite dev server verified: starts cleanly in ~1100ms on port 5173.
- `[Module 4]` Orchestrator Agent Core: LangGraph state machine, multi-intent classification, concurrent fan-out via `Send` API, partial failure isolation, cost guardrails (`MAX_LLM_CALLS_PER_REQUEST`), `POST /api/v1/query` endpoint, 21 unit tests — 21/21 passing (exit 0).
- `[Module 5]` Agent 1 — Rights Explainer (Reference Template Agent): Qdrant + BGE-M3 RAG pipeline, 8-topic starter legal knowledge base, hallucination safeguard, citation verification, interactive React chat UI, 5 unit tests — 26/26 total passing (exit 0).
- `[Module 6]` Agent 2 — Document Drafter (+ Mandatory Parallel-Execution Milestone): Clause-based templates (RTI, Legal Notice, Consumer Complaint), multi-turn questionnaire, PDF/DOCX export, per-user access control, validated parallel execution milestone, 6 unit tests — 32/32 total passing (exit 0).
- `[Module 7]` Agent 3 — Document Analyzer: Secure file upload (allowlist + magic-byte validation), PyMuPDF + Tesseract OCR pipeline, rule-based + LLM-assisted clause risk classifier (GREEN/YELLOW/RED), bilingual Hindi/English rewriter, reusable per-user secure storage, orchestrator ANALYZE intent wired, side-by-side frontend UI, 10 unit tests — 42/42 total passing (exit 0).
- `[Module 8]` Agent 4 — Scam Detection Engine: 17-pattern seed DB (MongoDB + Qdrant `scam_patterns`), keyword fast-path + BGE-M3 semantic search, DB-grounded alert generation (0 LLM fabrication), orchestrator SCAM intent wired, premium alert-card frontend UI, 5 unit tests — 47/47 total passing (exit 0).
- `[Module 9]` Agent 5 — Complaint Filing Guide: Exact-match filing authority DB (RTI, Consumer, Legal Notice), Module 6 → 9 handoff via draft_id (no re-entry), orchestrator FILING intent wired, premium "Where to File" frontend UI, 5 unit tests — 52/52 total passing (exit 0).
- `[Module 10]` Agent 6 — Vault & Deadline Agent: AES-256-GCM encryption at rest, OCR/date extraction (Module 7 reuse), LLM date extraction with confidence flagging, citizen confirmation flow, APScheduler daily job, proactive Document Drafter invocation at T-30/15/3, email notifications, hard delete, 13 unit tests — 65/65 total passing (exit 0).
- `[Module 11]` Memory & Reflection Layer: Redis session store (concurrent-safe, UUID-keyed, PII-free), Confirmation Agent (per-agent validation criteria), bounded retry loop (max 3 retries → honest fallback), cross-agent contradiction check (Rule C1: Legal Act Mismatch), PII-scrubbed MongoDB reflection log, 8 unit tests — 73/73 total passing (exit 0).
- `[Module 12]` Admin Panel: Admin-only protected routes (`require_role(["admin"])`), real reflection log analytics (all 6 agents, zero dummy numbers), user management (suspend/reactivate), moderation queue (Confirmation Agent fallbacks), dark React dashboard (`/admin`), 18 unit tests — 91/91 total passing (exit 0).
- `[Module 13]` Lawyer Role Scaffold: Established the lawyer-role permission boundary as a documented, intentional MVP boundary — not a bug or missing feature. Backend: `GET /api/v1/lawyer/dashboard` protected by `require_role(["lawyer"])`; returns structured Coming Soon JSON with three planned features (case referrals, lawyer verification, consultation booking) each explicitly marked "Not implemented — future phase only". Frontend: `LawyerDashboard.jsx` + `LawyerDashboard.css` (amber-accented premium Coming Soon screen, distinct from citizen teal and admin sky-blue); `/lawyer` route wrapped in `<ProtectedRoute allowedRoles={['lawyer']} />`; conditional `⚖️ Lawyer Portal` sidebar link visible only to lawyer-role users. Role-isolation verified: lawyer JWT → 403 on admin routes; user/admin/anonymous JWT → 403 on lawyer route; lawyer JWT → 200 on lawyer route; no JWT → 401 on both. Scaffold honesty test confirms response status is `coming_soon` and every feature description contains "Not implemented". 8 new unit tests (`test_lawyer_scaffold.py`) — **99/99 total unit tests passing (exit code 0)**.
- `[Module 13B]` Enhanced Auth & Profile: Email OTP verification (optional/secondary channel reusing core OTP generator + digest verification, Redis rate-limiting, EmailProvider interface with dev-console logging), User schema extension with `email`, `email_verified`, and `profile` sub-document (`full_name`, `address`, `preferred_language` enum: en/hi/mr, `date_of_birth`, `profile_picture_url`, `notification_preference` enum: sms/email/both), GET & PATCH `/api/v1/users/me/profile`, image-restricted profile picture upload via `SecureStorageService`, frontend `ProfileSetup` & `Settings` pages, deadline reminder scheduler wired to user `notification_preference`, cascading account deletion (`DELETE /api/v1/users/me` removes user, vault documents metadata & disk files, vault deadlines), data export (`GET /api/v1/users/me/export` JSON dump), 8 new unit tests (`test_module_13b.py`) — **107/107 total unit tests passing (exit code 0)**.

---

## 🤝 Team Collaboration & Git Workflow

For detailed rules on branch strategy, feature branching, resolving push conflicts, and main release merges, refer to the [Team Git Workflow Guide](GIT_WORKFLOW.md).
