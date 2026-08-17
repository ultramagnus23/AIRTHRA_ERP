import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";
import ErpNav from "@/components/erp/ErpNav";

// Server-side RBAC guard for every /(erp)/* route, mirroring the
// (client)/[plant_id]/layout.tsx pattern: ERP is run centrally by Airthra
// staff (global_admin/global_read), never by plant-tenant users. This is
// UX-only route gating (lib/session.ts's decode is unverified) - the real
// boundary is erp_deps.py's erp_read_user/erp_admin_user on every request
// the /api/backend proxy forwards.
export default async function ErpLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();

  if (!session) {
    redirect("/login?next=/vendors");
  }
  if (session.role !== "global_admin" && session.role !== "global_read") {
    redirect("/403");
  }

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <ErpNav role={session.role} />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
