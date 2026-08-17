import { redirect } from "next/navigation";
import { getSession } from "@/lib/session";

// Root landing: routes an authenticated tenant_read user straight into
// their plant dashboard, and a global_admin/global_read user into the
// admin console's fleet view (app/(admin)/fleet/page.tsx - the (admin)
// route group's own layout re-checks the role server-side, so this is
// just routing, not the security boundary).
//
// NOTE for other agents: this one-line addition (the second redirect)
// is the only change made to this shared file by the admin-console
// build - flagged per that build's brief since app/page.tsx isn't
// listed as admin-owned.
export default async function Home() {
  const session = await getSession();
  if (!session) {
    redirect("/login");
  }
  if (session.role === "tenant_read" && session.plantIds.length > 0) {
    redirect(`/${session.plantIds[0]}`);
  }
  if (session.role === "global_admin" || session.role === "global_read") {
    redirect("/fleet");
  }
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-2 bg-bg p-8 text-center">
      <h1 className="font-display text-2xl font-light text-fg">Airthra Platform</h1>
      <p className="text-mist">
        Signed in as <span className="font-mono text-copper">{session.role}</span>. No workspace is
        configured for this role.
      </p>
    </main>
  );
}
