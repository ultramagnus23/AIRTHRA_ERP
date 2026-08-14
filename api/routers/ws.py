"""WS /ws/{plant_id} - live readings fan-out.

Auth for the handshake: Authorization: Bearer <jwt> header if present,
else a `token` query param (browsers/most WS clients can't set custom
headers as easily as native clients, so the query param is the practical
fallback - same pattern used by e.g. Grafana live/websocket panels).

Unauthorized/unauthenticated connections are rejected with a genuine
HTTP-level status code (401/403) via Starlette's websocket denial-response
extension (`send_denial_response`), sent *before* accepting the socket -
not a post-accept close frame. Uvicorn's websockets and wsproto protocol
implementations both support this extension (verified against the
uvicorn 0.34 install in this repo's venv).
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket
from starlette.responses import PlainTextResponse

from ..deps import decode_user
from ..mqtt_bridge import registry

router = APIRouter(tags=["ws"])


def _extract_token(ws: WebSocket) -> str | None:
    auth = ws.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    token = ws.query_params.get("token")
    if token:
        return token
    return None


@router.websocket("/ws/{plant_id}")
async def ws_readings(websocket: WebSocket, plant_id: str) -> None:
    token = _extract_token(websocket)
    if not token:
        await websocket.send_denial_response(
            PlainTextResponse("missing bearer token", status_code=401)
        )
        return

    try:
        user = decode_user(token)
    except Exception:
        await websocket.send_denial_response(
            PlainTextResponse("invalid or expired token", status_code=401)
        )
        return

    if not user.is_global and plant_id not in user.plant_ids:
        await websocket.send_denial_response(
            PlainTextResponse(
                f"user is not authorized for plant '{plant_id}'", status_code=403
            )
        )
        return

    await websocket.accept()
    await registry.register(plant_id, websocket)
    try:
        while True:
            # We don't expect client->server traffic, but we must keep
            # consuming the receive queue so a client disconnect is
            # observed (raises WebSocketDisconnect) rather than leaking
            # the registry entry.
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        await registry.unregister(plant_id, websocket)
