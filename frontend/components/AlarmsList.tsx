"use client";

import { useCallback, useEffect, useState } from "react";
import { ackAlarm, getAlarms, ApiError } from "@/lib/api";
import type { Alarm } from "@/lib/types";

const SEVERITY_CLASS: Record<Alarm["severity"], string> = {
  info: "text-mist border-line bg-midnight",
  warning: "text-copper border-copper bg-panel",
  critical: "text-rust border-rust bg-panel",
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
      {error && <p className="rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}
      {alarms && alarms.length === 0 && (
        <p className="text-sm text-mist">No alarms for this plant.</p>
      )}
      <div className="flex flex-col gap-2">
        {alarms?.map((a) => (
          <div
            key={a.alarm_id}
            className="relative flex items-center justify-between overflow-hidden rounded-2xl border border-hair bg-panel p-4"
            style={{ boxShadow: "var(--shadow-sm)" }}
          >
            <div
              className="absolute inset-x-0 top-0 h-[2px]"
              style={{
                background:
                  a.severity === "critical"
                    ? "oklch(0.52 0.16 48 / 0.6)"
                    : a.severity === "warning"
                      ? "oklch(0.72 0.15 54 / 0.6)"
                      : "oklch(0.72 0.022 240 / 0.4)",
              }}
              aria-hidden
            />
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-md border px-2 py-0.5 font-mono text-[11px] font-medium ${SEVERITY_CLASS[a.severity]}`}
                >
                  {a.severity}
                </span>
                <span className="text-sm font-medium text-fg">{a.state}</span>
              </div>
              <p className="mt-1 text-sm text-mist">
                {a.diagnosis ?? "No diagnosis recorded"}
                {a.suggested_part && (
                  <span className="text-mist"> — suggested part: {a.suggested_part}</span>
                )}
              </p>
              <p className="mt-1 font-mono text-[11px] text-mist">
                Raised {new Date(a.raised_at).toLocaleString()}
                {a.acked_at && ` — acked ${new Date(a.acked_at).toLocaleString()}`}
              </p>
            </div>
            {a.state === "raised" && (
              <button
                onClick={() => handleAck(a.alarm_id)}
                disabled={ackingId === a.alarm_id}
                className="rounded-lg bg-rust px-3 py-1.5 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50"
              >
                {ackingId === a.alarm_id ? "Acking…" : "Acknowledge"}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
