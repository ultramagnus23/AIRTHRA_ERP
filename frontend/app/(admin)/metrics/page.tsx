"use client";

import { useState, type FormEvent } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getMetrics, AdminApiError } from "@/lib/admin-api";
import type { MetricsResponse } from "@/lib/admin-types";
import { SENSOR_MANIFEST } from "@/lib/types";

// Known kpi_name values (workers/kpi_worker.py) offered alongside the
// raw sensor tags, but `metric` stays a free-text input underneath -
// GET /admin/metrics accepts either a kpis.kpi_name or a
// readings.sensor_id (source=auto tries kpi first, falls back to
// reading). Listing both here is a UX convenience only.
const KNOWN_METRICS = [
  "so2_removal_efficiency",
  "mass_balance_closure",
  ...SENSOR_MANIFEST.map((s) => s.sensor_id),
];

const PERIOD_OPTIONS = ["6h", "24h", "7d", "30d"];

export default function MetricsPage() {
  const [metric, setMetric] = useState(KNOWN_METRICS[0]);
  const [period, setPeriod] = useState("24h");
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function run(e?: FormEvent) {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    getMetrics({ metric, period, group_by: "plant_id" })
      .then(setData)
      .catch((err: unknown) =>
        setError(err instanceof AdminApiError ? err.message : "failed to load metric"),
      )
      .finally(() => setLoading(false));
  }

  const chartData =
    data?.results.map((r) => ({
      plant_id: r.plant_id,
      avg: r.avg,
      min: r.min,
      max: r.max,
    })) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-display text-2xl font-light text-fg">Cross-plant metric explorer</h1>
        <p className="text-sm text-mist">
          GET /admin/metrics, grouped by plant_id. All aggregation (avg/min/max) happens
          server-side.
        </p>
      </div>

      <form
        onSubmit={run}
        className="flex flex-wrap items-end gap-3 rounded-2xl border border-hair bg-panel p-4"
        style={{ boxShadow: "var(--shadow-sm)" }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-mono text-xs tracking-[0.1em] text-mist uppercase">Metric</span>
          <input
            list="metric-options"
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
          />
          <datalist id="metric-options">
            {KNOWN_METRICS.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-mono text-xs tracking-[0.1em] text-mist uppercase">Period</span>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
          >
            {PERIOD_OPTIONS.map((p) => (
              <option key={p} value={p} className="bg-panel">
                {p}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={loading || !metric}
          className="rounded-lg bg-rust px-4 py-1.5 text-sm font-semibold text-fg transition-colors duration-150 hover:bg-copper disabled:opacity-50"
        >
          {loading ? "Loading..." : "Run"}
        </button>
      </form>

      {error && <p className="text-sm text-rust">{error}</p>}

      {data && (
        <>
          <div className="font-mono text-xs text-mist">
            source: {data.source} · {data.start.slice(0, 19)} to {data.end.slice(0, 19)}
          </div>

          {chartData.length === 0 ? (
            <div
              className="rounded-2xl border border-hair bg-panel p-6 text-center font-mono text-sm text-mist"
              style={{ boxShadow: "var(--shadow-sm)" }}
            >
              No data for this metric/period.
            </div>
          ) : (
            <div
              className="h-80 rounded-2xl border border-hair bg-panel p-4"
              style={{ boxShadow: "var(--shadow-sm)" }}
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid stroke="var(--color-hair)" vertical={false} />
                  <XAxis
                    dataKey="plant_id"
                    stroke="var(--color-mist)"
                    fontSize={10}
                    fontFamily="var(--font-mono)"
                    tickLine={false}
                    axisLine={{ stroke: "var(--color-line)" }}
                  />
                  <YAxis
                    stroke="var(--color-mist)"
                    fontSize={10}
                    fontFamily="var(--font-mono)"
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "var(--color-midnight)",
                      border: "1px solid var(--color-line)",
                      borderRadius: 8,
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                    }}
                    labelStyle={{ color: "var(--color-fg)" }}
                  />
                  <Bar dataKey="avg" fill="var(--color-copper)" name="avg" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div
            className="overflow-x-auto rounded-2xl border border-hair bg-panel"
            style={{ boxShadow: "var(--shadow-sm)" }}
          >
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
                <tr>
                  <th className="px-4 py-2">Plant</th>
                  <th className="px-4 py-2">Avg</th>
                  <th className="px-4 py-2">Min</th>
                  <th className="px-4 py-2">Max</th>
                  <th className="px-4 py-2">Samples</th>
                  <th className="px-4 py-2">Non-good %</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((r) => (
                  <tr key={r.plant_id} className="border-b border-hair last:border-0">
                    <td className="px-4 py-2 font-mono text-xs text-fg">{r.plant_id}</td>
                    <td className="px-4 py-2 font-mono text-fg">{r.avg?.toFixed(3) ?? "-"}</td>
                    <td className="px-4 py-2 font-mono text-fg">{r.min?.toFixed(3) ?? "-"}</td>
                    <td className="px-4 py-2 font-mono text-fg">{r.max?.toFixed(3) ?? "-"}</td>
                    <td className="px-4 py-2 font-mono text-fg">{r.sample_count}</td>
                    <td className="px-4 py-2 font-mono text-fg">{r.non_good_pct ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
