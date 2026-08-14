"use client";

import { useEffect, useState } from "react";
import { getRiskScores, AdminApiError } from "@/lib/admin-api";
import type { RiskComponents, RiskEntry, RiskScoresResponse } from "@/lib/admin-types";

const COMPONENT_LABELS: Record<string, string> = {
  data_quality: "Data quality",
  ack_latency: "Alarm ack latency",
  maintenance: "Maintenance adherence",
  flag_pct: "Flag %",
  spike_freq: "Spike frequency",
};

function riskColor(score: number): string {
  if (score >= 60) return "bg-red-100 text-red-800 border-red-300";
  if (score >= 30) return "bg-amber-100 text-amber-800 border-amber-300";
  return "bg-emerald-100 text-emerald-800 border-emerald-300";
}

export default function RiskPage() {
  const [data, setData] = useState<RiskScoresResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    getRiskScores(30)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load risk scores"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Risk scores</h1>
        <p className="text-sm text-slate-600">
          GET /admin/risk_scores - 0-100 weighted risk, higher = riskier. Weights are published
          below per the PRD, not just the final score.
        </p>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading...</p>}
      {error && <p className="text-sm text-red-700">{error}</p>}

      {data && (
        <>
          <div className="rounded-md border border-slate-200 bg-white p-4">
            <div className="mb-2 text-xs font-semibold uppercase text-slate-500">
              Scoring weights (period: {data.period_days} days)
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(data.weights).map(([k, w]) => (
                <span
                  key={k}
                  className="rounded-full border border-slate-300 bg-slate-50 px-2.5 py-1 text-xs text-slate-700"
                >
                  {COMPONENT_LABELS[k] ?? k}: <span className="font-semibold">{(w * 100).toFixed(0)}%</span>
                </span>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">{data.notes}</p>
          </div>

          <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2">Plant</th>
                  <th className="px-4 py-2">Risk score</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {data.plants.map((p: RiskEntry) => (
                  <RiskRow
                    key={p.plant_id}
                    plant={p}
                    weights={data.weights}
                    open={expanded === p.plant_id}
                    onToggle={() => setExpanded(expanded === p.plant_id ? null : p.plant_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function RiskRow({
  plant,
  weights,
  open,
  onToggle,
}: {
  plant: RiskEntry;
  weights: RiskScoresResponse["weights"];
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="border-b border-slate-100 last:border-0">
        <td className="px-4 py-2">
          <div className="font-medium text-slate-900">{plant.name}</div>
          <div className="font-mono text-xs text-slate-500">{plant.plant_id}</div>
        </td>
        <td className="px-4 py-2">
          <span
            className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${riskColor(
              plant.risk_score,
            )}`}
          >
            {plant.risk_score}
          </span>
        </td>
        <td className="px-4 py-2 text-right">
          <button
            onClick={onToggle}
            className="text-xs font-medium text-amber-700 underline hover:text-amber-800"
          >
            {open ? "Hide breakdown" : "Show breakdown"}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-slate-100 bg-slate-50">
          <td colSpan={3} className="px-4 py-3">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {(Object.entries(plant.components) as [keyof RiskComponents, number][]).map(
                ([k, badness]) => (
                  <div key={k} className="rounded-md border border-slate-200 bg-white p-2">
                    <div className="text-xs font-medium text-slate-600">
                      {COMPONENT_LABELS[k] ?? k}
                    </div>
                    <div className="text-sm text-slate-900">
                      badness {badness.toFixed(1)} × weight {(weights[k] * 100).toFixed(0)}% ={" "}
                      <span className="font-semibold">{(badness * weights[k]).toFixed(2)}</span>
                    </div>
                  </div>
                ),
              )}
            </div>
            <div className="mt-2 grid gap-x-6 gap-y-1 text-xs text-slate-500 sm:grid-cols-3">
              <span>readings: {plant.raw.readings_total} ({plant.raw.readings_non_good} non-good)</span>
              <span>avg ack latency: {plant.raw.avg_ack_latency_min ?? "n/a"} min</span>
              <span>
                maintenance events: {plant.raw.maintenance_events} / expected{" "}
                {plant.raw.maintenance_expected}
              </span>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
