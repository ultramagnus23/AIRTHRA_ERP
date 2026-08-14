"use client";

import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts";
import FlagBadge from "./FlagBadge";
import { qualityInfo } from "@/lib/quality";
import type { QualityFlagText, QualityFlagWire } from "@/lib/types";

export interface SparklinePoint {
  ts: number;
  value: number | null;
}

export default function SensorTile({
  label,
  unit,
  value,
  flag,
  ts,
  history,
}: {
  label: string;
  unit: string;
  value: number | null;
  flag: QualityFlagText | QualityFlagWire | number | string | null;
  ts: string | null;
  history: SparklinePoint[];
}) {
  const info = flag !== null ? qualityInfo(flag) : null;
  const isGood = info?.isGood ?? true;

  return (
    <div
      className={`rounded-lg border p-4 ${
        isGood ? "border-slate-200 bg-white" : "border-slate-300 bg-slate-100"
      }`}
    >
      <div className="flex items-start justify-between">
        <span className="text-sm font-medium text-slate-600">{label}</span>
        {flag !== null && <FlagBadge flag={flag} />}
      </div>
      <div
        className={`mt-1 text-2xl font-semibold tabular-nums ${
          isGood ? "text-slate-900" : "text-slate-500"
        }`}
      >
        {value === null || value === undefined ? "—" : value.toFixed(2)}{" "}
        <span className="text-sm font-normal text-slate-500">{unit}</span>
      </div>
      {history.length > 1 && (
        <div className="mt-2 h-10">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <YAxis domain={["auto", "auto"]} hide />
              <Line
                type="monotone"
                dataKey="value"
                stroke={isGood ? "#0f172a" : "#94a3b8"}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-1 text-[11px] text-slate-400">
        {ts ? new Date(ts).toLocaleTimeString() : "no data yet"}
      </div>
    </div>
  );
}
