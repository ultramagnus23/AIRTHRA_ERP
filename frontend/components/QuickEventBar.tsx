"use client";

import { useState } from "react";
import { postEvent, ApiError } from "@/lib/api";
import { QUICK_EVENTS, type QuickEvent } from "@/lib/types";

/** One-tap operator event logging.
 *
 * Every row written here is ML ground truth. When an operator tops up KOH
 * or swaps a stator, the sensor data step-changes; without a label the
 * model reads that as an anomaly and learns the wrong thing. The general
 * events form below this one still exists for anything unusual, but the
 * actions that actually recur are single buttons on purpose - a dropdown
 * plus a free-text note will not get filled in during an incident, and an
 * incident is precisely when the label is most valuable.
 *
 * Quantity-bearing actions (KOH volume) prompt inline before filing,
 * because the amount is itself a model feature. Everything else posts
 * immediately on tap.
 */
export default function QuickEventBar({ plantId }: { plantId: string }) {
  const [pending, setPending] = useState<QuickEvent | null>(null);
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [logged, setLogged] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function file(ev: QuickEvent, quantity?: number) {
    setBusy(ev.kind);
    setError(null);
    setLogged(null);
    try {
      const payload: Record<string, unknown> = { action: ev.label };
      if (ev.tag) payload.tag = ev.tag;
      if (quantity !== undefined) {
        payload.quantity = quantity;
        payload.unit = ev.quantity?.unit;
      }
      await postEvent(plantId, { kind: ev.kind, payload });
      setLogged(ev.label);
      setPending(null);
      setQty("");
      // Confirmation is transient - this bar is used repeatedly in a
      // session and a persistent banner would push the buttons around.
      setTimeout(() => setLogged(null), 4000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `failed to log "${ev.label}"`);
    } finally {
      setBusy(null);
    }
  }

  function onTap(ev: QuickEvent) {
    if (ev.quantity) {
      setPending(ev);
      setError(null);
      return;
    }
    void file(ev);
  }

  return (
    <section
      className="rounded-2xl border border-hair bg-panel p-4"
      style={{ boxShadow: "var(--shadow-sm)" }}
    >
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">Log an action</h2>
        <p className="font-mono text-[11px] text-mist">
          One tap. These labels train the predictive models — log it even if it seems minor.
        </p>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {QUICK_EVENTS.map((ev, i) => {
          const isCritical = ev.severity === "critical";
          const isBusy = busy === ev.kind;
          return (
            <button
              key={ev.kind}
              type="button"
              onClick={() => onTap(ev)}
              disabled={isBusy}
              style={{ animationDelay: `calc(var(--stagger) * ${i} / 2)` }}
              className={`air-rise air-lift flex items-baseline gap-2 rounded-full border px-3.5 py-2 text-sm font-medium disabled:opacity-50 ${
                isCritical
                  ? "border-rust/50 text-rust hover:border-rust hover:bg-rust/10"
                  : "border-line text-fg hover:border-copper hover:bg-copper/10"
              }`}
            >
              {ev.label}
              {ev.tag && <span className="font-mono text-[10px] text-mist">{ev.tag}</span>}
            </button>
          );
        })}
      </div>

      {pending && (
        <div className="air-rise mt-3 flex flex-wrap items-end gap-3 rounded-xl border border-copper/40 bg-midnight p-3">
          <div>
            <label
              htmlFor="quick-event-qty"
              className="block font-mono text-[11px] text-mist"
            >
              {pending.label} — {pending.quantity?.hint}
            </label>
            <div className="mt-1 flex items-center gap-2">
              <input
                id="quick-event-qty"
                type="number"
                step="any"
                min="0"
                autoFocus
                value={qty}
                onChange={(e) => setQty(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && qty.trim() !== "") void file(pending, Number(qty));
                  if (e.key === "Escape") setPending(null);
                }}
                className="w-32 rounded-lg border border-line bg-transparent px-2 py-1.5 font-mono text-sm text-fg focus:border-copper focus:outline-none"
              />
              <span className="font-mono text-xs text-mist">{pending.quantity?.unit}</span>
            </div>
          </div>
          <button
            type="button"
            disabled={qty.trim() === "" || busy !== null}
            onClick={() => void file(pending, Number(qty))}
            className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
          >
            Log it
          </button>
          <button
            type="button"
            onClick={() => setPending(null)}
            className="air-track px-2 py-2 text-sm text-mist hover:text-fg"
          >
            Cancel
          </button>
        </div>
      )}

      {/* Status is polite-live: it must announce to a screen reader without
          stealing focus from the button the operator just pressed. */}
      <div aria-live="polite" className="mt-2 min-h-5 font-mono text-xs">
        {logged && <span className="text-moss">Logged “{logged}”.</span>}
        {error && <span className="text-rust">{error}</span>}
      </div>
    </section>
  );
}
