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

const COLORS = ["#0f172a", "#0ea5e9", "#f59e0b", "#059669", "#dc2626", "#7c3aed", "#0891b2"];

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
      <div className="flex flex-wrap items-end gap-4 rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <label className="block text-xs font-medium text-slate-600">Start</label>
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600">End</label>
          <input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {SENSOR_MANIFEST.map((s) => (
            <label key={s.sensor_id} className="flex items-center gap-1 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={selected.includes(s.sensor_id)}
                onChange={() => toggleSensor(s.sensor_id)}
              />
              {s.label}
            </label>
          ))}
        </div>
        <button
          onClick={load}
          disabled={loading || selected.length === 0}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? "Loading..." : "Load"}
        </button>
      </div>

      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {data && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="mb-2 text-xs text-slate-500">
            Resolution: <span className="font-mono">{data.resolution}</span> (auto-selected by the
            backend from the requested range — {data.points.length} points)
          </p>
          <div className="h-96 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  dataKey="ts"
                  tickFormatter={(v) => new Date(v).toLocaleString()}
                  minTickGap={40}
                  fontSize={11}
                />
                <YAxis fontSize={11} />
                <Tooltip labelFormatter={(v) => new Date(String(v)).toLocaleString()} />
                <Legend />
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
