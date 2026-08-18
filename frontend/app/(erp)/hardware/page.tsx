"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createHardwareComponent,
  deleteHardwareComponent,
  listHardwareComponents,
  updateHardwareComponent,
  ErpApiError,
} from "@/lib/erp/api";
import type { HardwareComponent } from "@/lib/erp/types";

const emptyForm = { category: "", sort_order: "", item: "", spec_function: "", tag_id: "", tier: "", segment: "", cost_inr: "" };
type FormState = typeof emptyForm;

function toEditForm(c: HardwareComponent): FormState {
  return {
    category: c.category,
    sort_order: String(c.sort_order),
    item: c.item,
    spec_function: c.spec_function ?? "",
    tag_id: c.tag_id ?? "",
    tier: c.tier != null ? String(c.tier) : "",
    segment: c.segment ?? "",
    cost_inr: c.cost_inr != null ? String(c.cost_inr) : "",
  };
}

export default function HardwareComponentsPage() {
  const [components, setComponents] = useState<HardwareComponent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<FormState>(emptyForm);

  function load() {
    listHardwareComponents()
      .then(setComponents)
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load hardware components"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  const grouped = useMemo(() => {
    const byCategory = new Map<string, { order: number; items: HardwareComponent[] }>();
    for (const c of components) {
      const existing = byCategory.get(c.category);
      if (existing) {
        existing.items.push(c);
      } else {
        byCategory.set(c.category, { order: c.category_order, items: [c] });
      }
    }
    return Array.from(byCategory.entries()).sort((a, b) => a[1].order - b[1].order);
  }, [components]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      // New components not matching an existing category go at the end
      // (category_order = max + 1); within a known category they append
      // after the highest sort_order already seen for it.
      const existingOrders = components
        .filter((c) => c.category === form.category)
        .map((c) => c.sort_order);
      const nextSort = existingOrders.length ? Math.max(...existingOrders) + 1 : 1;
      const categoryOrder = components.find((c) => c.category === form.category)?.category_order
        ?? (components.length ? Math.max(...components.map((c) => c.category_order)) + 1 : 1);

      await createHardwareComponent({
        category: form.category,
        category_order: categoryOrder,
        sort_order: form.sort_order ? Number(form.sort_order) : nextSort,
        item: form.item,
        spec_function: form.spec_function || null,
        tag_id: form.tag_id || null,
        tier: form.tier ? Number(form.tier) : null,
        segment: form.segment || null,
        cost_inr: form.cost_inr ? Number(form.cost_inr) : null,
      });
      setForm(emptyForm);
      setShowForm(false);
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create component");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(c: HardwareComponent) {
    setEditId(c.id);
    setEditForm(toEditForm(c));
  }

  async function saveEdit(id: string) {
    setSaving(true);
    setError(null);
    try {
      await updateHardwareComponent(id, {
        category: editForm.category,
        sort_order: editForm.sort_order ? Number(editForm.sort_order) : undefined,
        item: editForm.item,
        spec_function: editForm.spec_function || null,
        tag_id: editForm.tag_id || null,
        tier: editForm.tier ? Number(editForm.tier) : null,
        segment: editForm.segment || null,
        cost_inr: editForm.cost_inr ? Number(editForm.cost_inr) : null,
      });
      setEditId(null);
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to update component");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteHardwareComponent(id);
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to delete component");
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-light text-fg">Hardware &amp; Instrumentation BOM</h1>
          <p className="text-sm text-mist">
            The edge-unit electrical/instrumentation register - compute &amp; power, gas/CEMS stack, process
            sensors &amp; translators, comms &amp; actuators, and field survival gear. Tracked and reported per unit built.
          </p>
        </div>
        <button
          onClick={() => setShowForm((s) => !s)}
          className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper"
        >
          {showForm ? "Cancel" : "+ New component"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      {showForm && (
        <form
          onSubmit={handleCreate}
          className="mb-6 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4"
          style={{ boxShadow: "var(--shadow-sm)" }}
        >
          <Field label="Category *" value={form.category} onChange={(v) => setForm({ ...form, category: v })} required />
          <Field label="Item *" value={form.item} onChange={(v) => setForm({ ...form, item: v })} required />
          <Field label="Tag ID" value={form.tag_id} onChange={(v) => setForm({ ...form, tag_id: v })} />
          <Field label="Segment" value={form.segment} onChange={(v) => setForm({ ...form, segment: v })} />
          <Field label="Spec / diagnostic purpose" value={form.spec_function} onChange={(v) => setForm({ ...form, spec_function: v })} className="sm:col-span-2" />
          <Field label="Tier (1/2/3)" value={form.tier} onChange={(v) => setForm({ ...form, tier: v })} type="number" />
          <Field label="Cost (INR)" value={form.cost_inr} onChange={(v) => setForm({ ...form, cost_inr: v })} type="number" />
          <Field label="Sort order (optional)" value={form.sort_order} onChange={(v) => setForm({ ...form, sort_order: v })} type="number" />
          <div className="sm:col-span-4">
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50"
            >
              {saving ? "Saving…" : "Create component"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-mist">Loading…</p>
      ) : (
        <div className="flex flex-col gap-6">
          {grouped.map(([category, { items }]) => (
            <section key={category}>
              <div className="mb-2 flex items-center gap-2">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-copper" aria-hidden />
                <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">{category}</h2>
                <span className="font-mono text-[10px] text-mist">
                  ({items.length}
                  {items.some((i) => i.cost_inr != null)
                    ? ` — ₹${items.reduce((sum, i) => sum + Number(i.cost_inr ?? 0), 0).toLocaleString("en-IN")}`
                    : ""}
                  )
                </span>
              </div>
              <div
                className="relative overflow-hidden overflow-x-auto rounded-2xl border border-hair bg-panel"
                style={{ boxShadow: "var(--shadow-sm)" }}
              >
                <div className="absolute inset-x-0 top-0 h-[2px]" style={{ background: "oklch(0.72 0.15 54 / 0.55)" }} aria-hidden />
                <table className="w-full text-left text-sm">
                  <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
                    <tr>
                      <th className="px-3 py-2">Tag</th>
                      <th className="px-3 py-2">Item</th>
                      <th className="px-3 py-2">Segment</th>
                      <th className="px-3 py-2">Tier</th>
                      <th className="px-3 py-2">Spec / Diagnostic Purpose</th>
                      <th className="px-3 py-2">Cost</th>
                      <th className="px-3 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((c) =>
                      editId === c.id ? (
                        <tr key={c.id} className="border-t border-hair bg-midnight">
                          <td className="px-3 py-2">
                            <input className="w-20 rounded-lg border border-line bg-transparent px-2 py-1 font-mono text-fg focus:border-copper focus:outline-none" value={editForm.tag_id} onChange={(e) => setEditForm({ ...editForm, tag_id: e.target.value })} />
                          </td>
                          <td className="px-3 py-2">
                            <input className="w-full min-w-40 rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.item} onChange={(e) => setEditForm({ ...editForm, item: e.target.value })} />
                          </td>
                          <td className="px-3 py-2">
                            <input className="w-28 rounded-lg border border-line bg-transparent px-2 py-1 font-mono text-fg focus:border-copper focus:outline-none" value={editForm.segment} onChange={(e) => setEditForm({ ...editForm, segment: e.target.value })} />
                          </td>
                          <td className="px-3 py-2">
                            <select className="rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.tier} onChange={(e) => setEditForm({ ...editForm, tier: e.target.value })}>
                              <option value="" className="bg-panel">-</option>
                              <option value="1" className="bg-panel">Tier 1</option>
                              <option value="2" className="bg-panel">Tier 2</option>
                              <option value="3" className="bg-panel">Tier 3</option>
                            </select>
                          </td>
                          <td className="px-3 py-2">
                            <input className="w-full min-w-56 rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.spec_function} onChange={(e) => setEditForm({ ...editForm, spec_function: e.target.value })} />
                          </td>
                          <td className="px-3 py-2">
                            <input className="w-24 rounded-lg border border-line bg-transparent px-2 py-1 font-mono text-fg focus:border-copper focus:outline-none" value={editForm.cost_inr} onChange={(e) => setEditForm({ ...editForm, cost_inr: e.target.value })} />
                          </td>
                          <td className="space-x-2 px-3 py-2 whitespace-nowrap text-right">
                            <button onClick={() => saveEdit(c.id)} disabled={saving} className="text-copper hover:underline">Save</button>
                            <button onClick={() => setEditId(null)} className="text-mist hover:underline">Cancel</button>
                          </td>
                        </tr>
                      ) : (
                        <tr key={c.id} className="border-t border-hair hover:bg-midnight">
                          <td className="px-3 py-2 font-mono font-medium text-copper">{c.tag_id || "-"}</td>
                          <td className="px-3 py-2 font-mono font-medium text-fg">{c.item}</td>
                          <td className="px-3 py-2 font-mono text-mist">{c.segment || "-"}</td>
                          <td className="px-3 py-2">
                            <TierBadge tier={c.tier} />
                          </td>
                          <td className="max-w-xl px-3 py-2 text-mist">{c.spec_function || "-"}</td>
                          <td className="px-3 py-2 font-mono text-fg">
                            {c.cost_inr != null ? `₹${Number(c.cost_inr).toLocaleString("en-IN")}` : "-"}
                          </td>
                          <td className="space-x-2 px-3 py-2 text-right whitespace-nowrap">
                            <button onClick={() => startEdit(c)} className="text-copper hover:underline">Edit</button>
                            <button onClick={() => handleDelete(c.id)} className="text-rust hover:underline">Remove</button>
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
          {grouped.length === 0 && <p className="text-sm text-mist">No hardware components recorded yet.</p>}
        </div>
      )}
    </div>
  );
}

// Tier 1 = safety-critical (rust), Tier 2 = diagnostic/revenue (copper),
// Tier 3 = ML enrichment (mist) - matches FEED Addendum A Section 2.8.
function TierBadge({ tier }: { tier: number | null }) {
  if (tier === null) return <span className="text-mist">-</span>;
  const styles: Record<number, string> = {
    1: "border-rust text-rust",
    2: "border-copper text-copper",
    3: "border-line text-mist",
  };
  const labels: Record<number, string> = {
    1: "Tier 1 — safety-critical",
    2: "Tier 2 — diagnostic",
    3: "Tier 3 — ML enrichment",
  };
  return (
    <span className={`rounded-md border px-1.5 py-0.5 font-mono text-[11px] font-medium whitespace-nowrap ${styles[tier] ?? "border-line text-mist"}`}>
      {labels[tier] ?? `Tier ${tier}`}
    </span>
  );
}

function Field({
  label, value, onChange, className, type = "text", required,
}: { label: string; value: string; onChange: (v: string) => void; className?: string; type?: string; required?: boolean }) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="mb-1 block font-medium text-fg">{label}</span>
      <input
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none"
      />
    </label>
  );
}
