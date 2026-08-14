import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";
import ClientNavBar from "@/components/ClientNavBar";

// Server-side RBAC + plant-scoping guard for every /[plant_id]/* route.
//
// This is the "defense in depth" check called out in the brief: even
// though api/deps.py's require_plant_access already returns a hard 403
// for any request whose JWT plant_ids don't cover the requested
// plant_id, a tenant user should never even see the shell of a
// dashboard for a plant outside their JWT. Two checks:
//   1. role must be tenant_read (global_admin/global_read belong in the
//      future (admin) route group, not here)
//   2. plant_id (the URL param) must be in the JWT's plant_ids
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
  if (session.role !== "tenant_read") {
    redirect("/");
  }
  if (!session.plantIds.includes(plant_id)) {
    redirect("/403");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <ClientNavBar plantId={plant_id} plantIds={session.plantIds} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
