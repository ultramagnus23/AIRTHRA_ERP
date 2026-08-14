"use client";

import { useEffect, useState } from "react";
import {
  createDrawing, listDrawings, listProjects, releaseDrawing, reviseDrawing, updateDrawing, ErpApiError,
} from "@/lib/erp/api";
import type { Drawing, Project } from "@/lib/erp/types";

const emptyForm = { project_id: "", dwg_no: "", title: "", revision: "A" };

export default function DrawingsPage() {
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [reviseId, setReviseId] = useState<string | null>(null);
  const [reviseRev, setReviseRev] = useState("B");
  const [editId, setEditId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  function load() {
    setLoading(true);
    Promise.all([listDrawings(), listProjects()])
      .then(([d, p]) => { setDrawings(d); setProjects(p); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createDrawing({ project_id: form.project_id, dwg_no: form.dwg_no, title: form.title || null, revision: form.revision || null });
      setForm(emptyForm);
      setShowForm(false);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create drawing");
    } finally {
      setSaving(false);
    }
  }

  async function handleRelease(id: string) {
    setError(null);
    try {
      await releaseDrawing(id);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to release drawing");
    }
  }

  async function handleRevise(id: string) {
    setSaving(true);
    setError(null);
    try {
      await reviseDrawing(id, { new_revision: reviseRev });
      setReviseId(null);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to revise drawing");
    } finally {
      setSaving(false);
    }
  }

  async function saveEditTitle(id: string) {
    setSaving(true);
    setError(null);
    try {
      await updateDrawing(id, { title: editTitle });
      setEditId(null);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to update drawing (it may be released - use Revise instead)");
    } finally {
      setSaving(false);
    }
  }

  const projectByCode = new Map(projects.map((p) => [p.id, p]));

  // Group drawings by (project_id, dwg_no) to show revision chains together.
  const groups = new Map<string, Drawing[]>();
  for (const d of drawings) {
    const key = `${d.project_id}::${d.dwg_no}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(d);
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Drawings</h1>
          <p className="text-sm text-slate-500">Revision chains per dwg_no. Released drawings are immutable - use Revise to create the next revision.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
          {showForm ? "Cancel" : "+ New drawing"}
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
          <Field label="Drawing no. *" value={form.dwg_no} onChange={(v) => setForm({ ...form, dwg_no: v })} required />
          <Field label="Title" value={form.title} onChange={(v) => setForm({ ...form, title: v })} />
          <Field label="Revision" value={form.revision} onChange={(v) => setForm({ ...form, revision: v })} />
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving..." : "Create drawing"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : groups.size === 0 ? (
        <p className="text-sm text-slate-500">No drawings yet.</p>
      ) : (
        <div className="space-y-4">
          {Array.from(groups.entries()).map(([key, chain]) => {
            const sorted = [...chain].sort((a, b) => (a.revision ?? "").localeCompare(b.revision ?? ""));
            const project = projectByCode.get(sorted[0].project_id);
            return (
              <div key={key} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="font-semibold text-slate-900">{sorted[0].dwg_no} <span className="font-normal text-slate-500">- {project?.code ?? sorted[0].project_id}</span></h3>
                </div>
                <ol className="space-y-2">
                  {sorted.map((d, i) => (
                    <li key={d.id} className="flex items-center gap-3 rounded-md border border-slate-100 px-3 py-2">
                      <span className="text-xs text-slate-400">{i < sorted.length - 1 ? "↳ superseded" : "↳ current"}</span>
                      <span className="font-mono text-sm font-medium text-slate-800">Rev {d.revision || "-"}</span>
                      {editId === d.id ? (
                        <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm" />
                      ) : (
                        <span className="flex-1 text-sm text-slate-600">{d.title || "-"}</span>
                      )}
                      <DrawingStatusBadge status={d.status} />
                      <div className="flex gap-2 text-xs whitespace-nowrap">
                        {editId === d.id ? (
                          <>
                            <button onClick={() => saveEditTitle(d.id)} disabled={saving} className="text-teal-700 hover:underline">Save</button>
                            <button onClick={() => setEditId(null)} className="text-slate-500 hover:underline">Cancel</button>
                          </>
                        ) : d.status === "released" ? (
                          <button onClick={() => setReviseId(reviseId === d.id ? null : d.id)} className="text-teal-700 hover:underline">Revise</button>
                        ) : d.status === "superseded" ? (
                          <span className="text-slate-400">immutable (superseded)</span>
                        ) : (
                          <>
                            <button onClick={() => { setEditId(d.id); setEditTitle(d.title ?? ""); }} className="text-teal-700 hover:underline">Edit</button>
                            <button onClick={() => handleRelease(d.id)} className="text-teal-700 hover:underline">Release</button>
                          </>
                        )}
                      </div>
                      {reviseId === d.id && (
                        <div className="flex items-center gap-2">
                          <input value={reviseRev} onChange={(e) => setReviseRev(e.target.value)} className="w-16 rounded border border-slate-300 px-2 py-1 text-sm" placeholder="new rev" />
                          <button onClick={() => handleRevise(d.id)} disabled={saving} className="rounded bg-teal-700 px-2 py-1 text-xs text-white">Confirm revise</button>
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function DrawingStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    draft: "bg-slate-100 text-slate-700", for_review: "bg-blue-100 text-blue-800",
    released: "bg-green-100 text-green-800", superseded: "bg-slate-200 text-slate-500",
  };
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? "bg-slate-100"}`}>{status}</span>;
}

function Field({
  label, value, onChange, className, required,
}: { label: string; value: string; onChange: (v: string) => void; className?: string; required?: boolean }) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input required={required} value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-teal-500 focus:outline-none" />
    </label>
  );
}
