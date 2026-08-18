// Department-scoped route gate for dept_user sessions. Runs before every
// (erp)/(admin) page renders and redirects a dept_user away from a page
// outside their one business function - see lib/departments.ts for the
// department -> page-list mapping this enforces, which mirrors the
// backend's api/routers/erp_*.py and api/routers/admin_*.py
// require_department(...)/require_global_or_department(...) calls.
//
// Same UX-only caveat as lib/session.ts: the JWT is decoded, not
// verified, here (Proxy has no access to JWT_SECRET, which is the
// FastAPI api's secret). The real enforcement is every gated endpoint's
// 403 server-side; this only stops a dept_user from ever seeing a page
// their JWT can't act on render in the first place.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { AUTH_COOKIE, decodeSessionToken } from "@/lib/session";
import { departmentAllowsPath } from "@/lib/departments";

export function proxy(request: NextRequest) {
  const session = decodeSessionToken(request.cookies.get(AUTH_COOKIE)?.value);

  if (session?.role === "dept_user" && session.department) {
    const { pathname } = request.nextUrl;
    if (!departmentAllowsPath(session.department, pathname)) {
      return NextResponse.redirect(new URL("/403", request.url));
    }
  }

  return NextResponse.next();
}

// Next.js statically analyzes this array at build time (its own docs:
// "matcher values need to be constants... dynamic values are ignored"),
// so this is a literal, not computed from lib/departments.ts's page
// lists at runtime - it MUST be kept in sync with every page listed in
// DEPARTMENT_ERP_PAGES/DEPARTMENT_ADMIN_PAGES there by hand.
export const config = {
  matcher: [
    "/boms", "/boms/:path*",
    "/drawings", "/drawings/:path*",
    "/projects", "/projects/:path*",
    "/jobs", "/jobs/:path*",
    "/qc", "/qc/:path*",
    "/vendors", "/vendors/:path*",
    "/materials", "/materials/:path*",
    "/hardware", "/hardware/:path*",
    "/pos", "/pos/:path*",
    "/grn", "/grn/:path*",
    "/inventory", "/inventory/:path*",
    "/invoices", "/invoices/:path*",
    "/quotations", "/quotations/:path*",
    "/dispatch", "/dispatch/:path*",
    "/billing", "/billing/:path*",
    "/leads", "/leads/:path*",
    "/offtake", "/offtake/:path*",
    "/logistics", "/logistics/:path*",
    "/mrv", "/mrv/:path*",
  ],
};
