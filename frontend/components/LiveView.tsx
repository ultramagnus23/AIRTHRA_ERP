"use client";

import { useEffect, useRef, useState } from "react";
import { getCurrentReadings, getKpis, ApiError } from "@/lib/api";
import { connectPlantWs } from "@/lib/ws";
import {
  SENSOR_MANIFEST,
  SUBSYSTEM_LABELS,
  REGISTER_TAG_COUNT,
  WIRED_TAG_COUNT,
  CATALOGUED_TAG_COUNT,
  COMPUTABLE_METRICS,
  PENDING_METRICS,
  CATEGORY_LABELS,
} from "@/lib/types";
import type { QualityFlagText, QualityFlagWire, Subsystem, PendingMetric } from "@/lib/types";
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
  const [kpis, setKpis] = useState<Record<string, { value: number | null; flag: QualityFlagText; ts: string }>>({});
  const mountedRef = useRef(true);

  // Calculated metrics are server-computed by workers/kpi_worker.py - this
  // just displays the latest value per kpi_name, never derives one itself
  // (the platform's hard rule: business logic is never computed in the
  // frontend). Polled rather than pushed over the WS, since kpis write on
  // the worker's own ~60s cadence, not per-reading.
  useEffect(() => {
    let cancelled = false;
    async function loadKpis() {
      try {
        const end = new Date();
        const start = new Date(end.getTime() - 60 * 60 * 1000);
        const res = await getKpis(plantId, { start: start.toISOString(), end: end.toISOString() });
        if (cancelled) return;
        const latest: typeof kpis = {};
        for (const p of res.kpis) {
          const existing = latest[p.kpi_name];
          if (!existing || p.ts > existing.ts) {
            latest[p.kpi_name] = { value: p.value, flag: p.quality_flag, ts: p.ts };
          }
        }
        setKpis(latest);
      } catch {
        // Non-fatal: the Calculated section just shows "no recent data" for
        // whichever kpi_name didn't resolve, same failure mode as a sensor
        // tile with no reading yet.
      }
    }
    loadKpis();
    const interval = setInterval(loadKpis, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [plantId]);

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
                {WIRED_TAG_COUNT} of {REGISTER_TAG_COUNT}
              </span>{" "}
              FEED register tags wired up ({CATALOGUED_TAG_COUNT - WIRED_TAG_COUNT} more catalogued
              below, awaiting hardware — {REGISTER_TAG_COUNT - CATALOGUED_TAG_COUNT} not yet
              transcribed into this build at all).
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
                        range={
                          s.min !== undefined && s.max !== undefined && s.normal
                            ? { min: s.min, max: s.max, normal: s.normal }
                            : undefined
                        }
                        accent={s.accent}
                        tag={s.tag}
                        location={s.location}
                        purpose={s.purpose}
                        threshold={s.threshold}
                        note={s.note}
                        wired={s.wired}
                      />
                    );
                  })}
                </div>
              </section>
            );
          })}

          <section>
            <h2 className="mb-3 flex items-baseline gap-2 font-mono text-xs tracking-[0.15em] text-mist uppercase">
              Calculated
              <span className="text-[10px] tracking-normal normal-case">
                server-computed by workers/kpi_worker.py — never derived in this page
              </span>
            </h2>

            <div className="mb-4 grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-4">
              {COMPUTABLE_METRICS.map((m, i) => {
                const k = kpis[m.kpi_name];
                return (
                  <div
                    key={m.kpi_name}
                    className="air-rise relative overflow-hidden rounded-2xl border border-hair bg-panel p-4"
                    style={{ boxShadow: "var(--shadow-sm)", animationDelay: `calc(var(--stagger) * ${i})` }}
                  >
                    <div
                      className="absolute inset-x-0 top-0 h-[2px]"
                      style={{ background: "oklch(0.72 0.15 54 / 0.55)" }}
                      aria-hidden
                    />
                    <span className="font-mono text-xs tracking-[0.08em] text-mist uppercase">{m.label}</span>
                    <div className="mt-2 font-mono text-2xl font-medium tabular-nums text-fg">
                      {k?.value === null || k?.value === undefined ? "—" : k.value.toFixed(1)}{" "}
                      <span className="text-sm font-normal text-mist">{m.unit}</span>
                    </div>
                    <div className="mt-2 font-mono text-[10px] leading-snug text-mist">{m.formula}</div>
                    <div className="mt-1 font-mono text-[11px] text-mist">
                      {k?.ts ? new Date(k.ts).toLocaleTimeString() : "no data yet"}
                    </div>
                  </div>
                );
              })}
            </div>

            <p className="mb-3 font-mono text-[10px] leading-snug text-mist">
              Everything below is a real formula from the platform&apos;s calculated-metrics
              roadmap, honestly marked pending — each needs at least one register tag this build
              doesn&apos;t have a live sensor for yet (see the tags column, and the placeholder
              tiles above). None of these are estimated or faked.
            </p>
            <div className="flex flex-col gap-4">
              {(Object.keys(CATEGORY_LABELS) as PendingMetric["category"][]).map((cat) => {
                const metrics = PENDING_METRICS.filter((m) => m.category === cat);
                if (metrics.length === 0) return null;
                return (
                  <div key={cat} className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
                    <h3 className="mb-2 font-mono text-[11px] tracking-[0.1em] text-copper uppercase">
                      {CATEGORY_LABELS[cat]}
                    </h3>
                    <div className="flex flex-col gap-2">
                      {metrics.map((m) => (
                        <div key={m.label} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-hair pt-2 first:border-t-0 first:pt-0">
                          <div>
                            <span className="text-sm text-fg">{m.label}</span>{" "}
                            <span className="font-mono text-[10px] text-mist">({m.unit})</span>
                            <div className="font-mono text-[10px] leading-snug text-mist">{m.formula}</div>
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {m.missingTags.map((t) => (
                              <span
                                key={t}
                                className="rounded-full border border-dashed border-line px-2 py-0.5 font-mono text-[9px] text-mist"
                              >
                                needs: {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

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
