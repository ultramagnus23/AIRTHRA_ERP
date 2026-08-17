// Direct-to-FastAPI client for the /invite/[token] page.
//
// Same reasoning as lib/driverApi.ts: NOT routed through
// /api/backend/[...path]/route.ts, because that proxy attaches the
// httpOnly-cookie JWT, and a visitor accepting an invite has no session
// yet - the whole point of this page is to create one. FastAPI's own
// per-token rate limiting (api/ratelimit.py, reused generically by
// api/routers/admin_tenants.py's invite endpoints) is what protects this
// surface, not the proxy.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class InviteApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function inviteRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    throw new InviteApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export interface InviteDetails {
  email: string;
  role: string;
}

export function getInvite(token: string) {
  return inviteRequest<InviteDetails>(`/invites/${encodeURIComponent(token)}`);
}

export function acceptInvite(token: string, password: string) {
  return inviteRequest<{ status: string }>(`/invites/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}
