"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createInventoryLot, getGrn, listGrn, listInventoryLots, listMaterials, ErpApiError } from "@/lib/erp/api";
import type { Grn, InventoryLot, Material } from "@/lib/erp/types";

const emptyForm = { grn_id: "", grn_line_id: "", material_id: "", qty_on_hand: "", unit: "kg", location: "", heat_no: "" };

export default function InventoryPage() {
  const [lots, setLots] = useState<InventoryLot[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [grns, setGrns] = useState<Grn[]>([]);
  const [selectedGrn, setSelectedGrn] = useState<Grn | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  function load() {
    setLoading(true);
    Promise.all([listInventoryLots(), listMaterials(), listGrn()])
      .then(([l, m, g]) => { setLots(l.lots); setMaterials(m); setGrns(g); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleSelectGrn(grnId: string) {
    setForm({ ...form, grn_id: grnId, grn_line_id: "" });
    if (!grnId) { setSelectedGrn(null); return; }
    try {
      setSelectedGrn(await getGrn(grnId));
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to load GRN lines");
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createInventoryLot({
        grn_line_id: form.grn_line_id || null, material_id: form.material_id,
        qty_on_hand: Number(form.qty_on_hand), unit: form.unit,
        location: form.location || null, heat_no: form.heat_no || null,
      });
      setForm(emptyForm);
      setSelectedGrn(null);
      setShowForm(false);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create lot");
    } finally {
      setSaving(false);
    }
  }

  const materialById = new Map(materials.map((m) => [m.id, m]));

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-900">Inventory Lots</h1>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
          {showForm ? "Cancel" : "+ New lot from GRN"}
        </button>
      </div>
      <p className="mb-4 text-sm text-slate-500">Each lot traces back to a GRN line and forward to fabrication/installation via genealogy.</p>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">GRN (optional, for traceability)</span>
            <select value={form.grn_id} onChange={(e) => handleSelectGrn(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- none --</option>
              {grns.map((g) => <option key={g.id} value={g.id}>{g.grn_no}</option>)}
            </select>
          </label>
          {selectedGrn && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">GRN line</span>
              <select value={form.grn_line_id} onChange={(e) => setForm({ ...form, grn_line_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
                <option value="">-- none --</option>
                {(selectedGrn.lines ?? []).map((l) => <option key={l.id} value={l.id}>{l.id.slice(0, 8)} (accepted {l.qty_accepted})</option>)}
              </select>
            </label>
          )}
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Material *</span>
            <select required value={form.material_id} onChange={(e) => setForm({ ...form, material_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- select --</option>
              {materials.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Qty on hand *</span>
            <input required type="number" step="any" value={form.qty_on_hand} onChange={(e) => setForm({ ...form, qty_on_hand: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Unit</span>
            <input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Location</span>
            <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Heat no.</span>
            <input value={form.heat_no} onChange={(e) => setForm({ ...form, heat_no: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving..." : "Create lot"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : lots.length === 0 ? (
        <p className="text-sm text-slate-500">No inventory lots yet - create one via GRN receiving.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2">Lot</th><th className="px-3 py-2">Material</th><th className="px-3 py-2">Qty on hand</th><th className="px-3 py-2">Location</th><th className="px-3 py-2">Heat no.</th></tr>
            </thead>
            <tbody>
              {lots.map((l) => (
                <tr key={l.lot_id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2"><Link href={`/inventory/${l.lot_id}`} className="font-mono text-xs font-medium text-teal-700 hover:underline">{l.lot_id.slice(0, 8)}</Link></td>
                  <td className="px-3 py-2 text-slate-800">{materialById.get(l.material_id)?.name ?? l.material_id}</td>
                  <td className="px-3 py-2 text-slate-600">{l.qty_on_hand} {l.unit}</td>
                  <td className="px-3 py-2 text-slate-600">{l.location || "-"}</td>
                  <td className="px-3 py-2 text-slate-600">{l.heat_no || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
