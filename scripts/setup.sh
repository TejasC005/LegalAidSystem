#!/bin/bash
# One-shot local dev bootstrap: installs backend + frontend deps
set -e
echo "Setting up backend..."
cd backend && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt && cd ..
echo "Setting up frontend..."
cd frontend && npm install && cd ..
echo "Done. Copy .env.example -> .env in both backend/ and frontend/, then fill in keys."

