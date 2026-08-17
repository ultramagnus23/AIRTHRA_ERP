"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout } from "@/lib/api";

// Mirrors ClientNavBar.tsx's detached floating pill pattern exactly (same
// grid-cols-[1fr_auto_1fr] zones, glass background, centered serif
// wordmark) so the whole product reads as one system, per DESIGN.md's
// "one brand, one palette" rule. The only intentional difference is the
// small mono "ADMIN" eyebrow tag under the wordmark, so a user can never
// confuse this shell with the client dashboard or ERP workspace even
// though they share the same "Airthra." mark.
const LEFT_TABS = [
  { href: "/fleet", label: "Fleet" },
  { href: "/triage", label: "Triage" },
  { href: "/metrics", label: "Metrics" },
  { href: "/logistics", label: "Logistics" },
];
const RIGHT_TABS = [
  { href: "/risk", label: "Risk" },
  { href: "/billing", label: "Billing" },
  { href: "/mrv", label: "MRV Export" },
  { href: "/tenants", label: "Tenants" },
];

export default function AdminNavBar({ role }: { role: string }) {
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
        className={`relative rounded-full px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors duration-150 ${
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
          height: "var(--nav-h)",
          background: "var(--glass-bg)",
          boxShadow: "var(--shadow-md)",
        }}
        className="mx-auto grid w-full max-w-6xl grid-cols-[1fr_auto_1fr] items-center gap-4 rounded-full border border-hair px-6 backdrop-blur-md backdrop-saturate-150"
      >
        {/* left zone */}
        <div className="flex items-center gap-1 justify-self-start">
          <span className="mr-2 hidden rounded-full border border-line px-2.5 py-0.5 font-mono text-xs text-mist sm:inline">
            {role}
          </span>
          <nav className="hidden items-center gap-1 md:flex">{LEFT_TABS.map(tabLink)}</nav>
        </div>

        {/* center wordmark + eyebrow */}
        <div className="flex flex-col items-center justify-self-center">
          <Link href="/fleet" className="font-display text-lg font-medium text-fg">
            Airthra<span className="text-copper">.</span>
          </Link>
          <span className="mt-0.5 font-mono text-[10px] tracking-[0.15em] text-mist uppercase">
            Admin
          </span>
        </div>

        {/* right zone */}
        <div className="flex items-center gap-1 justify-self-end">
          <nav className="hidden items-center gap-1 md:flex">{RIGHT_TABS.map(tabLink)}</nav>
          <button
            onClick={handleLogout}
            className="ml-2 text-sm text-mist transition-colors duration-150 hover:text-fg"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* mobile: full tab row beneath the pill, mirroring ClientNavBar */}
      <nav className="mt-2 flex justify-center gap-1 overflow-x-auto md:hidden">
        {[...LEFT_TABS, ...RIGHT_TABS].map(tabLink)}
      </nav>
    </div>
  );
}
