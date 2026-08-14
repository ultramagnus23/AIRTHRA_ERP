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
        <h1 className="text-xl font-semibold text-slate-900">Cross-plant metric explorer</h1>
        <p className="text-sm text-slate-600">
          GET /admin/metrics, grouped by plant_id. All aggregation (avg/min/max) happens
          server-side.
        </p>
      </div>

      <form
        onSubmit={run}
        className="flex flex-wrap items-end gap-3 rounded-md border border-slate-200 bg-white p-4"
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Metric</span>
          <input
            list="metric-options"
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          <datalist id="metric-options">
            {KNOWN_METRICS.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-slate-600">Period</span>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            {PERIOD_OPTIONS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={loading || !metric}
          className="rounded-md bg-amber-500 px-4 py-1.5 text-sm font-semibold text-slate-900 hover:bg-amber-400 disabled:opacity-50"
        >
          {loading ? "Loading..." : "Run"}
        </button>
      </form>

      {error && <p className="text-sm text-red-700">{error}</p>}

      {data && (
        <>
          <div className="text-xs text-slate-500">
            source: {data.source} · {data.start.slice(0, 19)} to {data.end.slice(0, 19)}
          </div>

          {chartData.length === 0 ? (
            <div className="rounded-md border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
              No data for this metric/period.
            </div>
          ) : (
            <div className="h-80 rounded-md border border-slate-200 bg-white p-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="plant_id" fontSize={12} />
                  <YAxis fontSize={12} />
                  <Tooltip />
                  <Bar dataKey="avg" fill="#f59e0b" name="avg" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
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
                  <tr key={r.plant_id} className="border-b border-slate-100 last:border-0">
                    <td className="px-4 py-2 font-mono text-xs text-slate-700">{r.plant_id}</td>
                    <td className="px-4 py-2">{r.avg?.toFixed(3) ?? "-"}</td>
                    <td className="px-4 py-2">{r.min?.toFixed(3) ?? "-"}</td>
                    <td className="px-4 py-2">{r.max?.toFixed(3) ?? "-"}</td>
                    <td className="px-4 py-2">{r.sample_count}</td>
                    <td className="px-4 py-2">{r.non_good_pct ?? "-"}</td>
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
