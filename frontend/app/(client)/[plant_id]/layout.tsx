import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";
import ClientNavBar from "@/components/ClientNavBar";

// Server-side RBAC + plant-scoping guard for every /[plant_id]/* route.
//
// This is the "defense in depth" check called out in the brief: even
// though api/deps.py's require_plant_access already returns a hard 403
// for any request whose JWT plant_ids don't cover the requested
// plant_id, a tenant user should never even see the shell of a
// dashboard for a plant outside their JWT. Checks:
//   1. role must be tenant_read, global_admin, or global_read.
//      global_admin/global_read are let in deliberately (not just
//      tenant_read) so admins can open any plant's live view from the
//      Fleet page for remote debugging - api/deps.py's
//      require_plant_access already lets user.is_global through with no
//      plant check, so this mirrors the real backend boundary rather
//      than adding a stricter one.
//   2. for tenant_read only: plant_id (the URL param) must be in the
//      JWT's plant_ids - global roles have no plant_ids and aren't
//      scoped, so this check is skipped for them.
//
// Both are UX-only, per lib/session.ts's caveat about unverified decode
// - the actual enforcement happens server-side in FastAPI on every call
// the /api/backend proxy forwards.
export default async function ClientPlantLayout({
  children,
  params,
}: LayoutProps<"/[plant_id]">) {
  const { plant_id } = await params;
  const session = await getSession();

  if (!session) {
    redirect(`/login?next=/${plant_id}`);
  }
  const isGlobal = session.role === "global_admin" || session.role === "global_read";
  if (session.role !== "tenant_read" && !isGlobal) {
    redirect("/");
  }
  if (!isGlobal && !session.plantIds.includes(plant_id)) {
    redirect("/403");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <ClientNavBar plantId={plant_id} plantIds={session.plantIds} isAdmin={isGlobal} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
