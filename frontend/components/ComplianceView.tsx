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
        <h2 className="mb-3 font-mono text-xs tracking-[0.15em] text-mist uppercase">KPIs (last 24h)</h2>
        {kpiError && <p className="text-sm text-rust">{kpiError}</p>}
        {kpis && kpiNames.length === 0 && (
          <p className="text-sm text-mist">
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
                className={`relative overflow-hidden rounded-2xl border p-4 ${
                  info.isGood ? "border-hair bg-panel" : "border-line bg-midnight"
                }`}
                style={{ boxShadow: "var(--shadow-sm)" }}
              >
                <div
                  className="absolute inset-x-0 top-0 h-[2px]"
                  style={{ background: "oklch(0.72 0.15 54 / 0.55)" }}
                  aria-hidden
                />
                <div className="flex items-center gap-1.5 font-mono text-xs tracking-[0.08em] text-mist uppercase">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-copper" aria-hidden />
                  {friendlyKpiName(name)}
                </div>
                <div className={`mt-2 font-mono text-2xl font-medium ${info.isGood ? "text-fg" : "text-mist"}`}>
                  {k.value === null ? "—" : k.value.toFixed(2)}
                  {!info.isGood && (
                    <span className="ml-2 align-middle text-xs font-normal text-mist">
                      ({info.label})
                    </span>
                  )}
                </div>
                <div className="mt-1 font-mono text-[11px] text-mist">
                  {new Date(k.ts).toLocaleString()}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <h2 className="mb-1 font-mono text-xs tracking-[0.15em] text-mist uppercase">
          Stack SO2 (ppm) vs. limit — last 24h
        </h2>
        <p className="mb-3 font-mono text-[11px] text-mist">
          Limit line is a hardcoded placeholder ({SO2_STACK_LIMIT_PPM} ppm) — the schema has no
          per-plant regulatory limit field to pull from yet.
        </p>
        {stackError && <p className="text-sm text-rust">{stackError}</p>}
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={stackRows ?? []}>
              <CartesianGrid stroke="var(--color-hair)" vertical={false} />
              <XAxis
                dataKey="ts"
                tickFormatter={(v) => new Date(v).toLocaleTimeString()}
                fontSize={10}
                fontFamily="var(--font-mono)"
                stroke="var(--color-mist)"
                minTickGap={40}
                tickLine={false}
                axisLine={{ stroke: "var(--color-line)" }}
              />
              <YAxis fontSize={10} fontFamily="var(--font-mono)" stroke="var(--color-mist)" tickLine={false} axisLine={false} />
              <Tooltip
                labelFormatter={(v) => new Date(String(v)).toLocaleString()}
                contentStyle={{
                  background: "var(--color-midnight)",
                  border: "1px solid var(--color-line)",
                  borderRadius: 8,
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                }}
              />
              <ReferenceLine
                y={SO2_STACK_LIMIT_PPM}
                stroke="var(--color-rust)"
                strokeDasharray="4 4"
                label={{ value: "Limit", position: "insideTopRight", fill: "var(--color-rust)", fontSize: 11 }}
              />
              <Line type="monotone" dataKey="value" stroke="var(--color-copper)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div>
        <button
          disabled
          title="Not yet wired: there is no backend PDF-export endpoint for the client compliance view (POST /admin/mrv_export/{plant_id} exists but is global_admin-only and would 403 a tenant_read user)."
          className="cursor-not-allowed rounded-lg border border-line bg-panel px-4 py-2 text-sm font-medium text-mist"
        >
          Generate inspector PDF (coming soon)
        </button>
      </div>
    </div>
  );
}
