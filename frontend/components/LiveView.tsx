"use client";

import { useEffect, useRef, useState } from "react";
import { getCurrentReadings, ApiError } from "@/lib/api";
import { connectPlantWs } from "@/lib/ws";
import { SENSOR_MANIFEST, SUBSYSTEM_LABELS, REGISTER_TAG_COUNT } from "@/lib/types";
import type { QualityFlagText, QualityFlagWire, Subsystem } from "@/lib/types";
import SensorTile, { type SparklinePoint } from "./SensorTile";
import TrendPanel from "./TrendPanel";
import PidDiagram from "./PidDiagram";

interface SensorState {
  value: number | null;
  flag: QualityFlagText | QualityFlagWire;
  ts: string;
}

const MAX_SPARKLINE_POINTS = 40;

// "tiles" (the Live tab: sensor grid + trend chart) and "diagram" (the
// P&ID tab: the process schematic alone) share this component rather than
// duplicating the WS-subscription/history-buffer logic - see
// app/(client)/[plant_id]/pid/page.tsx for why the route exists
// separately from the root Live route despite both using LiveView.
export default function LiveView({
  plantId,
  view = "tiles",
}: {
  plantId: string;
  view?: "tiles" | "diagram";
}) {
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
    <div className="flex flex-col gap-8">
      <div className="flex items-baseline justify-between">
        <h1 className="font-display text-2xl font-light text-fg">
          {view === "diagram" ? "P&ID" : "Live"}
        </h1>
        <div className="flex items-center gap-2 font-mono text-xs text-mist">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              wsStatus === "open"
                ? "bg-moss"
                : wsStatus === "connecting"
                  ? "bg-copper"
                  : "bg-rust"
            }`}
          />
          {wsStatus}
          {error && <span className="text-rust"> — {error}</span>}
        </div>
      </div>

      {view === "diagram" ? (
        <section>
          <h2 className="mb-3 font-mono text-xs tracking-[0.15em] text-mist uppercase">
            Process overview
          </h2>
          <PidDiagram
            so2In={pidReading("SO2_in", "ppm")}
            so2Out={pidReading("SO2_out", "ppm")}
            ph={pidReading("pH", "pH")}
            temp={pidReading("temp_C", "C")}
            kohLevel={pidReading("level_KOH_tank", "%")}
            k2so3Level={pidReading("level_K2SO3_tank", "%")}
            flow={pidReading("flow", "m3/h")}
          />
        </section>
      ) : (
        <>
          <div
            className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 rounded-2xl border border-hair bg-panel p-3 font-mono text-xs text-mist"
            style={{ boxShadow: "var(--shadow-sm)" }}
          >
            <span>
              Instrument coverage:{" "}
              <span className="text-fg">
                {SENSOR_MANIFEST.length} of {REGISTER_TAG_COUNT}
              </span>{" "}
              FEED register tags wired up.
            </span>
            <span>
              Ranges and trip thresholds below are the register&apos;s, shown for reference — alarm
              state is decided by the alarm engine, not this page.
            </span>
          </div>

          {(Object.keys(SUBSYSTEM_LABELS) as Subsystem[]).map((sub) => {
            const sensors = SENSOR_MANIFEST.filter((s) => s.subsystem === sub);
            if (sensors.length === 0) return null;
            return (
              <section key={sub}>
                <h2 className="mb-3 flex items-baseline gap-2 font-mono text-xs tracking-[0.15em] text-mist uppercase">
                  {SUBSYSTEM_LABELS[sub]}
                  <span className="text-[10px] tracking-normal normal-case">
                    {sensors.length} instrument{sensors.length === 1 ? "" : "s"}
                  </span>
                </h2>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-4">
                  {sensors.map((s, i) => {
                    const r = byId(s.sensor_id);
                    return (
                      <SensorTile
                        key={s.sensor_id}
                        index={i}
                        label={s.label}
                        unit={s.unit}
                        value={r?.value ?? null}
                        flag={r?.flag ?? null}
                        ts={r?.ts ?? null}
                        history={history[s.sensor_id] ?? []}
                        range={{ min: s.min, max: s.max, normal: s.normal }}
                        accent={s.accent}
                        tag={s.tag}
                        location={s.location}
                        purpose={s.purpose}
                        threshold={s.threshold}
                        note={s.note}
                      />
                    );
                  })}
                </div>
              </section>
            );
          })}

          <section>
            <h2 className="mb-3 font-mono text-xs tracking-[0.15em] text-mist uppercase">
              Trend
            </h2>
            <TrendPanel inSeries={history.SO2_in ?? []} outSeries={history.SO2_out ?? []} />
          </section>
        </>
      )}
    </div>
  );
}
