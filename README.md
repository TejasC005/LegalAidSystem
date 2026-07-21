# LEXIS — Autonomous Multi-Agent Legal Aid System

LEXIS helps Indian citizens navigate legal issues through a team of
coordinated AI agents — not a single chatbot, but an orchestrated
multi-agent system with shared memory, parallel task execution, and
inter-agent collaboration.

## Project Structure

```
LEXIS/
├── backend/                  # FastAPI backend — agents, orchestration, API
│   ├── agents/                # 7 specialist agents (one folder each)
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
│   │   ├── vault/                 # Evidence Vault storage logic
│   │   ├── notifications/         # Deadline notification service
│   │   └── auth/                  # Firebase auth integration
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
│   ├── implementation-plan/    # 6-week, 15-module plan
│   ├── cost-estimates/         # Service-by-service cost breakdown
│   └── api-docs/
│
├── scripts/                  # Setup/deploy helper scripts
└── .github/workflows/        # CI config (placeholder)
```

## Tech Stack
- **Backend**: FastAPI (Python), OpenAI API (GPT-4o-mini for dev, GPT-4o for demo)
- **Auth**: Firebase Authentication (phone OTP, free tier)
- **Frontend**: React + Vite
- **Hosting**: Render (free tier during build, Starter tier for demo week)
- **DB**: SQLite (dev) via SQLAlchemy — swappable for Postgres later

## Getting Started

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # fill in your keys
uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

## Team Tracks
- **Track A** — Security: auth, encryption, API hardening, prompt-injection defense
- **Track B** — (TBD per member assignment)
- **Track C** — (TBD per member assignment)
- **Track D** — (TBD per member assignment)

See `docs/implementation-plan/` for the full 6-week, 15-module breakdown.
