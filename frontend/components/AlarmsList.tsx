"use client";

import { useCallback, useEffect, useState } from "react";
import { ackAlarm, getAlarms, ApiError } from "@/lib/api";
import type { Alarm } from "@/lib/types";

const SEVERITY_CLASS: Record<Alarm["severity"], string> = {
  info: "bg-sky-50 text-sky-700 border-sky-200",
  warning: "bg-amber-50 text-amber-700 border-amber-200",
  critical: "bg-red-50 text-red-700 border-red-200",
};

export default function AlarmsList({ plantId }: { plantId: string }) {
  const [alarms, setAlarms] = useState<Alarm[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ackingId, setAckingId] = useState<string | null>(null);

  const load = useCallback(() => {
    getAlarms(plantId)
      .then((res) => setAlarms(res.alarms))
      .catch((err) => setError(err instanceof ApiError ? err.message : "failed to load alarms"));
  }, [plantId]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAck(alarmId: string) {
    setAckingId(alarmId);
    try {
      await ackAlarm(plantId, alarmId);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "failed to ack alarm");
    } finally {
      setAckingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {alarms && alarms.length === 0 && (
        <p className="text-sm text-slate-500">No alarms for this plant.</p>
      )}
      <div className="flex flex-col gap-2">
        {alarms?.map((a) => (
          <div
            key={a.alarm_id}
            className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4"
          >
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${SEVERITY_CLASS[a.severity]}`}
                >
                  {a.severity}
                </span>
                <span className="text-sm font-medium text-slate-800">{a.state}</span>
              </div>
              <p className="mt-1 text-sm text-slate-600">
                {a.diagnosis ?? "No diagnosis recorded"}
                {a.suggested_part && (
                  <span className="text-slate-400"> — suggested part: {a.suggested_part}</span>
                )}
              </p>
              <p className="mt-1 text-[11px] text-slate-400">
                Raised {new Date(a.raised_at).toLocaleString()}
                {a.acked_at && ` — acked ${new Date(a.acked_at).toLocaleString()}`}
              </p>
            </div>
            {a.state === "raised" && (
              <button
                onClick={() => handleAck(a.alarm_id)}
                disabled={ackingId === a.alarm_id}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {ackingId === a.alarm_id ? "Acking..." : "Acknowledge"}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
