// Direct-to-FastAPI client for the /driver/[trip_token] page.
//
// Deliberately NOT routed through /api/backend/[...path]/route.ts (see
// lib/api.ts) - that proxy exists to attach the httpOnly-cookie JWT, and
// a driver has no JWT. Per api/routers/logistics.py, ping/stop are
// authenticated by a per-trip token sent as the X-Trip-Token header
// instead, so this file talks to FastAPI directly from the browser.
// api/main.py's dev CORS config already allow-lists localhost:3000.
//
// Backend gap this file works around: there is no GET-trip-by-token
// endpoint (POST /logistics/trips requires a dispatcher JWT and is the
// *creation* call, not something a driver's device can use, and
// GET /logistics/trips/{id}/pings also requires a JWT). A driver link
// therefore cannot resolve state from the token alone. Since every
// token-authenticated endpoint already needs BOTH the trip id (as a path
// param) and the token (as a header), the /driver/[trip_token] route
// segment encodes both, joined by ".": "{trip_id}.{token}". trip_id is a
// UUID and token is secrets.token_urlsafe(32) output, neither of which
// contains ".", so the split below is unambiguous. This is a client-side
// packing convenience only - no business logic, just address book of
// which two opaque strings to send back to the API.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class DriverApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function parseTripToken(segment: string): { tripId: string; token: string } | null {
  const dot = segment.indexOf(".");
  if (dot <= 0 || dot === segment.length - 1) return null;
  return { tripId: segment.slice(0, dot), token: segment.slice(dot + 1) };
}

export interface PingResult {
  trip_id: string;
  ts: string;
  lat: number;
  lon: number;
  speed: number | null;
}

export interface StopResult {
  id: string;
  vehicle_no: string;
  status: string;
  started: string;
  completed: string | null;
}

async function driverRequest<T>(path: string, tripId: string, token: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Trip-Token": token,
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    throw new DriverApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function postPing(
  tripId: string,
  token: string,
  body: { lat: number; lon: number; speed?: number | null },
): Promise<PingResult> {
  return driverRequest<PingResult>(`/logistics/trips/${tripId}/ping`, tripId, token, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function stopTrip(tripId: string, token: string): Promise<StopResult> {
  return driverRequest<StopResult>(`/logistics/trips/${tripId}/stop`, tripId, token, {
    method: "POST",
  });
}
