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
          <h1 className="font-display text-2xl font-light text-fg">Bills of Material</h1>
          <p className="text-sm text-mist">Server-computed weight/cost. Released BOMs are immutable.</p>
        </div>
        <button
          onClick={() => setShowForm((s) => !s)}
          className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper"
        >
          {showForm ? "Cancel" : "+ New BOM"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4" style={{ boxShadow: "var(--shadow-sm)" }}>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Project *</span>
            <select required value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- select --</option>
              {projects.map((p) => <option key={p.id} value={p.id} className="bg-panel">{p.code} - {p.name}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Drawing</span>
            <select value={form.drawing_id} onChange={(e) => setForm({ ...form, drawing_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- none --</option>
              {drawings.filter((d) => !form.project_id || d.project_id === form.project_id).map((d) => <option key={d.id} value={d.id} className="bg-panel">{d.dwg_no} rev {d.revision}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Name *</span>
            <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Revision</span>
            <input value={form.revision} onChange={(e) => setForm({ ...form, revision: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
              {saving ? "Creating..." : "Create BOM & open editor"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : boms.length === 0 ? (
        <p className="text-sm text-mist">No BOMs yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
              <tr><th className="px-3 py-2">Name</th><th className="px-3 py-2">Project</th><th className="px-3 py-2">Revision</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {boms.map((b) => (
                <tr key={b.id} className="border-t border-hair hover:bg-midnight">
                  <td className="px-3 py-2"><Link href={`/boms/${b.id}`} className="font-medium text-copper hover:underline">{b.name}</Link></td>
                  <td className="px-3 py-2 text-mist">{projectByCode.get(b.project_id)?.code ?? b.project_id}</td>
                  <td className="px-3 py-2 font-mono text-xs text-mist">{b.revision || "-"}</td>
                  <td className="px-3 py-2">
                    <BomStatusBadge status={b.status} />
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

function BomStatusBadge({ status }: { status: string }) {
  if (status === "released") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-moss/15 px-2 py-0.5 text-xs font-medium text-moss">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-moss" aria-hidden />
        Released
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-midnight px-2 py-0.5 text-xs font-medium text-mist">
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-mist" aria-hidden />
      Draft
    </span>
  );
}
