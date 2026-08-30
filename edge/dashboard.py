"""Minimal local debugging dashboard - a single-page live view of the
sensors this Pi is actually reading, served straight off local_store.py's
SQLite log. Zero dependency on the cloud (Postgres/MQTT reachability) and
zero extra command for whoever's standing at the Pi: it starts
automatically alongside the daemon's other tasks and is reachable at
http://<pi-ip>:8080 (or http://localhost:8080 on the Pi's own screen, via
Raspberry Pi Connect's Screen Sharing) from the moment the container is up.

Routes: `/` (the live table), `/api/latest` (JSON backing it),
`/api/history/<sensor_id>?limit=N` (recent readings for one sensor), and
`/api/export` (every retained row, as a one-click file download).

Implemented with a hand-rolled asyncio HTTP server (stdlib `asyncio.
start_server` only) rather than pulling in FastAPI/aiohttp - edge/
requirements.txt is deliberately kept small (see its own docstring) since
this whole image only exists to run on the Pi; a handful of read-only
debugging routes doesn't justify a new dependency. Only GET is supported,
which is all a read-only dashboard needs.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    from edge.daemon import Context

logger = logging.getLogger("edge.dashboard")

_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Airthra Edge - Local Debug View</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; background: #0b0f14; color: #e6edf3; margin: 0; padding: 16px; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: #8b949e; font-size: 13px; margin-bottom: 14px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #21262d; }
  th { color: #8b949e; font-weight: 600; position: sticky; top: 0; background: #0b0f14; }
  tr.good { }
  tr.comm_error td.value, tr.out_of_range td.value, tr.frozen td.value { color: #f0883e; font-weight: 600; }
  .flag { font-size: 11px; padding: 2px 6px; border-radius: 10px; background: #21262d; }
  .flag.good { background: #1f6f43; }
  .flag.comm_error, .flag.out_of_range, .flag.frozen { background: #7d2d1a; }
  #status { font-size: 13px; margin-bottom: 10px; }
  #status.ok { color: #3fb950; }
  #status.stale { color: #f0883e; }
  #source-banner { font-size: 14px; font-weight: 700; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; display: none; }
  #source-banner.mock { display: block; background: #7d2d1a; color: #ffdcd1; }
  #source-banner.real { display: block; background: #1f6f43; color: #d1f7e0; }
  .src { font-size: 10px; padding: 1px 5px; border-radius: 8px; margin-left: 6px; }
  .src.mock { background: #7d2d1a; color: #ffdcd1; }
  .src.real { background: #1f6f43; color: #d1f7e0; }
  #export-panel { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 14px; padding: 10px 12px; background: #161b22; border: 1px solid #21262d; border-radius: 8px; }
  #export-panel label { font-size: 12px; color: #8b949e; display: flex; flex-direction: column; gap: 3px; }
  #export-panel input[type="datetime-local"] { background: #0b0f14; color: #e6edf3; border: 1px solid #30363d; border-radius: 4px; padding: 4px 6px; font-size: 12px; }
  #export-btn { display: inline-block; padding: 8px 14px; background: #238636; color: #fff; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: 600; border: none; cursor: pointer; align-self: flex-end; }
  #export-btn:hover { background: #2ea043; }
  #export-clear { background: none; border: none; color: #8b949e; font-size: 12px; text-decoration: underline; cursor: pointer; align-self: flex-end; padding: 8px 0; }
</style>
</head>
<body>
<h1>Airthra Edge - Local Debug View</h1>
<div class="sub" id="plant"></div>
<div id="source-banner"></div>
<div id="export-panel">
  <label>From <input type="datetime-local" id="export-from"></label>
  <label>To <input type="datetime-local" id="export-to"></label>
  <a id="export-btn" href="/api/export" download="airthra_readings_export.json">Download history (JSON)</a>
  <button id="export-clear" type="button">clear range (download everything)</button>
</div>
<div id="status">connecting...</div>
<table>
  <thead><tr><th>Sensor</th><th>Value</th><th>Status</th><th>Source</th><th>Last update</th></tr></thead>
  <tbody id="rows"></tbody>
</table>
<script>
const FLAG_LABEL = {0: "good", 1: "comm_error", 2: "out_of_range", 3: "frozen", 4: "imputed"};
async function refresh() {
  try {
    const res = await fetch("/api/latest");
    const data = await res.json();
    document.getElementById("plant").textContent = "plant: " + data.plant_id + "  |  local rows stored: " + data.local_row_count;

    const banner = document.getElementById("source-banner");
    const anyMock = data.readings.some(r => r.source === "mock");
    if (anyMock) {
      banner.textContent = "SIMULATED DATA - this daemon is running with --mock. These are NOT real sensor readings.";
      banner.className = "mock";
    } else if (data.readings.length > 0) {
      banner.textContent = "REAL SENSOR DATA - reading actual connected hardware.";
      banner.className = "real";
    } else {
      banner.className = "";
    }

    const rows = data.readings.map(r => {
      const label = FLAG_LABEL[r.quality_flag] || "unknown";
      const ageS = (Date.now() - new Date(r.ts).getTime()) / 1000;
      const stale = ageS > 5 ? ' style="opacity:0.5"' : "";
      return `<tr class="${label}"${stale}>
        <td>${r.sensor_id}</td>
        <td class="value">${r.value === null ? "-" : Number(r.value).toFixed(3)}</td>
        <td><span class="flag ${label}">${label}</span></td>
        <td><span class="src ${r.source}">${r.source}</span></td>
        <td>${ageS.toFixed(1)}s ago</td>
      </tr>`;
    }).join("");
    document.getElementById("rows").innerHTML = rows;
    const st = document.getElementById("status");
    st.textContent = "live - last refreshed " + new Date().toLocaleTimeString();
    st.className = "ok";
  } catch (e) {
    const st = document.getElementById("status");
    st.textContent = "lost contact with local daemon: " + e;
    st.className = "stale";
  }
}
refresh();
setInterval(refresh, 1000);

// Date-range picker for the export button - rebuilds its href from the
// two datetime-local inputs whenever either changes, so the browser's
// native "download" behaviour (triggered by the <a download> attribute)
// still works with no page reload or form submit needed.
const exportBtn = document.getElementById("export-btn");
const fromInput = document.getElementById("export-from");
const toInput = document.getElementById("export-to");

function updateExportHref() {
  const params = new URLSearchParams();
  // datetime-local gives local time with no timezone suffix - appending
  // one makes it parse as a real instant rather than being silently
  // interpreted as UTC or the server's zone.
  if (fromInput.value) params.set("from", new Date(fromInput.value).toISOString());
  if (toInput.value) params.set("to", new Date(toInput.value).toISOString());
  const qs = params.toString();
  exportBtn.href = "/api/export" + (qs ? "?" + qs : "");
}
fromInput.addEventListener("change", updateExportHref);
toInput.addEventListener("change", updateExportHref);
document.getElementById("export-clear").addEventListener("click", () => {
  fromInput.value = "";
  toInput.value = "";
  updateExportHref();
});
</script>
</body>
</html>
"""


