"""Ephemeral FastAPI app used ONLY by tests/p6_genealogy_gate.py to exercise
the new P6 routers over real HTTP against the live stack, without touching
api/main.py (owned by P2, and other concurrent phases wire their own
routers into it separately). Mounts api.routers.auth (for login, unmodified)
plus the four new P6 routers.

Run standalone with:
  .venv/Scripts/python.exe -m uvicorn tests._p6_test_app:app --port 8010
"""
from __future__ import annotations

from fastapi import FastAPI

from api.routers import auth, genealogy, logistics, production, tally

app = FastAPI(title="Airthra P6 gate test app")

app.include_router(auth.router)
app.include_router(genealogy.router)
app.include_router(production.router)
app.include_router(logistics.router)
app.include_router(tally.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
