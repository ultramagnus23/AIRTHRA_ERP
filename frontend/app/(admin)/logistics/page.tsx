"use client";

import { useEffect, useMemo, useState } from "react";
import { getBurnRates, AdminApiError } from "@/lib/admin-api";
import type { BurnRateEntry, BurnRatesResponse } from "@/lib/admin-types";

// Matches the 2-day threshold P6's Grafana KOH-refill alert uses
// (admin_logistics.py's POST /admin/logistics/task webhook fires a task
// at days_remaining < 2) - flagged here in red for visual consistency
// with that alert's meaning, not recomputed independently.
const URGENT_DAYS_THRESHOLD = 2;

type SortKey = "days_remaining" | "fill_pct" | "name";

export default function LogisticsPage() {
  const [data, setData] = useState<BurnRatesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("days_remaining");

  useEffect(() => {
    getBurnRates()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load burn rates"))
      .finally(() => setLoading(false));
  }, []);

  const sorted = useMemo(() => {
    if (!data) return [];
    const rows = [...data.plants];
    rows.sort((a, b) => {
      if (sortKey === "name") return a.name.localeCompare(b.name);
      if (sortKey === "fill_pct") {
        return (a.k2so3.fill_pct ?? Infinity) - (b.k2so3.fill_pct ?? Infinity);
      }
      // days_remaining: nulls (no trend / not draining) sort last
      const av = a.koh.days_remaining ?? Infinity;
      const bv = b.koh.days_remaining ?? Infinity;
      return av - bv;
    });
    return rows;
  }, [data, sortKey]);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-display text-2xl font-light text-fg">Logistics urgency</h1>
        <p className="text-sm text-mist">
          GET /admin/logistics/burn_rates - {data ? data.method : "OLS trend of KOH tank level over the trailing window"}.
        </p>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono text-xs tracking-[0.1em] text-mist uppercase">Sort by:</span>
        {(["days_remaining", "fill_pct", "name"] as SortKey[]).map((k) => (
          <button
            key={k}
            onClick={() => setSortKey(k)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
              sortKey === k ? "bg-rust text-fg" : "bg-midnight text-mist hover:text-fg"
            }`}
          >
            {k === "days_remaining" ? "KOH days remaining" : k === "fill_pct" ? "K2SO3 fill %" : "Plant"}
          </button>
        ))}
      </div>

      {loading && <p className="font-mono text-sm text-mist">Loading...</p>}
      {error && <p className="text-sm text-rust">{error}</p>}

      {data && (
        <div
          className="overflow-x-auto rounded-2xl border border-hair bg-panel"
          style={{ boxShadow: "var(--shadow-sm)" }}
        >
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
              <tr>
                <th className="px-4 py-2">Plant</th>
                <th className="px-4 py-2">KOH level</th>
                <th className="px-4 py-2">KOH trend (%/day)</th>
                <th className="px-4 py-2">KOH days remaining</th>
                <th className="px-4 py-2">K2SO3 fill %</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((p: BurnRateEntry) => {
                const urgent =
                  p.koh.days_remaining !== null && p.koh.days_remaining < URGENT_DAYS_THRESHOLD;
                return (
                  <tr key={p.plant_id} className="border-b border-hair last:border-0">
                    <td className="px-4 py-2">
                      <div className="font-medium text-fg">{p.name}</div>
                      <div className="font-mono text-xs text-mist">{p.plant_id}</div>
                    </td>
                    <td className="px-4 py-2 font-mono text-fg">
                      {p.koh.current_level_pct !== null ? `${p.koh.current_level_pct.toFixed(1)}%` : "-"}
                    </td>
                    <td className="px-4 py-2 font-mono text-fg">
                      {p.koh.trend_pct_per_day !== null ? p.koh.trend_pct_per_day.toFixed(3) : "-"}
                    </td>
                    <td className="px-4 py-2">
                      {p.koh.days_remaining !== null ? (
                        <span
                          className={`inline-flex items-center rounded-md border px-2.5 py-0.5 font-mono text-xs font-medium ${
                            urgent
                              ? "border-rust/40 bg-rust/10 text-rust"
                              : "border-line bg-midnight text-mist"
                          }`}
                        >
                          {urgent && "⚠ "}
                          {p.koh.days_remaining.toFixed(1)}d
                        </span>
                      ) : (
                        <span className="font-mono text-xs text-mist">{p.koh.reason ?? "n/a"}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 font-mono text-fg">
                      {p.k2so3.fill_pct !== null ? `${p.k2so3.fill_pct.toFixed(1)}%` : "-"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
