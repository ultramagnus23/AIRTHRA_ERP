"""FastAPI app factory / entrypoint.

Run with:  .venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
(from repo root, so `api` is importable as a package).
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

# aiomqtt (via paho-mqtt) registers socket readers/writers with
# loop.add_reader/add_writer, which asyncio's default Windows event loop
# (ProactorEventLoop, since Python 3.8) does not implement - it raises
# NotImplementedError. This only affects the mqtt_bridge background task
# (WS live fan-out); everything else in the API works fine either way.
# Switching to the selector-based policy on Windows fixes it. No-op on
# other platforms.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from . import mqtt_bridge
from .routers import (
    admin_billing,
    admin_fleet,
    admin_logistics,
    admin_metrics,
    admin_mrv,
    admin_risk,
    auth,
    erp_boms,
    erp_drawings,
    erp_grn,
    erp_invoices,
    erp_materials,
    erp_pos,
    erp_projects,
    erp_quotations,
    erp_tasks,
    erp_vendors,
    genealogy,
    logistics,
    plant,
    production,
    tally,
    ws,
)

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = asyncio.Event()
    bridge_task = asyncio.create_task(mqtt_bridge.run_forever(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        bridge_task.cancel()
        try:
            await bridge_task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(title="Airthra P2 API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(plant.router)
app.include_router(ws.router)

# P5 - ERP procurement + engineering
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

# P6 - genealogy, production/QC, logistics, Tally export
app.include_router(genealogy.router)
app.include_router(production.router)
app.include_router(logistics.router)
app.include_router(tally.router)

# P7 - admin platform
app.include_router(admin_fleet.router)
app.include_router(admin_metrics.router)
app.include_router(admin_logistics.router)
app.include_router(admin_risk.router)
app.include_router(admin_billing.router)
app.include_router(admin_mrv.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    # `python -m uvicorn api.main:app` does NOT work reliably for the
    # Windows event-loop-policy fix above: uvicorn's own asyncio.run()
    # creates the event loop as part of Server.run(), which happens
    # *before* this module's import-time policy-setting code would take
    # effect if invoked via the uvicorn CLI/module runner (the app is
    # imported *inside* that already-running loop). Running this file
    # directly (`python -m api.main` / `python api/main.py`) ensures the
    # policy is set before uvicorn.run() creates its loop.
    import uvicorn

    from . import config as _config

    uvicorn.run(app, host=_config.API_HOST, port=_config.API_PORT, log_level="info")
