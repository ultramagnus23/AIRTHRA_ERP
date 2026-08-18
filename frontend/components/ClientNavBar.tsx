"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout } from "@/lib/api";

// Split across the pill: left/right groups flank a centered serif
// wordmark, mirroring the referenced pill-nav layout (fully rounded
// ends, three-zone grid so the center stays visually centered
// regardless of how much content sits on either side).
const LEFT_TABS = [
  { href: "", label: "Live" },
  { href: "/history", label: "History" },
  { href: "/compliance", label: "Compliance" },
];
const RIGHT_TABS = [
  { href: "/alarms", label: "Alarms" },
  { href: "/events", label: "Events" },
  { href: "/pid", label: "P&ID" },
];

export default function ClientNavBar({
  plantId,
  plantIds,
  isAdmin = false,
}: {
  plantId: string;
  plantIds: string[];
  /** global_admin/global_read viewing a plant from the admin Fleet page,
   * not a scoped tenant_read user - shows a way back to the admin console
   * instead of the (empty, for global roles) plant switcher. */
  isAdmin?: boolean;
}) {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  function tabLink(tab: { href: string; label: string }) {
    const href = `/${plantId}${tab.href}`;
    const active = pathname === href;
    return (
      <Link
        key={tab.href}
        href={href}
        className={`air-track relative rounded-full px-3 py-1.5 text-sm font-medium whitespace-nowrap ${
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
    // will-change: transform promotes this sticky element to its own GPU
    // compositor layer. Without it, a sticky/fixed element carrying
    // backdrop-filter (the blur below) forces the browser to re-sample
    // everything scrolling underneath it on every single frame - a
    // well-documented scroll-jank source, worse the taller the page below
    // it (History, with its long chart + sensor checklist, is exactly the
    // page where this would be most noticeable). Layer promotion lets the
    // browser cache the blurred backdrop as a texture instead.
    <div className="sticky top-4 z-10 mx-4" style={{ willChange: "transform" }}>
      <header
        style={{
          height: "var(--nav-h)",
          background: "var(--glass-bg)",
          boxShadow: "var(--shadow-md)",
          transform: "translateZ(0)",
        }}
        className="mx-auto grid w-full max-w-6xl grid-cols-[1fr_auto_1fr] items-center gap-4 rounded-full border border-hair px-6 backdrop-blur-md backdrop-saturate-150"
      >
        {/* left zone */}
        <div className="flex items-center gap-1 justify-self-start">
          {isAdmin ? (
            <Link
              href="/fleet"
              className="mr-2 rounded-full border border-line px-2.5 py-1 font-mono text-xs text-mist hover:text-fg"
            >
              ← Fleet
            </Link>
          ) : plantIds.length > 1 ? (
            <select
              defaultValue={plantId}
              onChange={(e) => router.push(`/${e.target.value}`)}
              className="mr-2 rounded-full border border-line bg-transparent px-2.5 py-1 font-mono text-xs text-fg"
            >
              {plantIds.map((id) => (
                <option key={id} value={id} className="bg-panel">
                  {id}
                </option>
              ))}
            </select>
          ) : (
            <span className="mr-2 hidden font-mono text-xs text-mist sm:inline">{plantId}</span>
          )}
          <nav className="hidden items-center gap-1 md:flex">{LEFT_TABS.map(tabLink)}</nav>
        </div>

        {/* center wordmark */}
        <Link
          href={`/${plantId}`}
          className="justify-self-center font-display text-lg font-medium text-fg"
        >
          Airthra<span className="text-copper">.</span>
        </Link>

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

      {/* mobile: full tab row beneath the pill, since the pill itself
          hides tabs below md to keep the centered wordmark from crowding.
          Edge-to-edge scroll with the scrollbar hidden and inertial
          snapping - a visible native scrollbar bleeding across the bar
          was the exact thing that made this look broken before. */}
      <nav
        className="air-scroll mt-2 flex snap-x snap-mandatory gap-1 overflow-x-auto px-1 md:hidden"
        aria-label="Plant sections"
      >
        {[...LEFT_TABS, ...RIGHT_TABS].map((t) => (
          <span key={t.href} className="snap-start">
            {tabLink(t)}
          </span>
        ))}
      </nav>
    </div>
  );
}
