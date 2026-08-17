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
      className="flex flex-col gap-3 rounded-2xl border border-hair bg-panel p-4 sm:flex-row sm:items-end"
      style={{ boxShadow: "var(--shadow-sm)" }}
    >
      <div>
        <label className="block text-xs font-medium text-mist">Kind</label>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as EventKind)}
          className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
        >
          {KINDS.map((k) => (
            <option key={k} value={k} className="bg-panel">
              {k}
            </option>
          ))}
        </select>
      </div>
      <div className="flex-1">
        <label className="block text-xs font-medium text-mist">Note</label>
        <input
          type="text"
          required
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What happened?"
          className="w-full rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none"
        />
      </div>
      <div className="w-28">
        <label className="block text-xs font-medium text-mist">Quantity (optional)</label>
        <input
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          className="w-full rounded-lg border border-line bg-transparent px-2 py-1.5 font-mono text-sm text-fg focus:border-copper focus:outline-none"
        />
      </div>
      <button
        type="submit"
        disabled={busy}
        className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50"
      >
        {busy ? "Logging…" : "Log event"}
      </button>
      {status && <span className="text-sm text-moss">{status}</span>}
      {error && <span className="text-sm text-rust">{error}</span>}
    </form>
  );
}
