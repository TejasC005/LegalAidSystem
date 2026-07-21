"""
LEXIS Backend Entrypoint
-------------------------
Boots the FastAPI app, wires up the Orchestrator Agent, and exposes
the API routes consumed by the frontend.

Module 0: this is a placeholder entrypoint. Orchestrator wiring and
route registration land in later modules per the implementation plan.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="LEXIS API",
    description="Autonomous multi-agent legal aid system for Indian citizens",
    version="0.0.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # tighten before demo
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "LEXIS backend"}


# TODO (later modules):
# - include_router() calls for chat, vault, auth, agents
# - Orchestrator + scratchpad + memory layer initialization on startup
