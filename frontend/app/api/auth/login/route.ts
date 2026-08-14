// POST /api/auth/login - proxies to FastAPI's POST /auth/login, then
// stores the returned JWT in an httpOnly cookie. See lib/session.ts for
// the full rationale.
import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIE } from "@/lib/session";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body?.email || !body?.password) {
    return NextResponse.json({ detail: "email and password are required" }, { status: 400 });
  }

  const upstream = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: body.email, password: body.password }),
    cache: "no-store",
  });

  const data = await upstream.json().catch(() => ({ detail: "invalid response from API" }));
  if (!upstream.ok) {
    return NextResponse.json(data, { status: upstream.status });
  }

  // Non-sensitive claims are echoed back so the client can redirect
  // immediately without a round-trip to /api/session; the token itself
  // never appears in this JSON body.
  const res = NextResponse.json({ role: data.role, plant_ids: data.plant_ids });
  res.cookies.set(AUTH_COOKIE, data.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    // Mirrors api/config.py's JWT_EXPIRE_MINUTES default (480m = 8h).
    maxAge: 8 * 60 * 60,
  });
  return res;
}
