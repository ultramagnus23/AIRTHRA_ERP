"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout } from "@/lib/api";

const TABS = [
  { href: "", label: "Live" },
  { href: "/history", label: "History" },
  { href: "/compliance", label: "Compliance" },
  { href: "/alarms", label: "Alarms" },
  { href: "/events", label: "Events" },
  { href: "/pid", label: "P&ID" },
];

export default function ClientNavBar({
  plantId,
  plantIds,
}: {
  plantId: string;
  plantIds: string[];
}) {
  const pathname = usePathname();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-4">
          <span className="text-sm font-semibold text-slate-900">Airthra</span>
          {plantIds.length > 1 ? (
            <select
              defaultValue={plantId}
              onChange={(e) => router.push(`/${e.target.value}`)}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              {plantIds.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-sm text-slate-500">{plantId}</span>
          )}
        </div>
        <button
          onClick={handleLogout}
          className="text-sm text-slate-500 hover:text-slate-900"
        >
          Sign out
        </button>
      </div>
      <nav className="mx-auto flex w-full max-w-6xl gap-1 overflow-x-auto px-4 pb-2">
        {TABS.map((tab) => {
          const href = `/${plantId}${tab.href}`;
          const active = pathname === href;
          return (
            <Link
              key={tab.href}
              href={href}
              className={`rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap ${
                active
                  ? "bg-slate-900 text-white"
                  : "text-slate-600 hover:bg-slate-100"
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
