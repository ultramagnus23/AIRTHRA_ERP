"use client";

import { useEffect, useState } from "react";
import { createMaterial, listMaterials, updateMaterial, ErpApiError } from "@/lib/erp/api";
import type { Material } from "@/lib/erp/types";

const emptyForm = { name: "", grade: "", density_kg_m3: "", rate_per_kg: "", hsn: "" };

export default function MaterialsPage() {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState(emptyForm);

  function load() {
    setLoading(true);
    listMaterials()
      .then(setMaterials)
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load materials"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createMaterial({
        name: form.name,
        grade: form.grade || null,
        density_kg_m3: form.density_kg_m3 ? Number(form.density_kg_m3) : null,
        rate_per_kg: form.rate_per_kg ? Number(form.rate_per_kg) : null,
        hsn: form.hsn || null,
      });
      setForm(emptyForm);
      setShowForm(false);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create material");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(m: Material) {
    setEditId(m.id);
    setEditForm({
      name: m.name, grade: m.grade ?? "",
      density_kg_m3: m.density_kg_m3 != null ? String(m.density_kg_m3) : "",
      rate_per_kg: m.rate_per_kg != null ? String(m.rate_per_kg) : "",
      hsn: m.hsn ?? "",
    });
  }

  async function saveEdit(id: string) {
    setSaving(true);
    setError(null);
    try {
      await updateMaterial(id, {
        name: editForm.name,
        grade: editForm.grade || null,
        density_kg_m3: editForm.density_kg_m3 ? Number(editForm.density_kg_m3) : null,
        rate_per_kg: editForm.rate_per_kg ? Number(editForm.rate_per_kg) : null,
        hsn: editForm.hsn || null,
      });
      setEditId(null);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to update material");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Materials</h1>
          <p className="text-sm text-slate-500">density_kg_m3 / rate_per_kg drive the BOM weight/cost calculator.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
          {showForm ? "Cancel" : "+ New material"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-5">
          <Field label="Name *" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />
          <Field label="Grade" value={form.grade} onChange={(v) => setForm({ ...form, grade: v })} />
          <Field label="Density (kg/m3)" value={form.density_kg_m3} onChange={(v) => setForm({ ...form, density_kg_m3: v })} type="number" />
          <Field label="Rate (per kg)" value={form.rate_per_kg} onChange={(v) => setForm({ ...form, rate_per_kg: v })} type="number" />
          <Field label="HSN" value={form.hsn} onChange={(v) => setForm({ ...form, hsn: v })} />
          <div className="sm:col-span-5">
            <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving..." : "Create material"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Grade</th>
                <th className="px-3 py-2">Density (kg/m3)</th>
                <th className="px-3 py-2">Rate/kg</th>
                <th className="px-3 py-2">HSN</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {materials.map((m) =>
                editId === m.id ? (
                  <tr key={m.id} className="border-t border-slate-100 bg-teal-50/40">
                    <td className="px-3 py-2"><input className="w-full rounded border border-slate-300 px-2 py-1" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-full rounded border border-slate-300 px-2 py-1" value={editForm.grade} onChange={(e) => setEditForm({ ...editForm, grade: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-24 rounded border border-slate-300 px-2 py-1" value={editForm.density_kg_m3} onChange={(e) => setEditForm({ ...editForm, density_kg_m3: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-24 rounded border border-slate-300 px-2 py-1" value={editForm.rate_per_kg} onChange={(e) => setEditForm({ ...editForm, rate_per_kg: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-20 rounded border border-slate-300 px-2 py-1" value={editForm.hsn} onChange={(e) => setEditForm({ ...editForm, hsn: e.target.value })} /></td>
                    <td className="space-x-2 px-3 py-2 whitespace-nowrap">
                      <button onClick={() => saveEdit(m.id)} disabled={saving} className="text-teal-700 hover:underline">Save</button>
                      <button onClick={() => setEditId(null)} className="text-slate-500 hover:underline">Cancel</button>
                    </td>
                  </tr>
                ) : (
                  <tr key={m.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-3 py-2 font-medium text-slate-900">{m.name}</td>
                    <td className="px-3 py-2 text-slate-600">{m.grade || "-"}</td>
                    <td className="px-3 py-2 text-slate-600">{m.density_kg_m3 ?? "-"}</td>
                    <td className="px-3 py-2 text-slate-600">{m.rate_per_kg ?? "-"}</td>
                    <td className="px-3 py-2 text-slate-600">{m.hsn || "-"}</td>
                    <td className="px-3 py-2 text-right">
                      <button onClick={() => startEdit(m)} className="text-teal-700 hover:underline">Edit</button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Field({
  label, value, onChange, className, type = "text", required,
}: { label: string; value: string; onChange: (v: string) => void; className?: string; type?: string; required?: boolean }) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-teal-500 focus:outline-none"
      />
    </label>
  );
}
