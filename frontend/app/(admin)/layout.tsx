import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";
import AdminNavBar from "@/components/admin/AdminNavBar";

// Server-side RBAC guard for every /(admin)/* route, mirroring
// app/(client)/[plant_id]/layout.tsx's pattern (that file is
// shared/off-limits - this is a new, sibling layout for the admin route
// group instead of an edit to it).
//
// Defense in depth only, same caveat as lib/session.ts documents: the
// JWT decode here is unverified, so this is UX-only route gating. The
// real enforcement is every /admin/* endpoint's admin_common.require_global
// (or require_global_or_department/require_global_admin_or_department,
// for the billing/leads/offtake/logistics/mrv routers a dept_user can
// reach) 403ing everyone else server-side - this layout just stops a
// tenant_read (or logged-out) user from ever seeing the admin shell
// render in the first place.
//
// A dept_user is admitted here regardless of which department -
// proxy.ts (frontend/proxy.ts) already redirected them to /403 before
// this layout renders if the specific page isn't theirs.
export default async function AdminLayout({ children }: { children: ReactNode }) {
  const session = await getSession();

  if (!session) {
    redirect("/login");
  }
  if (
    session.role !== "global_admin" &&
    session.role !== "global_read" &&
    session.role !== "dept_user"
  ) {
    redirect("/403");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <AdminNavBar role={session.role} department={session.department} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
