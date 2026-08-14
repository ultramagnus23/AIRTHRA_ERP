"""Standalone FastAPI app factory for the P5 ERP routers, used only by
tests/p5_gate.py (and available for ad-hoc local runs).

This intentionally does NOT touch api/main.py - per the P5 phase boundary,
other concurrently-developed phases (P3/P4/P6/P7) own that file, and
wiring app.include_router(...) into the real app is a separate integration
step (see the exact lines to add, reported at the end of the P5 task).
This module exists so the gate script has something real to run against
the live Docker stack without a merge conflict on main.py.
"""
from __future__ import annotations

from fastapi import FastAPI

from .routers import auth
from .routers import (
    erp_boms, erp_drawings, erp_grn, erp_invoices, erp_materials,
    erp_pos, erp_projects, erp_quotations, erp_tasks, erp_vendors,
)


def build_app() -> FastAPI:
    app = FastAPI(title="Airthra P5 ERP (standalone gate/dev app)")
    app.include_router(auth.router)
    app.include_router(erp_vendors.router)
    app.include_router(erp_materials.router)
    app.include_router(erp_projects.router)
    app.include_router(erp_tasks.router)
    app.include_router(erp_quotations.router)
    app.include_router(erp_drawings.router)
    app.include_router(erp_boms.router)
    app.include_router(erp_pos.router)
    app.include_router(erp_grn.router)
    app.include_router(erp_invoices.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = build_app()

if __name__ == "__main__":
    import asyncio
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import uvicorn

    from . import config as _config

    uvicorn.run(app, host=_config.API_HOST, port=_config.API_PORT, log_level="info")
