"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getHistory, ApiError } from "@/lib/api";
import { SENSOR_MANIFEST, type HistoryResponse } from "@/lib/types";

// Airthra palette only - cycled across however many sensors are selected.
const COLORS = [
  "oklch(0.72 0.15 54)", // copper
  "oklch(0.64 0.1 152)", // moss
  "oklch(0.52 0.16 48)", // rust
  "oklch(0.935 0.062 96)", // sand
  "oklch(0.965 0.012 236)", // fg
  "oklch(0.72 0.022 240)", // mist
  "oklch(0.86 0.09 54)", // copper, lighter
];

function isAggPoint(p: HistoryResponse["points"][number]): p is Extract<
  HistoryResponse["points"][number],
  { bucket: string }
> {
  return "bucket" in p;
}

function toChartRows(res: HistoryResponse) {
  const byTs = new Map<string, Record<string, number | null | string>>();
  for (const p of res.points) {
    const agg = isAggPoint(p);
    const ts = agg ? p.bucket : p.ts;
    const value = agg ? p.avg_value : p.value;
    const row = byTs.get(ts) ?? { ts };
    row[p.sensor_id] = value;
    byTs.set(ts, row);
  }
  return Array.from(byTs.values()).sort((a, b) =>
    String(a.ts).localeCompare(String(b.ts)),
  );
}

// <input type="datetime-local"> holds a LOCAL wall-clock string with no
// timezone info, not UTC - toISOString() would silently shift the
// displayed default by the browser's UTC offset (bit us during manual
// testing: the initial 6h window pointed at the wrong hours entirely).
// Build the string from local getters instead.
function toLocalInputValue(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function defaultRange() {
  const end = new Date();
  const start = new Date(end.getTime() - 6 * 60 * 60 * 1000); // last 6h -> backend picks 'raw'
  return {
    start: toLocalInputValue(start),
    end: toLocalInputValue(end),
  };
}

export default function HistoryChart({ plantId }: { plantId: string }) {
  const initial = defaultRange();
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [selected, setSelected] = useState<string[]>(["SO2_in", "SO2_out"]);
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      // Backend auto-selects raw/1m/15m/1h from the start/end span - we
      // just pass the range through untouched (see api/routers/plant.py
      // _auto_resolution). Never compute/override resolution here.
      const res = await getHistory(plantId, {
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        sensors: selected,
      });
      setData(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "failed to load history");
    } finally {
      setLoading(false);
    }
  }

  const rows = useMemo(() => (data ? toChartRows(data) : []), [data]);

  function toggleSensor(id: string) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]));
  }

  return (
    <div className="flex flex-col gap-4">
      <div
        className="flex flex-wrap items-end gap-4 rounded-2xl border border-hair bg-panel p-4"
        style={{ boxShadow: "var(--shadow-sm)" }}
      >
        <div>
          <label className="block text-xs font-medium text-mist">Start</label>
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="rounded-lg border border-line bg-transparent px-2 py-1.5 font-mono text-sm text-fg [color-scheme:dark] focus:border-copper focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-mist">End</label>
          <input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="rounded-lg border border-line bg-transparent px-2 py-1.5 font-mono text-sm text-fg [color-scheme:dark] focus:border-copper focus:outline-none"
          />
        </div>
        <div className="flex flex-wrap gap-3">
          {SENSOR_MANIFEST.map((s) => (
            <label key={s.sensor_id} className="flex items-center gap-1.5 text-xs text-mist">
              <input
                type="checkbox"
                checked={selected.includes(s.sensor_id)}
                onChange={() => toggleSensor(s.sensor_id)}
                className="accent-copper"
              />
              {s.label}
            </label>
          ))}
        </div>
        <button
          onClick={load}
          disabled={loading || selected.length === 0}
          className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50"
        >
          {loading ? "Loading…" : "Load"}
        </button>
      </div>

      {error && (
        <p className="rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>
      )}

      {data && (
        <div
          className="rounded-2xl border border-hair bg-panel p-4"
          style={{ boxShadow: "var(--shadow-sm)" }}
        >
          <p className="mb-2 font-mono text-xs text-mist">
            resolution: <span className="text-copper">{data.resolution}</span> (auto-selected by the
            backend from the requested range — {data.points.length} points)
          </p>
          <div className="h-96 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows}>
                <CartesianGrid stroke="var(--color-hair)" vertical={false} />
                <XAxis
                  dataKey="ts"
                  tickFormatter={(v) => new Date(v).toLocaleString()}
                  minTickGap={40}
                  fontSize={10}
                  fontFamily="var(--font-mono)"
                  stroke="var(--color-mist)"
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
                <Legend wrapperStyle={{ fontFamily: "var(--font-body)", fontSize: 11, color: "var(--color-mist)" }} />
                {selected.map((id, i) => (
                  <Line
                    key={id}
                    type="monotone"
                    dataKey={id}
                    stroke={COLORS[i % COLORS.length]}
                    dot={false}
                    connectNulls
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
