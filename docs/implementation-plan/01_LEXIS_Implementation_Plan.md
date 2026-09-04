# LEXIS — MVP Implementation Plan
### Autonomous Multi-Agent Legal Aid System for Indian Citizens
**Status:** Module 0 (project scaffold) complete. This plan covers Modules 1–15.

---

## 0. How to use this document

You are a beginner, so this plan is written as a **guided build order**, not just a spec. Every module has four parts:

- **What you're building** — plain-English description
- **Why this exists** — the reasoning, so you understand the system instead of just typing commands
- **Build steps** — the actual sequence
- **Security checkpoint** — what to lock down at this stage (never skipped, just scoped to what's relevant right now)

You will not read this whole document at once and build blind. For **each module**, you take the matching prompt from `02_Antigravity_Master_Prompts.md`, paste it into Antigravity, let it build, review the diff, test it, then update `README.md` before moving to the next module. One module = one Antigravity session = one README update = one git commit.

---

## 1. Two decisions, made up front

### 1.1 Agent-by-agent or all-at-once?

**Decision: agent-by-agent, sequentially. Not simultaneous.**

Reasoning, since you asked directly:

- Every one of your 5 feature agents (Rights, Drafter, Analyzer, Scam Detection, Filing Guide) follows the **same underlying shape**: Orchestrator routes to it → it uses a tool/knowledge source → it produces output → the Reflection layer checks it. If you build all 5 at once, and your pattern has a flaw (wrong state shape, bad prompt structure, broken retry logic), you now have **5 broken things** to fix, each slightly differently, because Antigravity will have improvised differently in each parallel session.
- If you build **one agent completely first** (Module 5, Rights Explainer — chosen because it's the simplest: no file upload, no OCR, just RAG + citation), you get a working, tested, end-to-end template. Modules 6–9 then become "copy this proven pattern and swap the tool/prompt," which is dramatically faster and far less error-prone than building from scratch each time.
- This also matches how a real engineering team works: build the "reference implementation" once, then fan out.

**If you later add teammates** (per your Track A–D structure), the moment Module 5 is done and stable, Track C members *can* build Modules 6–9 in parallel against the same template — but not before the template exists and is tested.

### 1.2 What "security tracked but cyber part later" means here

You will not ship a product with zero security to a real user, even at MVP stage — so:

- **Built now, in Module 2 (non-negotiable):** password/OTP auth, JWT with rotation, role-based access control (user/admin/lawyer), basic input validation, HTTPS-only cookies.
- **Deferred to Module 13 (deep hardening, done once the product works):** prompt-injection defenses, encryption-at-rest for sensitive documents, rate limiting/abuse prevention, audit logging, dependency vulnerability scanning, security headers, secrets rotation policy.

This is the standard order for a real product: **make it work correctly and safely enough not to leak data → then harden it against attackers** before public launch. Every module below still has a "security checkpoint" — those are the cheap, must-do-now items. Module 13 is where the expensive, dedicated hardening work happens.

---

## 2. Roles model (used everywhere from Module 2 onward)

| Role | MVP Status | What they can do |
|---|---|---|
| **User (citizen)** | Fully functional | Use all 5 agents, view own history, manage own account, optional anonymous mode |
| **Admin** | Fully functional | View system-wide usage/analytics, manage users, moderate flagged content, view agent error logs |
| **Lawyer** | Scaffolded only (future scope) | Role exists in the database and permission system; UI shows a "Coming Soon" panel; no functional lawyer-specific features are built in the MVP |

**Why scaffold Lawyer now instead of adding it later:** retrofitting a new role into an auth system after the fact means touching every protected route again. Defining the role's permission boundary now (even if empty) costs almost nothing and saves a painful migration later — this is a real production practice, not academic padding.

---

## 3. Module-by-module plan

### ✅ Module 0 — Project Structure (done)
Already complete per your scaffold zip.

---

### Module 1 — Core Backend Foundation
**What you're building:** A FastAPI server that boots, connects to MongoDB and Redis, has a health-check endpoint, structured logging, and environment-based config (dev/prod).

**Why this exists:** Every agent, every route, every piece of auth sits on top of this. If this isn't solid, every later bug becomes ambiguous — "is it my agent code or is the DB connection flaky?" Getting a clean, observable foundation first removes that whole category of confusion.

**Build steps:**
1. FastAPI app skeleton with versioned API prefix (`/api/v1`).
2. MongoDB connection (Motor async driver) with a startup/shutdown lifecycle hook.
3. Redis connection (for session cache and rate-limit counters later).
4. `.env`-based config using Pydantic Settings — separate dev/prod values, nothing hardcoded.
5. `/health` and `/health/db` endpoints.
6. Structured JSON logging (so logs are greppable later, and admin dashboards in Module 11 can read them).

**Security checkpoint:** No secrets in code or git. `.env` in `.gitignore`. CORS locked to your frontend origin only (not `*`).

**Definition of done:** Server boots locally and in Docker, `/health` returns 200, DB ping succeeds, no secret is committed anywhere.

---

### Module 2 — Authentication & Role-Based Access Control
**What you're building:** Signup/login (OTP-based, since this is India-facing and phone-first), JWT issuing + refresh/rotation, role field (`user` / `admin` / `lawyer`) on every user, and a permission-check dependency that protected routes use.

**Why this exists:** Nothing else can be safely built until you know *who* is calling an endpoint. This is also the module every future feature depends on — get the role model right here and every later module just plugs into it.

**Build steps:**
1. User schema in MongoDB: phone/email, hashed credentials, role, `is_anonymous` flag, created_at.
2. OTP send/verify flow (stub the SMS provider behind an interface — swap in Sarvam/Twilio/etc. later without touching business logic).
3. JWT access + refresh token issuing, short-lived access token, rotating refresh token.
4. `get_current_user` + `require_role(["admin"])` FastAPI dependencies.
5. Anonymous mode: a user can use the product without a persistent identity (per your original spec) — implemented as a temporary session-scoped identity, not a real account.
6. Basic rate limiting on the OTP endpoint specifically (this one can't wait for Module 13 — OTP endpoints are the #1 abused endpoint on every Indian consumer app).

**Security checkpoint:** Passwords/OTPs never logged. JWT secret from env, rotated per environment. OTP endpoint rate-limited per phone number, not just per IP.

**Definition of done:** A user can sign up, verify OTP, get a token, hit a protected route, and get correctly rejected if their role doesn't match. Admin and Lawyer role slots exist and are assignable (Lawyer just isn't used yet).

---

### Module 3 — Frontend Foundation (React)
**What you're building:** The React app shell — routing, layout, auth pages (login/OTP), protected route wrapper, and a design system baseline (so every later screen looks consistent instead of each agent's UI being visually different).

**Why this exists:** You said you don't know React yet — this module is deliberately scoped as "structure only," no feature logic, so you can learn the shape of the app (pages, routes, how API calls work) before layering 5 different agent UIs on top of it.

**Build steps:**
1. Vite + React 18 project, React Router with route definitions for each future agent page (even if they're placeholder screens right now).
2. Axios instance with base URL from env, auth token interceptor (attaches JWT automatically, handles 401 by redirecting to login).
3. Login/OTP screens wired to Module 2's backend.
4. `ProtectedRoute` component that checks role before rendering (used later for the admin panel).
5. A shared layout: header, sidebar/nav listing the 5 features, footer.
6. Firebase wired only for what you actually need at MVP (likely just hosting or push notifications later — not auth, since you're doing custom JWT/OTP auth).

**Security checkpoint:** JWT stored appropriately (httpOnly cookie preferred over localStorage if your infra allows it — flagged here, finalized in Module 13's hardening pass). No API keys or secrets in frontend bundle.

**Definition of done:** You can log in through the browser, land on a dashboard shell, and see 5 empty placeholder pages for the future agents. Nothing "intelligent" yet — that's intentional.

---

### Module 4 — Orchestrator Agent Core
**What you're building:** The LangGraph-based orchestrator: it receives a citizen's query, classifies intent (which of the 5 features it maps to), maintains a shared scratchpad/state object, and routes to the correct specialist agent. This is the piece that makes LEXIS *agentic* rather than "an LLM wrapper."

**Why this exists:** This is the architectural core of your whole capstone claim. A wrapper calls one prompt and returns text. LEXIS decomposes a goal, holds shared state, routes to specialists, and — from Module 10 onward — reflects and self-corrects. Building this properly now, even with only a stub agent behind it, is what your evaluators will be checking for.

**Build steps:**
1. Define the shared state schema (LangGraph state): citizen query, detected intent, conversation history, scratchpad for intermediate agent outputs, final response, confidence/status flags.
2. Intent classifier node — routes to one of the 5 agent placeholders based on the query.
3. Graph wiring: entry → classify → route → (stub agent) → compile response → exit.
4. A single dummy "echo agent" wired in so you can prove the graph runs end-to-end before real agents exist.
5. API endpoint (`/api/v1/query`) that the frontend can call, which invokes the graph.

**Security checkpoint:** Input length limits and basic sanitization on the incoming query (full prompt-injection defense is Module 13, but a naive length/format guard belongs here so Module 5 isn't built on an unguarded input path).

**Definition of done:** A query typed in the frontend reaches the orchestrator, gets classified, and a stub response returns to the screen. This is your architecture's skeleton, proven alive.

---

### Module 5 — Agent 1: Rights Explainer (the template agent)
**What you're building:** The first real specialist agent — end to end. Citizen asks a rights question → RAG retrieval against your legal knowledge base (Qdrant + BGE-M3 embeddings) → agent drafts a plain-language answer with a cited law section → returned to the frontend with a real UI.

**Why this exists, and why it's first:** This is chosen deliberately as your **reference implementation**. It's the simplest of the 5 features (pure retrieval + generation, no file handling, no OCR, no external directory lookups) — which means every mistake you make here is cheap to fix, and once it's right, Modules 6–9 become adaptation, not invention.

**Build steps:**
1. Stand up Qdrant, load an initial legal knowledge base (start small — a handful of well-known citizen rights topics — you can expand the corpus later without touching code).
2. Embedding pipeline using BGE-M3.
3. Rights Agent node in the LangGraph: retrieves relevant chunks, drafts an answer, attaches citations.
4. Wire this agent into the orchestrator's routing (replacing the stub for this intent).
5. Frontend: a real chat-style UI for this one feature, showing the answer and its cited source.
6. Basic output check: does the answer actually contain a citation? (Full reflection/self-correction loop is Module 10 — this is a cheap placeholder check.)

**Security checkpoint:** RAG retrieval scoped to your own knowledge base only (no arbitrary URL fetching). Citations traceable to a real source in your DB, not hallucinated-looking free text.

**Definition of done:** A citizen can ask "What are my rights if my landlord won't return my deposit?" and get a real, cited, plain-language answer through the actual UI. This is your working proof of concept — treat it as the pattern you'll replicate.

---

### Module 6 — Agent 2: Document Drafter
**What you're building:** Multi-turn agent that asks 4–6 targeted questions, then drafts a submission-ready legal document (RTI, notice, complaint) using a template + clause library, exported as PDF/DOCX.

**Why this exists:** This is your first **multi-turn, stateful** agent (unlike Rights Explainer's single-shot Q&A) — it proves your shared state/scratchpad design from Module 4 actually holds context across multiple turns, which is a core "agentic" requirement, not just a nice feature.

**Build steps:**
1. Template & Clause Engine: structured templates for RTI/notice/complaint types, with fillable clause slots.
2. Multi-turn conversation logic: agent asks questions one at a time, stores answers in scratchpad, knows when it has enough to draft.
3. Document assembly: fill template with collected answers.
4. PDF/DOCX export (server-side generation).
5. Frontend: multi-step conversational form UI + document preview/download.

**Security checkpoint:** Uploaded/generated documents stored per-user, access-controlled (a user can only fetch their own drafts). No document persisted longer than necessary without the user's knowledge — surface a clear retention note in the UI.

**Definition of done:** A citizen answers a few questions and downloads a correctly filled, submission-ready document.

---

### Module 7 — Agent 3: Document Analyzer
**What you're building:** Citizen uploads a document (photo or PDF) → OCR extracts text → risk classifier scores clauses Green/Yellow/Red → agent rewrites risky clauses in plain Hindi/English → annotated copy returned.

**Why this exists:** This is your first agent handling **untrusted file input**, which is a meaningfully different risk profile from text queries — OCR pipelines and file uploads are common attack surfaces, so this module also introduces file-handling discipline the rest of the app will reuse.

**Build steps:**
1. Secure file upload endpoint (type/size validation, virus/malware-safe handling pattern even if full scanning is deferred).
2. OCR pipeline (extract text from image/PDF).
3. Clause-level risk classifier (rule-based + LLM-assisted scoring to start; can be refined later).
4. Plain-language rewrite agent for flagged clauses.
5. Frontend: upload UI + side-by-side annotated view (original vs. risk-flagged plain-language version).

**Security checkpoint:** Strict file type/size allowlist. Uploaded files scanned for type spoofing (don't trust the extension). Files stored in isolated storage, not directly web-accessible by guessable URL.

**Definition of done:** A citizen uploads a rental agreement photo and gets back a clause-by-clause risk-annotated, plain-language version.

---

### Module 8 — Agent 4: Scam Detection Engine
**What you're building:** Citizen describes a suspicious situation → agent matches it against a documented scam-pattern database → returns an alert with the legal reality and recommended action.

**Why this exists:** This is your fastest module to build (pattern matching + a curated DB is much simpler than the previous two), which is intentional pacing — after two heavier modules, this one should move quickly and rebuild momentum.

**Build steps:**
1. Scam Pattern Database: seed with well-documented scams targeting Indian citizens (start with 15–20 real, well-known patterns).
2. Matching logic: semantic similarity between citizen's description and known patterns (reuse your embedding pipeline from Module 5).
3. Alert generation: pattern matched, legal reality, recommended action.
4. Frontend: simple description-in, alert-card-out UI.

**Security checkpoint:** This agent must never itself become a vector for spreading misinformation — every alert must trace back to a curated DB entry, never freeform LLM speculation presented as fact.

**Definition of done:** Describing a known scam pattern (e.g., a fake "digital arrest" call) returns an accurate, sourced alert.

---

### Module 9 — Agent 5: Complaint Filing Guide
**What you're building:** Given a drafted complaint (from Module 6) or a described issue, this agent identifies the correct authority to file with, and returns the filing directory info (portal, address, fees, required documents).

**Why this exists:** This is your integration agent — it's designed to consume output from Module 6 (the drafted document) and close the loop from "citizen has a problem" to "citizen knows exactly where to act." This is where your 5 agents stop being 5 separate tools and start feeling like one coherent system.

**Build steps:**
1. Authority & Filing Directory: structured data — which authority handles which complaint type, portal links, fees, checklist.
2. Filing Guide Agent: takes complaint type/context, matches to the right authority entry.
3. Hand-off logic: if the citizen arrives here from Module 6's drafted document, context carries over automatically (this is your scratchpad/shared-state design proving its value).
4. Frontend: "Where to file" results screen, linkable from the Document Drafter's output.

**Security checkpoint:** Only link to official/verified portals in the directory — this data should be reviewed, not scraped blindly, since a wrong government portal link is a real harm vector.

**Definition of done:** All 5 core features are now live end-to-end. This is your feature-complete MVP core, before hardening and polish.

---

### Module 10 — Memory & Reflection Layer
**What you're building:** Cross-cutting session memory (keeps case context across turns and across agents) and the self-correction loop: a **Confirmation Agent** that checks every agent's output for citations, completeness, and accuracy before it reaches the citizen, with a bounded retry (max 3 attempts).

**Why this exists:** This is the second pillar of your "genuinely agentic" claim (alongside the orchestrator). Without this, LEXIS is 5 independent generate-and-return agents. With it, LEXIS actively checks its own work and retries when it's wrong — this is the single most defensible "not a wrapper" argument you have for evaluation, so build and document it carefully.

**Build steps:**
1. Session memory store (Redis-backed): keyed per conversation, holds recent turns and cross-agent context.
2. Confirmation Agent: a lightweight LLM-based checker node that reviews an agent's draft output against defined criteria per agent type (e.g., Rights Explainer output must cite a real source ID from the DB).
3. Retry loop: if Confirmation Agent rejects an output, the originating agent retries with feedback — hard cap at 3 attempts, after which the system returns a clear "couldn't verify this confidently" response rather than a silently wrong answer.
4. Wire this into all 5 agents from Modules 5–9 (retrofit).
5. Logging: every reflection pass (pass/fail/retry count) logged for the admin dashboard in Module 11.

**Security checkpoint:** Reflection logs must not leak sensitive citizen data into general application logs — scrub PII before logging.

**Definition of done:** You can demo a deliberately ambiguous query and show the retry loop actually triggering — this is a strong demo moment for evaluators.

---

### Module 11 — Admin Panel
**What you're building:** Admin-only dashboard: usage analytics, user management, flagged-content moderation, agent error/reflection logs.

**Why this exists:** A real product needs operators, not just users. This also gives you, as the builder, actual visibility into whether your agents are behaving correctly once real usage starts (including during evaluation/demo).

**Build steps:**
1. Admin-only protected routes (built on Module 2/3's role guard).
2. Usage analytics: queries per agent, success/failure/retry rates (pulled from Module 10's logs).
3. User management: view/suspend users.
4. Moderation queue: flagged outputs (from the Confirmation Agent's rejections) surfaced for human review.
5. Frontend: dashboard with charts and tables.

**Security checkpoint:** Admin routes double-checked against role escalation — a `user`-role JWT must never reach an admin endpoint even with a crafted request.

**Definition of done:** Logging in as admin shows real usage data pulled from actual agent activity, not mock data.

---

### Module 12 — Lawyer Role Scaffold (future scope)
**What you're building:** The Lawyer role becomes selectable/assignable, has its own (currently minimal) dashboard shell, and clearly-labeled "Coming Soon" panels for the features you're intentionally not building yet (case referrals, lawyer verification, consultation booking).

**Why this exists:** This directly matches your stated future-scope boundary — you get credit in your report for architecting for it without spending MVP time building features that aren't required yet.

**Build steps:**
1. Lawyer role fully wired into the permission system (was stubbed in Module 2 — now given a real dashboard route).
2. Placeholder dashboard: "Coming Soon" state, clearly not functional, clearly intentional (not a bug).
3. Document in README exactly what's scaffolded vs. what's deferred, and why (useful for your academic report's "future scope" section).

**Security checkpoint:** A Lawyer-role account must not accidentally inherit Admin permissions, or vice versa — verify role boundaries explicitly with a test per role.

**Definition of done:** Three distinct, correctly-isolated roles exist in the running system.

---

### Module 13 — Security Hardening Pass (the deferred "cyber part")
**What you're building:** The dedicated hardening layer you asked to defer until the core product works: prompt-injection defenses, encryption-at-rest for sensitive documents, rate limiting/abuse prevention across the whole API (not just OTP), audit logging, dependency vulnerability scanning, security headers, and a secrets rotation policy.

**Why this exists, and why it's here and not earlier:** Hardening a moving target wastes effort — you'd secure endpoints that later change shape. Now that Modules 1–12 are feature-complete, this pass secures the *actual, final* attack surface once, properly, instead of five times as the product evolved.

**Build steps:**
1. **Prompt-injection hardening:** input/output guardrails on every agent (system-prompt isolation, refusal to follow instructions embedded in uploaded documents or retrieved content, output filtering).
2. **Encryption at rest:** sensitive fields (documents, OCR text, personal data) encrypted in MongoDB, not just relying on infra-level disk encryption.
3. **Rate limiting:** applied API-wide (not just OTP), tuned per endpoint sensitivity.
4. **Audit logging:** who accessed/changed what, when — especially for admin actions and document access.
5. **Dependency scanning:** run `npm audit` / `pip-audit` (or equivalent), fix high-severity findings, wire into CI (Module 14) so this doesn't rot.
6. **Security headers:** CSP, HSTS, X-Content-Type-Options, etc., on the deployed frontend/backend.
7. **Secrets policy:** rotation plan documented, JWT secret and DB credentials not reused across dev/prod.

**Security checkpoint:** This whole module *is* the checkpoint — treat it as a checklist you tick off item by item, and record the checklist state in README so it's visible for your academic report too.

**Definition of done:** A documented security checklist, fully checked, with evidence (e.g., a rate-limit test, an encryption verification) referenced in README.

---

### Module 14 — Testing, QA, Containerization & Deployment
**What you're building:** Automated tests (unit + integration + a handful of end-to-end flows), Dockerized services, CI via GitHub Actions, and a live deployment on Railway/Render.

**Why this exists:** "It worked when I built it" is not the same claim as "it works, reliably, and I can prove it." This module is what lets you demo confidently and defend the project under questioning.

**Build steps:**
1. Unit tests for core logic (auth, orchestrator routing, each agent's core function).
2. Integration tests for the 5 end-to-end agent flows.
3. Dockerfiles per service + `docker-compose.yml` for local full-stack spin-up.
4. GitHub Actions CI: run tests + dependency scan (from Module 13) on every push.
5. Deploy backend + frontend (Railway/Render), connect to production MongoDB/Redis/Qdrant.

**Security checkpoint:** Production environment variables set correctly (no dev secrets leaking into prod, no debug mode enabled in prod).

**Definition of done:** A public URL exists, all 5 features work on it, and CI is green.

---

### Module 15 — Final Polish, Demo Prep & Documentation
**What you're building:** UX polish pass, seeded demo data, a rehearsed demo script, and finalized documentation (README, architecture doc, your academic submission materials).

**Why this exists:** Evaluation is a presentation event, not just a working system. A rough-edged but well-demoed product often scores better than a technically superior but confusingly presented one.

**Build steps:**
1. UX pass: loading states, error states, empty states — the small things that make a demo feel finished.
2. Seed realistic demo data (sample legal queries, a sample rental agreement to analyze, a known scam script) so your demo isn't typed live from a blank state.
3. Write and rehearse a demo script that deliberately shows the orchestrator routing and the Module 10 reflection/retry loop — these are your strongest "genuinely agentic" evidence points.
4. Finalize README, architecture diagram (you already have this), and cross-check against your Implementation Breakdown Chart for the academic submission.

**Security checkpoint:** Final review — no test/admin credentials hardcoded anywhere, no debug endpoints left exposed.

**Definition of done:** You could hand this to someone cold and they could set it up, use it, and understand it from the README alone.

---

## 4. README tracking convention

Use `03_README_template.md` as your starting `README.md`. Every Antigravity session for a module should end with Antigravity updating the module status table and appending a one-line changelog entry — the master prompts in the next document include this instruction explicitly, so you don't have to remember to ask for it.
