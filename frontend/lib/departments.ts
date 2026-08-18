// Single source of truth for what pages each department (api/security.py's
// DEPARTMENTS) can reach, mirroring the backend wiring in
// api/routers/erp_*.py and api/routers/admin_*.py (each file's
// `require_department("...")`/`require_global_or_department(user, "...")`
// call names the same department this file assigns its page to). Used by
// middleware.ts (the actual UX-level gate, redirecting a dept_user away
// from a page their JWT can't act on) and by ErpNav/AdminNavBar (hiding
// tabs a dept_user would just bounce off of).
//
// Same caveat as lib/session.ts: this is UX only. The backend re-enforces
// every one of these on every request regardless of what this file says.
import type { Department } from "./types";

export const DEPARTMENT_ERP_PAGES: Record<Department, string[]> = {
  engineering: ["/boms", "/drawings", "/projects", "/jobs", "/qc"],
  procurement: ["/vendors", "/materials", "/hardware", "/pos", "/grn", "/inventory"],
  finance: ["/invoices"],
  sales: ["/quotations"],
  logistics: ["/dispatch"],
};

export const DEPARTMENT_ADMIN_PAGES: Record<Department, string[]> = {
  engineering: [],
  procurement: [],
  finance: ["/billing"],
  sales: ["/leads", "/offtake"],
  logistics: ["/logistics", "/mrv"],
};

/** First page a dept_user lands on after login / at "/". */
export const DEPARTMENT_HOME: Record<Department, string> = {
  engineering: "/boms",
  procurement: "/vendors",
  finance: "/billing",
  sales: "/leads",
  logistics: "/logistics",
};

function allPagesFor(department: Department): string[] {
  return [...DEPARTMENT_ERP_PAGES[department], ...DEPARTMENT_ADMIN_PAGES[department]];
}

/** True if `pathname` is one of `department`'s pages (exact or a sub-route of one). */
export function departmentAllowsPath(department: Department, pathname: string): boolean {
  return allPagesFor(department).some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/** Every page path gated behind ANY department - used by middleware.ts's matcher. */
export const ALL_DEPARTMENT_PAGES: string[] = (
  Object.keys(DEPARTMENT_ERP_PAGES) as Department[]
).flatMap(allPagesFor);
