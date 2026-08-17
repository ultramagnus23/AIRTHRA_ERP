"use client";

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import type { SparklinePoint } from "./SensorTile";

// A larger, dual-axis trend chart - the "more graph space" companion to
// the compact sparklines on each SensorTile. Reuses the same in-memory
// rolling history the tiles already track; no extra API calls.
export default function TrendPanel({
  inSeries,
  outSeries,
}: {
  inSeries: SparklinePoint[];
  outSeries: SparklinePoint[];
}) {
  const merged = inSeries.map((p, i) => ({
    ts: p.ts,
    inValue: p.value,
    outValue: outSeries[i]?.value ?? null,
  }));

  const fmtTime = (ts: number) =>
    new Date(ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="font-mono text-xs tracking-[0.08em] text-mist uppercase">
          SO2 capture trend
        </h3>
        <span className="font-mono text-[10px] text-mist">last {merged.length} samples</span>
      </div>
      {merged.length > 1 ? (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={merged} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke="var(--color-hair)" vertical={false} />
              <XAxis
                dataKey="ts"
                tickFormatter={fmtTime}
                stroke="var(--color-mist)"
                fontSize={10}
                fontFamily="var(--font-mono)"
                tickLine={false}
                axisLine={{ stroke: "var(--color-line)" }}
              />
              <YAxis
                yAxisId="in"
                stroke="var(--color-mist)"
                fontSize={10}
                fontFamily="var(--font-mono)"
                tickLine={false}
                axisLine={false}
                width={48}
              />
              <YAxis
                yAxisId="out"
                orientation="right"
                stroke="var(--color-mist)"
                fontSize={10}
                fontFamily="var(--font-mono)"
                tickLine={false}
                axisLine={false}
                width={48}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--color-midnight)",
                  border: "1px solid var(--color-line)",
                  borderRadius: 4,
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                }}
                labelFormatter={(v) => fmtTime(Number(v))}
              />
              <Legend
                wrapperStyle={{ fontFamily: "var(--font-body)", fontSize: 11, color: "var(--color-mist)" }}
              />
              <Line
                yAxisId="in"
                type="monotone"
                dataKey="inValue"
                name="SO2 inlet (ppm)"
                stroke="var(--color-mist)"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                yAxisId="out"
                type="monotone"
                dataKey="outValue"
                name="SO2 stack (ppm)"
                stroke="var(--color-copper)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="flex h-56 items-center justify-center font-mono text-xs text-mist">
          collecting samples…
        </div>
      )}
    </div>
  );
}
