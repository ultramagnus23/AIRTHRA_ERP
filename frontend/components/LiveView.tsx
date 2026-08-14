"use client";

import { useEffect, useRef, useState } from "react";
import { getCurrentReadings, ApiError } from "@/lib/api";
import { connectPlantWs } from "@/lib/ws";
import { SENSOR_MANIFEST } from "@/lib/types";
import type { QualityFlagText, QualityFlagWire } from "@/lib/types";
import SensorTile, { type SparklinePoint } from "./SensorTile";
import PidDiagram from "./PidDiagram";

interface SensorState {
  value: number | null;
  flag: QualityFlagText | QualityFlagWire;
  ts: string;
}

const MAX_SPARKLINE_POINTS = 40;

export default function LiveView({ plantId }: { plantId: string }) {
  const [readings, setReadings] = useState<Record<string, SensorState>>({});
  const [history, setHistory] = useState<Record<string, SparklinePoint[]>>({});
  const [wsStatus, setWsStatus] = useState<"connecting" | "open" | "closed">("connecting");
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  function applyReading(sensorId: string, value: number | null, flag: QualityFlagText | QualityFlagWire, ts: string) {
    setReadings((prev) => ({ ...prev, [sensorId]: { value, flag, ts } }));
    setHistory((prev) => {
      const existing = prev[sensorId] ?? [];
      const next = [...existing, { ts: new Date(ts).getTime(), value }].slice(-MAX_SPARKLINE_POINTS);
      return { ...prev, [sensorId]: next };
    });
  }

  useEffect(() => {
    mountedRef.current = true;
    getCurrentReadings(plantId)
      .then((res) => {
        if (!mountedRef.current) return;
        for (const r of res.readings) {
          applyReading(r.sensor_id, r.value, r.quality_flag, r.ts);
        }
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "failed to load current readings");
      });

    const handle = connectPlantWs(plantId, {
      onOpen: () => setWsStatus("open"),
      onClose: () => setWsStatus("closed"),
      onError: () => setError((prev) => prev ?? "live connection error"),
      onReadings: (msgs) => {
        for (const r of msgs) {
          applyReading(r.sensor_id, r.value, r.quality_flag, r.ts);
        }
      },
    });

    return () => {
      mountedRef.current = false;
      handle.close();
    };
  }, [plantId]);

  const byId = (id: string) => readings[id];
  const pidReading = (id: string, unit: string) => {
    const r = byId(id);
    return r ? { value: r.value, flag: r.flag, unit } : undefined;
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            wsStatus === "open" ? "bg-emerald-500" : wsStatus === "connecting" ? "bg-amber-400" : "bg-red-500"
          }`}
        />
        Live feed: {wsStatus}
        {error && <span className="text-red-600">— {error}</span>}
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {SENSOR_MANIFEST.map((s) => {
          const r = byId(s.sensor_id);
          return (
            <SensorTile
              key={s.sensor_id}
              label={s.label}
              unit={s.unit}
              value={r?.value ?? null}
              flag={r?.flag ?? null}
              ts={r?.ts ?? null}
              history={history[s.sensor_id] ?? []}
            />
          );
        })}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Process overview</h2>
        <PidDiagram
          so2In={pidReading("SO2_in", "ppm")}
          so2Out={pidReading("SO2_out", "ppm")}
          ph={pidReading("pH", "pH")}
          temp={pidReading("temp_C", "C")}
          kohLevel={pidReading("level_KOH_tank", "%")}
          k2so3Level={pidReading("level_K2SO3_tank", "%")}
          flow={pidReading("flow", "m3/h")}
        />
      </div>
    </div>
  );
}
