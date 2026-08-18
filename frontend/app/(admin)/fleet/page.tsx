"use client";

import Link from "next/link";
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
// Fleet status colors mapped onto the Airthra semantic tokens: green (ok)
// = moss, yellow (degraded) = copper, red (critical) = rust, gray
// (unknown/offline) = mist. Always paired with the text label, never
// color alone, per DESIGN.md's status-badge rule.
const COLOR_STYLES: Record<string, string> = {
  green: "border-moss/40 bg-moss/10 text-moss",
  yellow: "border-copper/40 bg-copper/10 text-copper",
  red: "border-rust/40 bg-rust/10 text-rust",
  gray: "border-line bg-midnight text-mist",
};
const DOT_STYLES: Record<string, string> = {
  green: "bg-moss",
  yellow: "bg-copper",
  red: "bg-rust",
  gray: "bg-mist",
};

function ColorBadge({ color }: { color: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-0.5 font-mono text-xs font-medium ${
        COLOR_STYLES[color] ?? COLOR_STYLES.gray
      }`}
    >
      <span className={`h-2 w-2 rounded-full ${DOT_STYLES[color] ?? DOT_STYLES.gray}`} />
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
        <h1 className="font-display text-2xl font-light text-fg">Fleet health</h1>
        <p className="text-sm text-mist">
          Cross-plant status, computed server-side by GET /admin/fleet. Table view (see note in
          source) in place of a live map.
        </p>
      </div>

      {loading && <p className="font-mono text-sm text-mist">Loading fleet status...</p>}
      {error && <p className="text-sm text-rust">{error}</p>}

      {data && (
        <>
          <div
            className="rounded-2xl border border-hair bg-panel p-3 font-mono text-xs text-mist"
            style={{ boxShadow: "var(--shadow-sm)" }}
          >
            Thresholds: offline after {data.thresholds.offline_threshold_s}s of no readings;
            degraded when &gt;{data.thresholds.degraded_flag_pct}% of readings in the trailing{" "}
            {data.thresholds.degraded_window_s / 60}min are non-good.
          </div>

          <div
            className="overflow-x-auto rounded-2xl border border-hair bg-panel"
            style={{ boxShadow: "var(--shadow-sm)" }}
          >
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
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
                  <tr
                    key={p.plant_id}
                    className="border-b border-hair transition-colors duration-[var(--dur-fast)] last:border-0 hover:bg-midnight/60"
                  >
                    <td className="px-4 py-2">
                      <Link
                        href={`/${p.plant_id}`}
                        className="air-track inline-block font-medium text-fg underline decoration-line hover:text-copper hover:decoration-copper"
                        title="Open this plant's live view (remote debugging)"
                      >
                        {p.name}
                      </Link>
                      <div className="font-mono text-xs text-mist">{p.plant_id}</div>
                    </td>
                    <td className="px-4 py-2">
                      <ColorBadge color={p.color} />
                    </td>
                    <td className="px-4 py-2 font-mono text-fg">
                      {p.last_reading_ts ? new Date(p.last_reading_ts).toLocaleString() : "never"}
                    </td>
                    <td className="px-4 py-2 font-mono text-fg">
                      {p.flagged_pct_last_hour !== null ? `${p.flagged_pct_last_hour}%` : "-"}
                    </td>
                    <td className="px-4 py-2 text-mist">
                      {p.reasons.length > 0 ? p.reasons.join("; ") : "-"}
                    </td>
                  </tr>
                ))}
                {data.fleet.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-mist">
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
