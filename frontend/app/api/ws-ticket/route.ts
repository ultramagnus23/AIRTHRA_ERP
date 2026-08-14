// GET /api/ws-ticket - the single deliberate exception to "the JWT
// never reaches browser JS" (see lib/session.ts). Browsers can't attach
// a custom Authorization header to a WebSocket handshake, and
// api/routers/ws.py documents exactly this fallback: a `?token=` query
// param. This route reads the httpOnly cookie server-side (proving the
// caller already holds a valid session cookie for this origin) and
// hands back the raw token for lib/ws.ts to use immediately when
// opening the socket. Nothing else in the app should ever read or log
// this value.
import { NextResponse } from "next/server";
import { getRawToken, getSession } from "@/lib/session";

export async function GET() {
  const session = await getSession();
  const token = await getRawToken();
  if (!session || !token) {
    return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
  }
  return NextResponse.json({ token });
}
