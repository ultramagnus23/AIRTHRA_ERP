// Route gate (Next.js 16 renamed "middleware" -> "proxy" - see
// node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md).
// Runs before any page render: redirects unauthenticated visitors to
// /login, and bounces an authenticated non-tenant user away from
// client-dashboard URLs. This is UX-only (unverified JWT decode, see
// lib/session.ts) - the real boundary is FastAPI's require_plant_access
// on every request the /api/backend proxy forwards. The per-plant_id
// check (does THIS user's JWT cover THIS plant_id) happens one layer
// deeper, in app/(client)/[plant_id]/layout.tsx, since proxy doesn't
// get an easy typed match on the dynamic segment here.
import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIE, decodeSessionToken } from "@/lib/session";

// Unlike the old "middleware" convention (which defaulted to the Edge
// runtime and needed an explicit `export const runtime = "nodejs"` for
// decodeSessionToken's Buffer usage to work), "proxy" always runs on
// Node.js - a `runtime` export here is a build error.

const PUBLIC_PATHS = ["/login"];

export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (
    PUBLIC_PATHS.includes(pathname) ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico" ||
    // /driver/[trip_token] is a genuinely unauthenticated route - the
    // driver has no JWT, the per-trip token IS the auth (verified
    // server-side by FastAPI on every request, see
    // api/routers/logistics.py's _verify_trip_token). Do not route it
    // through the JWT-cookie gate below.
    pathname.startsWith("/driver/")
  ) {
    return NextResponse.next();
  }

  const session = decodeSessionToken(req.cookies.get(AUTH_COOKIE)?.value);
  if (!session) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
