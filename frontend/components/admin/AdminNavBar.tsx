"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout } from "@/lib/api";

// Visually distinct from ClientNavBar (components/ClientNavBar.tsx) on
// purpose - amber/slate-900 accent vs. the client dashboard's plain
// white/slate bar - so admins and tenants can never mistake one shell
// for the other, per the build brief.
const TABS = [
  { href: "/fleet", label: "Fleet" },
  { href: "/triage", label: "Triage" },
  { href: "/metrics", label: "Metrics" },
  { href: "/logistics", label: "Logistics" },
  { href: "/risk", label: "Risk" },
  { href: "/billing", label: "Billing" },
  { href: "/mrv", label: "MRV Export" },
];

export default function AdminNavBar({ role }: { role: string }) {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="border-b border-amber-900/20 bg-slate-900">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-white">Airthra Admin</span>
          <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-300">
            {role}
          </span>
        </div>
        <button
          onClick={handleLogout}
          className="text-sm text-slate-300 hover:text-white"
        >
          Sign out
        </button>
      </div>
      <nav className="mx-auto flex w-full max-w-6xl gap-1 overflow-x-auto px-4 pb-2">
        {TABS.map((tab) => {
          const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap ${
                active
                  ? "bg-amber-500 text-slate-900"
                  : "text-slate-300 hover:bg-slate-800 hover:text-white"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
