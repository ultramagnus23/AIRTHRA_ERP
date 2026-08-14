"use client";

import { useEffect, useState } from "react";
import { getFleet, AdminApiError } from "@/lib/admin-api";
import type { FleetEntry, FleetResponse } from "@/lib/admin-types";

// Fleet map (PRD §5.5 "Admin"): a color-coded table/list view, not a
// real Leaflet/OSM map - documented deviation. react-leaflet isn't in
// package.json and pulling it in (plus tile-provider wiring, plant
// lat/lon isn't returned by GET /admin/fleet today) was judged not
// worth the added dependency/time for a first cut when the PRD itself
// calls a clean color-coded table an acceptable substitute. The health
// colors/thresholds are exactly GET /admin/fleet's payload, rendered
// with zero client-side recomputation.
const COLOR_STYLES: Record<string, string> = {
  green: "bg-emerald-100 text-emerald-800 border-emerald-300",
  yellow: "bg-amber-100 text-amber-800 border-amber-300",
  red: "bg-red-100 text-red-800 border-red-300",
  gray: "bg-slate-100 text-slate-600 border-slate-300",
};

function ColorBadge({ color }: { color: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${
        COLOR_STYLES[color] ?? COLOR_STYLES.gray
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${
          color === "green"
            ? "bg-emerald-500"
            : color === "yellow"
              ? "bg-amber-500"
              : color === "red"
                ? "bg-red-500"
                : "bg-slate-400"
        }`}
      />
      {color}
    </span>
  );
}

export default function FleetPage() {
  const [data, setData] = useState<FleetResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getFleet()
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof AdminApiError ? e.message : "failed to load fleet");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Fleet health</h1>
        <p className="text-sm text-slate-600">
          Cross-plant status, computed server-side by GET /admin/fleet. Table view (see note in
          source) in place of a live map.
        </p>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading fleet status...</p>}
      {error && <p className="text-sm text-red-700">{error}</p>}

      {data && (
        <>
          <div className="rounded-md border border-slate-200 bg-white p-3 text-xs text-slate-500">
            Thresholds: offline after {data.thresholds.offline_threshold_s}s of no readings;
            degraded when &gt;{data.thresholds.degraded_flag_pct}% of readings in the trailing{" "}
            {data.thresholds.degraded_window_s / 60}min are non-good.
          </div>

          <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Plant</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Last reading</th>
                  <th className="px-4 py-2">Flagged % (1h)</th>
                  <th className="px-4 py-2">Reasons</th>
                </tr>
              </thead>
              <tbody>
                {data.fleet.map((p: FleetEntry) => (
                  <tr key={p.plant_id} className="border-b border-slate-100 last:border-0">
                    <td className="px-4 py-2">
                      <div className="font-medium text-slate-900">{p.name}</div>
                      <div className="font-mono text-xs text-slate-500">{p.plant_id}</div>
                    </td>
                    <td className="px-4 py-2">
                      <ColorBadge color={p.color} />
                    </td>
                    <td className="px-4 py-2 text-slate-700">
                      {p.last_reading_ts ? new Date(p.last_reading_ts).toLocaleString() : "never"}
                    </td>
                    <td className="px-4 py-2 text-slate-700">
                      {p.flagged_pct_last_hour !== null ? `${p.flagged_pct_last_hour}%` : "-"}
                    </td>
                    <td className="px-4 py-2 text-slate-600">
                      {p.reasons.length > 0 ? p.reasons.join("; ") : "-"}
                    </td>
                  </tr>
                ))}
                {data.fleet.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                      No plants found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
