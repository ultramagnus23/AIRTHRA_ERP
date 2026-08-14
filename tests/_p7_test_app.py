"""Minimal FastAPI app wiring in just the P7 admin routers, for
tests/p7_gate.py to drive over real HTTP without touching api/main.py
(banned from edits per the P7 task - other phases own that file and a
separate integration step wires these routers into the real app).

Run standalone via:
    .venv/Scripts/python.exe -m uvicorn tests._p7_test_app:app --host 127.0.0.1 --port 8010
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import FastAPI  # noqa: E402

from api.routers import (  # noqa: E402
    admin_billing,
    admin_fleet,
    admin_logistics,
    admin_metrics,
    admin_mrv,
    admin_risk,
)

app = FastAPI(title="Airthra P7 gate test app")
app.include_router(admin_fleet.router)
app.include_router(admin_metrics.router)
app.include_router(admin_logistics.router)
app.include_router(admin_risk.router)
app.include_router(admin_billing.router)
app.include_router(admin_mrv.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
