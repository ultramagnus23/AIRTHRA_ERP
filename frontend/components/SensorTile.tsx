"use client";

import { useEffect, useRef, useState } from "react";
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
  tag,
  location,
  purpose,
  threshold,
  note,
  index = 0,
  wired,
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
  /** FEED register tag (AT-01, AE-02, ...) - the identifier a field engineer reads. */
  tag?: string;
  /** Mounting location + diagnostic purpose, shown on hover as the tile's title. */
  location?: string;
  purpose?: string;
  /** Register's alert/trip threshold, rendered verbatim as reference text.
   * Never evaluated here - alarm state comes from the alarm engine. */
  threshold?: string | null;
  /** Divergence between this platform's sensor and the FEED register. */
  note?: string;
  /** Position in the grid, for the staggered entrance cascade. */
  index?: number;
  /** false = catalogued FEED register tag with no sensor installed yet.
   * Renders as a plain "--" placeholder, dashed border, no flag/sparkline/
   * range bar - visually distinct from "wired but momentarily no data"
   * (which still shows "no data yet" under an em-dash). Never a faked
   * reading. */
  wired?: boolean;
}) {
  const info = flag !== null ? qualityInfo(flag) : null;
  const isGood = info?.isGood ?? true;

  // Pulse the readout when a new value actually lands, so liveness is
  // visible at a glance rather than only in the timestamp. Keyed on the
  // value itself: a re-render that doesn't change the reading must not
  // blip, or the pulse stops meaning "fresh data".
  const [blip, setBlip] = useState(false);
  const prevValue = useRef(value);
  useEffect(() => {
    const changed = prevValue.current !== value && prevValue.current !== null;
    prevValue.current = value;
    if (!changed) return;
    setBlip(true);
    const t = setTimeout(() => setBlip(false), 900);
    return () => clearTimeout(t);
  }, [value]);

  const inNormal =
    range && value !== null ? value >= range.normal[0] && value <= range.normal[1] : null;
  const barColor = !isGood ? "bg-mist" : inNormal === false ? "bg-copper" : "bg-moss";
  const barPct =
    range && value !== null
      ? Math.min(100, Math.max(0, ((value - range.min) / (range.max - range.min)) * 100))
      : null;

  if (wired === false) {
    return (
      <div
        className="relative overflow-hidden rounded-2xl border border-dashed border-line bg-panel/40 p-4 opacity-70"
        style={{ animationDelay: `calc(var(--stagger) * ${index})` }}
      >
        <span className="flex min-w-0 flex-col gap-0.5" title={purpose}>
          <span className="flex items-center gap-1.5 font-mono text-xs tracking-[0.08em] text-mist uppercase">
            <span className="inline-block h-1.5 w-1.5 rounded-full border border-mist" aria-hidden />
            {label}
          </span>
          {tag && (
            <span className="font-mono text-[10px] tracking-[0.12em] text-mist">{tag}</span>
          )}
        </span>
        <div className="mt-2 font-mono text-2xl font-medium tabular-nums text-mist">
          -- <span className="text-sm font-normal">{unit}</span>
        </div>
        <div className="mt-2 font-mono text-[10px] leading-snug text-mist">
          Register tag, not yet wired to hardware.
        </div>
      </div>
    );
  }

  return (
    <div
      className={`air-rise air-lift relative overflow-hidden rounded-2xl border p-4 hover:border-line ${
        isGood ? "border-hair bg-panel" : "border-line bg-midnight"
      }`}
      style={{
        boxShadow: "var(--shadow-sm)",
        animationDelay: `calc(var(--stagger) * ${index})`,
      }}
    >
      <div
        className="absolute inset-x-0 top-0 h-[2px]"
        style={{ background: ACCENT_EDGE[accent] }}
        aria-hidden
      />
      <div className="flex items-start justify-between gap-2">
        <span
          className="flex min-w-0 flex-col gap-0.5"
          title={[purpose, location && `Mounted: ${location}`].filter(Boolean).join("\n")}
        >
          <span className="flex items-center gap-1.5 font-mono text-xs tracking-[0.08em] text-mist uppercase">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${ACCENT_DOT[accent]}`} aria-hidden />
            {label}
          </span>
          {tag && (
            <span className="font-mono text-[10px] tracking-[0.12em] text-copper">{tag}</span>
          )}
        </span>
        {flag !== null && <FlagBadge flag={flag} />}
      </div>
      <div
        className={`${blip ? "air-blip" : ""} mt-2 -mx-1 rounded px-1 font-mono text-2xl font-medium tabular-nums ${
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

      {threshold && (
        <div className="mt-2 border-l-2 border-rust/40 pl-2 font-mono text-[10px] leading-snug text-mist">
          {threshold}
        </div>
      )}
      {note && (
        <div className="mt-1.5 font-mono text-[10px] leading-snug text-sand">{note}</div>
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
