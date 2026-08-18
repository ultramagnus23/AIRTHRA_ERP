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
      setLoading(true);
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
      setLoading(true);
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
          <h1 className="font-display text-2xl font-light text-fg">Materials</h1>
          <p className="text-sm text-mist">density_kg_m3 / rate_per_kg drive the BOM weight/cost calculator.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">
          {showForm ? "Cancel" : "+ New material"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-5" style={{ boxShadow: "var(--shadow-sm)" }}>
          <Field label="Name *" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />
          <Field label="Grade" value={form.grade} onChange={(v) => setForm({ ...form, grade: v })} />
          <Field label="Density (kg/m3)" value={form.density_kg_m3} onChange={(v) => setForm({ ...form, density_kg_m3: v })} type="number" />
          <Field label="Rate (per kg)" value={form.rate_per_kg} onChange={(v) => setForm({ ...form, rate_per_kg: v })} type="number" />
          <Field label="HSN" value={form.hsn} onChange={(v) => setForm({ ...form, hsn: v })} />
          <div className="sm:col-span-5">
            <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
              {saving ? "Saving..." : "Create material"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
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
                  <tr key={m.id} className="border-t border-hair bg-midnight">
                    <td className="px-3 py-2"><input className="w-full rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-full rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.grade} onChange={(e) => setEditForm({ ...editForm, grade: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-24 rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.density_kg_m3} onChange={(e) => setEditForm({ ...editForm, density_kg_m3: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-24 rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.rate_per_kg} onChange={(e) => setEditForm({ ...editForm, rate_per_kg: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-20 rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.hsn} onChange={(e) => setEditForm({ ...editForm, hsn: e.target.value })} /></td>
                    <td className="space-x-2 px-3 py-2 whitespace-nowrap">
                      <button onClick={() => saveEdit(m.id)} disabled={saving} className="text-copper hover:underline">Save</button>
                      <button onClick={() => setEditId(null)} className="text-mist hover:underline">Cancel</button>
                    </td>
                  </tr>
                ) : (
                  <tr key={m.id} className="border-t border-hair hover:bg-midnight">
                    <td className="px-3 py-2 font-medium text-fg">{m.name}</td>
                    <td className="px-3 py-2 text-mist">{m.grade || "-"}</td>
                    <td className="px-3 py-2 font-mono text-mist">{m.density_kg_m3 ?? "-"}</td>
                    <td className="px-3 py-2 font-mono text-mist">{m.rate_per_kg ?? "-"}</td>
                    <td className="px-3 py-2 font-mono text-mist">{m.hsn || "-"}</td>
                    <td className="px-3 py-2 text-right">
                      <button onClick={() => startEdit(m)} className="text-copper hover:underline">Edit</button>
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
