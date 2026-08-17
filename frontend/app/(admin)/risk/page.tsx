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
  if (score >= 60) return "border-rust/40 bg-rust/10 text-rust";
  if (score >= 30) return "border-copper/40 bg-copper/10 text-copper";
  return "border-moss/40 bg-moss/10 text-moss";
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
        <h1 className="font-display text-2xl font-light text-fg">Risk scores</h1>
        <p className="text-sm text-mist">
          GET /admin/risk_scores - 0-100 weighted risk, higher = riskier. Weights are published
          below per the PRD, not just the final score.
        </p>
      </div>

      {loading && <p className="font-mono text-sm text-mist">Loading...</p>}
      {error && <p className="text-sm text-rust">{error}</p>}

      {data && (
        <>
          <div className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
            <div className="mb-2 font-mono text-xs tracking-[0.1em] text-mist uppercase">
              Scoring weights (period: {data.period_days} days)
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(data.weights).map(([k, w]) => (
                <span
                  key={k}
                  className="rounded-md border border-line bg-midnight px-2.5 py-1 font-mono text-xs text-fg"
                >
                  {COMPONENT_LABELS[k] ?? k}: <span className="font-semibold text-copper">{(w * 100).toFixed(0)}%</span>
                </span>
              ))}
            </div>
            <p className="mt-2 text-xs text-mist">{data.notes}</p>
          </div>

          <div
            className="overflow-x-auto rounded-2xl border border-hair bg-panel"
            style={{ boxShadow: "var(--shadow-sm)" }}
          >
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
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
      <tr className="border-b border-hair last:border-0">
        <td className="px-4 py-2">
          <div className="font-medium text-fg">{plant.name}</div>
          <div className="font-mono text-xs text-mist">{plant.plant_id}</div>
        </td>
        <td className="px-4 py-2">
          <span
            className={`inline-flex items-center rounded-md border px-2.5 py-0.5 font-mono text-xs font-semibold ${riskColor(
              plant.risk_score,
            )}`}
          >
            {plant.risk_score}
          </span>
        </td>
        <td className="px-4 py-2 text-right">
          <button
            onClick={onToggle}
            className="text-xs font-medium text-copper underline hover:text-fg"
          >
            {open ? "Hide breakdown" : "Show breakdown"}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-hair bg-midnight">
          <td colSpan={3} className="px-4 py-3">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {(Object.entries(plant.components) as [keyof RiskComponents, number][]).map(
                ([k, badness]) => (
                  <div key={k} className="rounded-lg border border-hair bg-panel p-2">
                    <div className="font-mono text-xs tracking-[0.05em] text-mist uppercase">
                      {COMPONENT_LABELS[k] ?? k}
                    </div>
                    <div className="text-sm text-fg">
                      badness {badness.toFixed(1)} × weight {(weights[k] * 100).toFixed(0)}% ={" "}
                      <span className="font-mono font-semibold text-copper">{(badness * weights[k]).toFixed(2)}</span>
                    </div>
                  </div>
                ),
              )}
            </div>
            <div className="mt-2 grid gap-x-6 gap-y-1 font-mono text-xs text-mist sm:grid-cols-3">
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
