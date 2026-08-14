"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout } from "@/lib/api";

const TABS = [
  { href: "/vendors", label: "Vendors" },
  { href: "/materials", label: "Materials" },
  { href: "/quotations", label: "Quotations" },
  { href: "/projects", label: "Projects" },
  { href: "/drawings", label: "Drawings" },
  { href: "/boms", label: "BOMs" },
  { href: "/pos", label: "POs" },
  { href: "/grn", label: "GRN" },
  { href: "/invoices", label: "Invoices" },
  { href: "/inventory", label: "Inventory" },
  { href: "/jobs", label: "Jobs" },
  { href: "/qc", label: "QC" },
  { href: "/dispatch", label: "Logistics" },
];

export default function ErpNav({ role }: { role: string }) {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="border-b border-teal-900 bg-teal-950">
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold tracking-wide text-teal-50">
            Airthra ERP
          </span>
          <span className="rounded bg-teal-800 px-2 py-0.5 text-xs text-teal-100">{role}</span>
        </div>
        <button onClick={handleLogout} className="text-sm text-teal-200 hover:text-white">
          Sign out
        </button>
      </div>
      <nav className="mx-auto flex w-full max-w-7xl gap-1 overflow-x-auto px-4 pb-2">
        {TABS.map((tab) => {
          const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors ${
                active ? "bg-teal-600 text-white" : "text-teal-200 hover:bg-teal-900 hover:text-white"
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
