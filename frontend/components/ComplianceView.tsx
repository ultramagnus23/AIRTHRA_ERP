"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getHistory, getKpis, ApiError } from "@/lib/api";
import { qualityInfo } from "@/lib/quality";
import type { KpiPoint } from "@/lib/types";

// SO2 stack emission limit line. There is no `limit` field anywhere in
// the schema (sensors/plants/kpis) for this - CPCB's typical FGD stack
// SO2 limit for this boiler class is used as a documented, configurable
// placeholder constant rather than a real per-plant regulatory value
// pulled from the backend (which doesn't have one to give). A future
// backend change could add a `plants.so2_limit_ppm` column; until then
// this is intentionally hardcoded and clearly labeled as such in the UI.
const SO2_STACK_LIMIT_PPM = 200;

function friendlyKpiName(name: string) {
  return name
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

function latestByKpiName(kpis: KpiPoint[]): Record<string, KpiPoint> {
  const out: Record<string, KpiPoint> = {};
  for (const k of kpis) {
    if (!out[k.kpi_name] || out[k.kpi_name].ts < k.ts) {
      out[k.kpi_name] = k;
    }
  }
  return out;
}

export default function ComplianceView({ plantId }: { plantId: string }) {
  const [kpis, setKpis] = useState<KpiPoint[] | null>(null);
  const [kpiError, setKpiError] = useState<string | null>(null);
  const [stackRows, setStackRows] = useState<{ ts: string; value: number | null }[] | null>(null);
  const [stackError, setStackError] = useState<string | null>(null);

  useEffect(() => {
    // Last 24h KPI window, same default the backend itself applies when
    // start/end are omitted (api/routers/plant.py get_kpis).
    getKpis(plantId)
      .then((res) => setKpis(res.kpis))
      .catch((err) => setKpiError(err instanceof ApiError ? err.message : "failed to load KPIs"));

    const end = new Date();
    const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
    getHistory(plantId, { start: start.toISOString(), end: end.toISOString(), sensors: ["SO2_out"] })
      .then((res) =>
        setStackRows(
          res.points.map((p) => ({
            ts: "bucket" in p ? p.bucket : p.ts,
            value: "avg_value" in p ? p.avg_value : p.value,
          })),
        ),
      )
      .catch((err) => setStackError(err instanceof ApiError ? err.message : "failed to load stack history"));
  }, [plantId]);

  const latest = kpis ? latestByKpiName(kpis) : {};
  const kpiNames = Object.keys(latest);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">KPIs (last 24h)</h2>
        {kpiError && <p className="text-sm text-red-700">{kpiError}</p>}
        {kpis && kpiNames.length === 0 && (
          <p className="text-sm text-slate-500">
            No KPI rows for this window yet (P3&apos;s kpi_worker writes so2_removal_efficiency and
            mass_balance_closure — literal SO2-kg-removed / K2SO3-kg / uptime% figures live in the
            billing worker&apos;s invoices table, which has no client-facing read endpoint yet).
          </p>
        )}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {kpiNames.map((name) => {
            const k = latest[name];
            const info = qualityInfo(k.quality_flag);
            return (
              <div
                key={name}
                className={`rounded-lg border p-4 ${
                  info.isGood ? "border-slate-200 bg-white" : "border-slate-300 bg-slate-100"
                }`}
              >
                <div className="text-sm font-medium text-slate-600">{friendlyKpiName(name)}</div>
                <div className={`mt-1 text-2xl font-semibold ${info.isGood ? "text-slate-900" : "text-slate-500"}`}>
                  {k.value === null ? "—" : k.value.toFixed(2)}
                  {!info.isGood && (
                    <span className="ml-2 align-middle text-xs font-normal text-slate-500">
                      ({info.label})
                    </span>
                  )}
                </div>
                <div className="mt-1 text-[11px] text-slate-400">
                  {new Date(k.ts).toLocaleString()}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-1 text-sm font-semibold text-slate-700">
          Stack SO2 (ppm) vs. limit — last 24h
        </h2>
        <p className="mb-2 text-xs text-slate-500">
          Limit line is a hardcoded placeholder ({SO2_STACK_LIMIT_PPM} ppm) — the schema has no
          per-plant regulatory limit field to pull from yet. See ComplianceView.tsx.
        </p>
        {stackError && <p className="text-sm text-red-700">{stackError}</p>}
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={stackRows ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="ts" tickFormatter={(v) => new Date(v).toLocaleTimeString()} fontSize={11} minTickGap={40} />
              <YAxis fontSize={11} />
              <Tooltip labelFormatter={(v) => new Date(String(v)).toLocaleString()} />
              <ReferenceLine
                y={SO2_STACK_LIMIT_PPM}
                stroke="#dc2626"
                strokeDasharray="4 4"
                label={{ value: "Limit", position: "insideTopRight", fill: "#dc2626", fontSize: 11 }}
              />
              <Line type="monotone" dataKey="value" stroke="#0ea5e9" dot={false} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <button
          disabled
          title="Not yet wired: there is no backend PDF-export endpoint for the client compliance view (POST /admin/mrv_export/{plant_id} exists but is global_admin-only and would 403 a tenant_read user)."
          className="cursor-not-allowed rounded-md border border-slate-300 bg-slate-100 px-4 py-2 text-sm font-medium text-slate-400"
        >
          Generate inspector PDF (coming soon)
        </button>
      </div>
    </div>
  );
}
