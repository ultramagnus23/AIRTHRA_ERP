"use client";

import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts";
import FlagBadge from "./FlagBadge";
import { qualityInfo } from "@/lib/quality";
import type { QualityFlagText, QualityFlagWire } from "@/lib/types";

export interface SparklinePoint {
  ts: number;
  value: number | null;
}

const ACCENT_DOT: Record<"copper" | "moss", string> = {
  copper: "bg-copper",
  moss: "bg-moss",
};
const ACCENT_EDGE: Record<"copper" | "moss", string> = {
  copper: "oklch(0.72 0.15 54 / 0.55)",
  moss: "oklch(0.64 0.1 152 / 0.55)",
};

export default function SensorTile({
  label,
  unit,
  value,
  flag,
  ts,
  history,
  range,
  accent = "copper",
}: {
  label: string;
  unit: string;
  value: number | null;
  flag: QualityFlagText | QualityFlagWire | number | string | null;
  ts: string | null;
  history: SparklinePoint[];
  /** Engineering min/max + normal sub-range, for the position bar. Optional - tile still works without it. */
  range?: { min: number; max: number; normal: [number, number] };
  /** Categorical color-coding (Airthra palette only) - which metric family this tile belongs to. */
  accent?: "copper" | "moss";
}) {
  const info = flag !== null ? qualityInfo(flag) : null;
  const isGood = info?.isGood ?? true;

  const inNormal =
    range && value !== null ? value >= range.normal[0] && value <= range.normal[1] : null;
  const barColor = !isGood ? "bg-mist" : inNormal === false ? "bg-copper" : "bg-moss";
  const barPct =
    range && value !== null
      ? Math.min(100, Math.max(0, ((value - range.min) / (range.max - range.min)) * 100))
      : null;

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border p-4 transition-colors duration-150 ${
        isGood ? "border-hair bg-panel" : "border-line bg-midnight"
      }`}
      style={{ boxShadow: "var(--shadow-sm)" }}
    >
      <div
        className="absolute inset-x-0 top-0 h-[2px]"
        style={{ background: ACCENT_EDGE[accent] }}
        aria-hidden
      />
      <div className="flex items-start justify-between">
        <span className="flex items-center gap-1.5 font-mono text-xs tracking-[0.08em] text-mist uppercase">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${ACCENT_DOT[accent]}`} aria-hidden />
          {label}
        </span>
        {flag !== null && <FlagBadge flag={flag} />}
      </div>
      <div
        className={`mt-2 font-mono text-2xl font-medium tabular-nums ${
          isGood ? "text-fg" : "text-mist"
        }`}
      >
        {value === null || value === undefined ? "—" : value.toFixed(2)}{" "}
        <span className="text-sm font-normal text-mist">{unit}</span>
      </div>

      {range && (
        <div className="mt-3">
          <div className="h-[3px] w-full overflow-hidden rounded-full bg-midnight">
            {barPct !== null && (
              <div
                className={`h-full rounded-full transition-[width] duration-300 ${barColor}`}
                style={{ width: `${barPct}%`, transitionTimingFunction: "var(--ease)" }}
              />
            )}
          </div>
          <div className="mt-1 font-mono text-[10px] text-mist">
            normal {range.normal[0]}–{range.normal[1]} {unit}
          </div>
        </div>
      )}

      {history.length > 1 && (
        <div className="mt-2 h-10">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <YAxis domain={["auto", "auto"]} hide />
              <Line
                type="monotone"
                dataKey="value"
                stroke={isGood ? "var(--color-copper)" : "var(--color-mist)"}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-1 font-mono text-[11px] text-mist">
        {ts ? new Date(ts).toLocaleTimeString() : "no data yet"}
      </div>
    </div>
  );
}
