"use client";

import { useEffect, useState } from "react";
import { getTriageAlarms, AdminApiError } from "@/lib/admin-api";
import type { AdminAlarm } from "@/lib/admin-types";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-300",
  warning: "bg-amber-100 text-amber-800 border-amber-300",
  info: "bg-slate-100 text-slate-700 border-slate-300",
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
          <h1 className="text-xl font-semibold text-slate-900">Triage queue</h1>
          <p className="text-sm text-slate-600">
            Raised alarms across every plant, via GET /admin/alarms?state=raised (new,
            cross-plant version of the client dashboard&apos;s per-plant alarm list - see report).
          </p>
        </div>
        <button
          onClick={load}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading...</p>}
      {error && <p className="text-sm text-red-700">{error}</p>}

      {alarms && (
        <div className="flex flex-col gap-3">
          {alarms.length === 0 && (
            <div className="rounded-md border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
              No raised alarms. Fleet is quiet.
            </div>
          )}
          {alarms.map((a) => (
            <div
              key={a.alarm_id}
              className="rounded-md border border-slate-200 bg-white p-4 shadow-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
                    SEVERITY_STYLES[a.severity] ?? SEVERITY_STYLES.info
                  }`}
                >
                  {a.severity}
                </span>
                <span className="text-sm font-medium text-slate-900">{a.plant_name}</span>
                <span className="font-mono text-xs text-slate-500">{a.plant_id}</span>
                <span className="ml-auto text-xs text-slate-500">
                  raised {new Date(a.raised_at).toLocaleString()}
                </span>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <div>
                  <div className="text-xs font-semibold uppercase text-slate-500">Diagnosis</div>
                  <div className="text-sm text-slate-800">{a.diagnosis ?? "-"}</div>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase text-slate-500">
                    Suggested part
                  </div>
                  <div className="text-sm text-slate-800">{a.suggested_part ?? "-"}</div>
                </div>
              </div>
              {a.rule_id && (
                <div className="mt-2 font-mono text-xs text-slate-400">rule: {a.rule_id}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
