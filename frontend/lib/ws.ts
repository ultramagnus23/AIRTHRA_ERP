// Typed WebSocket helper for /ws/{plant_id}.
//
// The browser opens this connection directly to the FastAPI backend
// (NEXT_PUBLIC_WS_BASE) rather than through the Next.js proxy, because
// route handlers can't transparently proxy a WS upgrade. Auth token is
// obtained from /api/ws-ticket first (a same-origin, cookie-authenticated
// route that hands back the raw JWT for this one purpose) and passed as
// the `token` query param, per api/routers/ws.py's documented fallback
// for browser clients that can't set a custom Authorization header on
// the handshake. See lib/session.ts for the full auth writeup.
import type { WsReading } from "./types";

export interface PlantWsHandle {
  close: () => void;
}

export interface PlantWsCallbacks {
  onReadings: (readings: WsReading[]) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
}

/**
 * Connects to /ws/{plant_id} and invokes onReadings for every message.
 * Reconnects with backoff on unexpected close (not on a deliberate
 * .close() from the caller). Returns a handle; call .close() on unmount.
 */
export function connectPlantWs(plantId: string, cb: PlantWsCallbacks): PlantWsHandle {
  let closedByCaller = false;
  let socket: WebSocket | null = null;
  let backoffMs = 1000;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const wsBase = process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:8000";

  async function connect() {
    if (closedByCaller) return;
    let token: string;
    try {
      const res = await fetch("/api/ws-ticket");
      if (!res.ok) throw new Error(`ws-ticket failed: ${res.status}`);
      const body = (await res.json()) as { token: string };
      token = body.token;
    } catch (err) {
      cb.onError?.(err);
      scheduleRetry();
      return;
    }

    const url = `${wsBase}/ws/${encodeURIComponent(plantId)}?token=${encodeURIComponent(token)}`;
    socket = new WebSocket(url);

    socket.onopen = () => {
      backoffMs = 1000;
      cb.onOpen?.();
    };
    socket.onmessage = (event) => {
      try {
        const readings = JSON.parse(event.data) as WsReading[];
        cb.onReadings(Array.isArray(readings) ? readings : [readings]);
      } catch (err) {
        cb.onError?.(err);
      }
    };
    socket.onerror = (err) => {
      cb.onError?.(err);
    };
    socket.onclose = () => {
      cb.onClose?.();
      if (!closedByCaller) scheduleRetry();
    };
  }

  function scheduleRetry() {
    if (closedByCaller) return;
    retryTimer = setTimeout(() => {
      backoffMs = Math.min(backoffMs * 2, 30000);
      connect();
    }, backoffMs);
  }

  connect();

  return {
    close: () => {
      closedByCaller = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    },
  };
}