def _http_response(status: str, content_type: str, body: bytes, extra_headers: str = "") -> bytes:
    headers = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"{extra_headers}"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    return headers + body


async def _handle_client(ctx: "Context", reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        # Drain and ignore headers - this server never reads a body, and
        # nothing here needs any request header's value.
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if line in (b"\r\n", b""):
                break

        parts = request_line.decode("latin-1").split()
        raw_path = parts[1] if len(parts) >= 2 else "/"
        split = urlsplit(raw_path)
        path = unquote(split.path)
        query = {
            unquote(k): unquote(v)
            for k, v in (pair.split("=", 1) for pair in split.query.split("&") if "=" in pair)
        }

        if path == "/" or path == "/index.html":
            writer.write(_http_response("200 OK", "text/html; charset=utf-8", _PAGE.encode("utf-8")))
        elif path == "/api/latest":
            readings = await ctx.local_store.latest_per_sensor()
            body = json.dumps(
                {
                    "plant_id": ctx.cfg.plant_id,
                    "local_row_count": await ctx.local_store.count(),
                    "readings": readings,
                }
            ).encode("utf-8")
            writer.write(_http_response("200 OK", "application/json", body))
        elif path.startswith("/api/history/"):
            sensor_id = path[len("/api/history/"):]
            try:
                limit = max(1, min(int(query.get("limit", "200")), 10_000))
            except ValueError:
                limit = 200
            body = json.dumps(
                {"sensor_id": sensor_id, "readings": await ctx.local_store.history(sensor_id, limit)}
            ).encode("utf-8")
            writer.write(_http_response("200 OK", "application/json", body))
        elif path == "/api/export":
            # Everything currently retained (bounded by LOCAL_RETENTION_DAYS,
            # never unbounded) by default, or a specific ?from=&to= window -
            # the dashboard's "download history" button, with an optional
            # date-range picker. Content-Disposition makes the browser save
            # it as a file instead of just displaying it inline; the
            # <a download> on the button is a redundant hint for the same
            # behaviour.
            start = query.get("from") or None
            end = query.get("to") or None
            body = json.dumps(
                {
                    "plant_id": ctx.cfg.plant_id,
                    "range": {"from": start, "to": end},
                    "readings": await ctx.local_store.export_all(start, end),
                }
            ).encode("utf-8")
            writer.write(
                _http_response(
                    "200 OK",
                    "application/json",
                    body,
                    extra_headers='Content-Disposition: attachment; filename="airthra_readings_export.json"\r\n',
                )
            )
        else:
            writer.write(_http_response("404 Not Found", "text/plain", b"not found"))
        await writer.drain()
    except (asyncio.TimeoutError, ConnectionError):
        pass
    except Exception:
        logger.exception("dashboard: error handling request")
    finally:
        writer.close()


async def dashboard_task(ctx: "Context") -> None:
    """One of the daemon's background tasks (see daemon.py's task list) -
    lives and dies with the daemon process, no separate command needed."""
    server = await asyncio.start_server(
        lambda r, w: _handle_client(ctx, r, w), host="0.0.0.0", port=ctx.cfg.dashboard_port
    )
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    logger.info("dashboard: serving local debug view on %s", addrs)
    async with server:
        await ctx.shutdown.wait()
