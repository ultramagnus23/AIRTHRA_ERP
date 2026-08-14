"use client";

import { useState } from "react";
import { postEvent, ApiError } from "@/lib/api";
import type { EventKind } from "@/lib/types";

const KINDS: EventKind[] = ["maintenance", "lab_sample", "note", "alarm_ack"];

export default function EventForm({ plantId }: { plantId: string }) {
  const [kind, setKind] = useState<EventKind>("note");
  const [text, setText] = useState("");
  const [quantity, setQuantity] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const payload: Record<string, unknown> = { text };
      if (quantity.trim() !== "") payload.quantity = Number(quantity);
      await postEvent(plantId, { kind, payload });
      setStatus("Logged.");
      setText("");
      setQuantity("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "failed to log event");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row sm:items-end"
    >
      <div>
        <label className="block text-xs font-medium text-slate-600">Kind</label>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as EventKind)}
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>
      <div className="flex-1">
        <label className="block text-xs font-medium text-slate-600">Note</label>
        <input
          type="text"
          required
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What happened?"
          className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
        />
      </div>
      <div className="w-28">
        <label className="block text-xs font-medium text-slate-600">Quantity (optional)</label>
        <input
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
        />
      </div>
      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
      >
        {busy ? "Logging..." : "Log event"}
      </button>
      {status && <span className="text-sm text-emerald-700">{status}</span>}
      {error && <span className="text-sm text-red-700">{error}</span>}
    </form>
  );
}
