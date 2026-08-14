// GET /api/session - lets client components read the (non-sensitive)
// decoded session claims without ever touching the httpOnly cookie's
// raw token value. Used by client-side RBAC guards for defense-in-depth
// UI decisions (e.g. hiding a plant switcher entry the user's JWT
// doesn't actually cover) on top of the server-side check every
// (client)/[plant_id]/layout.tsx already performs.
import { NextResponse } from "next/server";
import { getSession } from "@/lib/session";

export async function GET() {
  const session = await getSession();
  if (!session) {
    return NextResponse.json({ authenticated: false }, { status: 401 });
  }
  return NextResponse.json({
    authenticated: true,
    role: session.role,
    plantIds: session.plantIds,
    userId: session.userId,
  });
}
