"use client";

import { useEffect, useState } from "react";
import { getTriageAlarms, AdminApiError } from "@/lib/admin-api";
import type { AdminAlarm } from "@/lib/admin-types";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "border-rust/40 bg-rust/10 text-rust",
  warning: "border-copper/40 bg-copper/10 text-copper",
  info: "border-line bg-midnight text-mist",
};

export default function TriagePage() {
  const [alarms, setAlarms] = useState<AdminAlarm[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    getTriageAlarms("raised")
      .then((res) => setAlarms(res.alarms))
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load alarms"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    getTriageAlarms("raised")
      .then((res) => setAlarms(res.alarms))
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load alarms"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-light text-fg">Triage queue</h1>
          <p className="text-sm text-mist">
            Raised alarms across every plant, via GET /admin/alarms?state=raised (new,
            cross-plant version of the client dashboard&apos;s per-plant alarm list - see report).
          </p>
        </div>
        <button
          onClick={load}
          className="rounded-lg border border-line bg-transparent px-3 py-1.5 text-sm font-medium text-fg transition-colors duration-150 hover:bg-midnight"
        >
          Refresh
        </button>
      </div>

      {loading && <p className="font-mono text-sm text-mist">Loading...</p>}
      {error && <p className="text-sm text-rust">{error}</p>}

      {alarms && (
        <div className="flex flex-col gap-3">
          {alarms.length === 0 && (
            <div
              className="rounded-2xl border border-hair bg-panel p-6 text-center font-mono text-sm text-mist"
              style={{ boxShadow: "var(--shadow-sm)" }}
            >
              No raised alarms. Fleet is quiet.
            </div>
          )}
          {alarms.map((a) => (
            <div
              key={a.alarm_id}
              className="relative overflow-hidden rounded-2xl border border-hair bg-panel p-4"
              style={{ boxShadow: "var(--shadow-sm)" }}
            >
              <div
                className="absolute inset-x-0 top-0 h-[2px]"
                style={{
                  background:
                    a.severity === "critical"
                      ? "oklch(0.52 0.16 48 / 0.55)"
                      : "oklch(0.72 0.15 54 / 0.55)",
                }}
                aria-hidden
              />
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-md border px-2.5 py-0.5 font-mono text-xs font-medium ${
                    SEVERITY_STYLES[a.severity] ?? SEVERITY_STYLES.info
                  }`}
                >
                  {a.severity}
                </span>
                <span className="text-sm font-medium text-fg">{a.plant_name}</span>
                <span className="font-mono text-xs text-mist">{a.plant_id}</span>
                <span className="ml-auto font-mono text-xs text-mist">
                  raised {new Date(a.raised_at).toLocaleString()}
                </span>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <div>
                  <div className="font-mono text-xs tracking-[0.1em] text-mist uppercase">Diagnosis</div>
                  <div className="text-sm text-fg">{a.diagnosis ?? "-"}</div>
                </div>
                <div>
                  <div className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
                    Suggested part
                  </div>
                  <div className="text-sm text-fg">{a.suggested_part ?? "-"}</div>
                </div>
              </div>
              {a.rule_id && (
                <div className="mt-2 font-mono text-xs text-mist">rule: {a.rule_id}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
