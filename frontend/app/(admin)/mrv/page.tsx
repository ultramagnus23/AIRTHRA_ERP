"use client";

import { useEffect, useState } from "react";
import { exportMrv, getFleet, AdminApiError } from "@/lib/admin-api";
import type { FleetEntry, MrvExportResponse } from "@/lib/admin-types";

type ExportState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; result: MrvExportResponse }
  | { status: "error"; message: string };

function defaultPeriod(): string {
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = String(now.getUTCMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

export default function MrvPage() {
  const [plants, setPlants] = useState<FleetEntry[] | null>(null);
  const [plantsError, setPlantsError] = useState<string | null>(null);
  const [period, setPeriod] = useState(defaultPeriod());
  const [states, setStates] = useState<Record<string, ExportState>>({});

  useEffect(() => {
    // Reuses GET /admin/fleet purely for the plant_id/name list - there
    // is no dedicated "list plants" admin endpoint, and fleet's payload
    // already carries both fields for every plant, so a second fetch
    // just for names would be redundant.
    getFleet()
      .then((res) => setPlants(res.fleet))
      .catch((e: unknown) => setPlantsError(e instanceof AdminApiError ? e.message : "failed to load plants"));
  }, []);

  async function runExport(plantId: string) {
    setStates((prev) => ({ ...prev, [plantId]: { status: "loading" } }));
    try {
      const result = await exportMrv(plantId, period);
      setStates((prev) => ({ ...prev, [plantId]: { status: "success", result } }));
    } catch (e) {
      setStates((prev) => ({
        ...prev,
        [plantId]: {
          status: "error",
          message: e instanceof AdminApiError ? e.message : "export failed",
        },
      }));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-display text-2xl font-light text-fg">MRV export</h1>
        <p className="text-sm text-mist">
          POST /admin/mrv_export/{"{plant_id}"}?period=YYYY-MM. Builds and uploads a ZIP
          server-side (readings parquet + calibration manifest + OTS proofs where available) -
          this can take a while for a full month, so each plant tracks its own loading state
          below rather than blocking the page.
        </p>
      </div>

      <label className="flex max-w-xs flex-col gap-1 text-sm">
        <span className="font-mono text-xs tracking-[0.1em] text-mist uppercase">Period (YYYY-MM)</span>
        <input
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          placeholder="2026-08"
          className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none"
        />
      </label>

      {plantsError && <p className="text-sm text-rust">{plantsError}</p>}
      {!plants && !plantsError && <p className="font-mono text-sm text-mist">Loading plants...</p>}

      <div className="flex flex-col gap-3">
        {plants?.map((p) => {
          const state = states[p.plant_id] ?? { status: "idle" };
          return (
            <div
              key={p.plant_id}
              className="flex flex-col gap-2 rounded-2xl border border-hair bg-panel p-4 sm:flex-row sm:items-center sm:justify-between"
              style={{ boxShadow: "var(--shadow-sm)" }}
            >
              <div>
                <div className="font-medium text-fg">{p.name}</div>
                <div className="font-mono text-xs text-mist">{p.plant_id}</div>
              </div>
              <div className="flex flex-1 flex-col items-start gap-2 sm:items-end">
                <button
                  onClick={() => runExport(p.plant_id)}
                  disabled={state.status === "loading" || !period}
                  className="rounded-lg bg-rust px-4 py-1.5 text-sm font-semibold text-fg transition-colors duration-150 hover:bg-copper disabled:opacity-50"
                >
                  {state.status === "loading" ? "Exporting..." : `Export MRV for ${period}`}
                </button>
                {state.status === "success" && (
                  <div className="text-right font-mono text-xs text-moss">
                    Done - {state.result.day_count} days.{" "}
                    <a
                      href={state.result.zip_url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline"
                    >
                      Download ZIP
                    </a>
                  </div>
                )}
                {state.status === "error" && (
                  <div className="text-right text-xs text-rust">{state.message}</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
