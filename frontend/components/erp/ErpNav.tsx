"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout } from "@/lib/api";

// ERP has far more sections than client/admin (13 links), so rather than
// force them into one line with an internal scrollbar (tried, rendered
// badly - the browser's own scrollbar chrome bled across the bar and
// overlapped the wordmark), this uses two clean rows inside the same
// detached glass pill: row 1 mirrors ClientNavBar's centered-wordmark
// layout exactly, row 2 is a simple centered flex-wrap of every link.
const ALL_TABS = [
  { href: "/vendors", label: "Vendors" },
  { href: "/materials", label: "Materials" },
  { href: "/hardware", label: "Hardware BOM" },
  { href: "/quotations", label: "Quotations" },
  { href: "/pos", label: "POs" },
  { href: "/grn", label: "GRN" },
  { href: "/invoices", label: "Invoices" },
  { href: "/projects", label: "Projects" },
  { href: "/drawings", label: "Drawings" },
  { href: "/boms", label: "BOMs" },
  { href: "/inventory", label: "Inventory" },
  { href: "/jobs", label: "Jobs" },
  { href: "/qc", label: "QC" },
  { href: "/dispatch", label: "Dispatch" },
];

export default function ErpNav({ role }: { role: string }) {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  function tabLink(tab: { href: string; label: string }) {
    const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
    return (
      <Link
        key={tab.href}
        href={tab.href}
        className={`relative rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors duration-150 ${
          active ? "text-fg" : "text-mist hover:text-fg"
        }`}
      >
        {active && (
          <span
            className="absolute inset-0 -z-10 rounded-full bg-midnight"
            style={{ boxShadow: "var(--shadow-sm)" }}
            aria-hidden
          />
        )}
        {tab.label}
      </Link>
    );
  }

  return (
    <div className="sticky top-4 z-10 mx-4">
      <header
        style={{
          background: "var(--glass-bg)",
          boxShadow: "var(--shadow-md)",
        }}
        className="mx-auto flex w-full max-w-6xl flex-col gap-2 rounded-3xl border border-hair px-6 py-3 backdrop-blur-md backdrop-saturate-150"
      >
        {/* row 1: wordmark + eyebrow, role, sign out */}
        <div className="flex items-center justify-between">
          <Link href="/vendors" className="flex items-baseline gap-2 leading-none">
            <span className="font-display text-lg font-medium text-fg">
              Airthra<span className="text-copper">.</span>
            </span>
            <span className="font-mono text-[10px] tracking-[0.2em] text-copper uppercase">ERP</span>
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden font-mono text-[10px] text-mist sm:inline">{role}</span>
            <button
              onClick={handleLogout}
              className="text-sm text-mist transition-colors duration-150 hover:text-fg"
            >
              Sign out
            </button>
          </div>
        </div>

        {/* row 2: every section, centered, wraps freely */}
        <nav className="flex flex-wrap items-center justify-center gap-x-1 gap-y-1 border-t border-hair pt-2">
          {ALL_TABS.map(tabLink)}
        </nav>
      </header>
    </div>
  );
}
