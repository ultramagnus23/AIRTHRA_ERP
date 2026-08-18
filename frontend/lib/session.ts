// Server-only session helpers. Import only from Server Components,
// Route Handlers, and middleware.ts - never from a "use client" file
// (the whole point is the JWT never becomes readable to browser JS).
//
// Auth storage decision (documented here once - other route groups
// should follow the same pattern rather than re-deciding it):
//
//   The JWT from POST /auth/login is stored in an httpOnly, sameSite=lax
//   cookie (see app/api/auth/login/route.ts) instead of localStorage.
//   Trade-off: httpOnly cookies are immune to XSS token theft (a
//   compromised dependency can't just `localStorage.getItem` the JWT
//   and exfiltrate it), at the cost of needing a same-origin proxy
//   (app/api/backend/[...path]/route.ts) for every REST call the
//   browser makes, since client JS can't attach the cookie's value as
//   an Authorization header itself. WebSockets are the one deliberate
//   exception: browsers can't set custom headers on the WS handshake,
//   so app/api/ws-ticket/route.ts hands the raw token to same-origin
//   JS *only* for that purpose (see lib/ws.ts). That endpoint is the
//   single controlled leak of the token into JS-land; everything else
//   stays server-side.
//
// Decoding here is UNVERIFIED (no signature check) - this file never
// sees JWT_SECRET, which is api's secret, not the frontend's. Treat any
// role/plant_ids read via this module as UX-only route gating, not a
// security boundary: the FastAPI backend re-validates the signature
// and re-checks plant scoping on every single proxied request via
// require_plant_access (api/deps.py). That's the actual boundary.
import { cookies } from "next/headers";
import type { Department, JwtRole, SessionUser } from "./types";

export const AUTH_COOKIE = "airthra_token";

function base64UrlDecode(input: string): string {
  const padded = input.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  return Buffer.from(padded + pad, "base64").toString("utf-8");
}

/** Decodes (does not verify) a JWT's payload. Returns null if malformed/missing/expired. */
export function decodeSessionToken(token: string | undefined | null): SessionUser | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = JSON.parse(base64UrlDecode(parts[1])) as {
      sub?: string;
      role?: JwtRole;
      plant_ids?: string[];
      department?: Department;
      exp?: number;
    };
    if (!payload.role || !payload.exp) return null;
    if (payload.exp * 1000 < Date.now()) return null; // expired
    return {
      userId: payload.sub ?? "",
      role: payload.role,
      plantIds: payload.plant_ids ?? [],
      department: payload.department ?? null,
      exp: payload.exp,
    };
  } catch {
    return null;
  }
}

/** Reads the session from the incoming request's cookies (Server Components / Route Handlers). */
export async function getSession(): Promise<SessionUser | null> {
  const store = await cookies();
  return decodeSessionToken(store.get(AUTH_COOKIE)?.value);
}

/** Reads the raw JWT (needed only by the backend proxy + ws-ticket route). */
export async function getRawToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(AUTH_COOKIE)?.value ?? null;
}
