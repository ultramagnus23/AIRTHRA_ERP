"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createBom, listBoms, listDrawings, listProjects, ErpApiError } from "@/lib/erp/api";
import type { Bom, Drawing, Project } from "@/lib/erp/types";

const emptyForm = { project_id: "", drawing_id: "", name: "", revision: "A" };

export default function BomsPage() {
  const [boms, setBoms] = useState<Bom[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  function load() {
    setLoading(true);
    Promise.all([listBoms(), listProjects(), listDrawings()])
      .then(([b, p, d]) => { setBoms(b); setProjects(p); setDrawings(d); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const bom = await createBom({ project_id: form.project_id, drawing_id: form.drawing_id || null, name: form.name, revision: form.revision || null });
      setForm(emptyForm);
      setShowForm(false);
      window.location.href = `/boms/${bom.id}`;
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create BOM");
      setSaving(false);
    }
  }

  const projectByCode = new Map(projects.map((p) => [p.id, p]));

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Bills of Material</h1>
          <p className="text-sm text-slate-500">Server-computed weight/cost. Released BOMs are immutable.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
          {showForm ? "Cancel" : "+ New BOM"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Project *</span>
            <select required value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- select --</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Drawing</span>
            <select value={form.drawing_id} onChange={(e) => setForm({ ...form, drawing_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- none --</option>
              {drawings.filter((d) => !form.project_id || d.project_id === form.project_id).map((d) => <option key={d.id} value={d.id}>{d.dwg_no} rev {d.revision}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Name *</span>
            <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Revision</span>
            <input value={form.revision} onChange={(e) => setForm({ ...form, revision: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Creating..." : "Create BOM & open editor"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : boms.length === 0 ? (
        <p className="text-sm text-slate-500">No BOMs yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2">Name</th><th className="px-3 py-2">Project</th><th className="px-3 py-2">Revision</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {boms.map((b) => (
                <tr key={b.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2"><Link href={`/boms/${b.id}`} className="font-medium text-teal-700 hover:underline">{b.name}</Link></td>
                  <td className="px-3 py-2 text-slate-600">{projectByCode.get(b.project_id)?.code ?? b.project_id}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-600">{b.revision || "-"}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${b.status === "released" ? "bg-green-100 text-green-800" : "bg-slate-100 text-slate-700"}`}>{b.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
