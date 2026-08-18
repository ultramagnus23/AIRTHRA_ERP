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
      setLoading(true);
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
      setLoading(true);
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
      setLoading(true);
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
      setLoading(true);
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
          <h1 className="font-display text-2xl font-light text-fg">Drawings</h1>
          <p className="text-sm text-mist">Revision chains per dwg_no. Released drawings are immutable - use Revise to create the next revision.</p>
        </div>
        <button
          onClick={() => setShowForm((s) => !s)}
          className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper"
        >
          {showForm ? "Cancel" : "+ New drawing"}
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
          <Field label="Drawing no. *" value={form.dwg_no} onChange={(v) => setForm({ ...form, dwg_no: v })} required />
          <Field label="Title" value={form.title} onChange={(v) => setForm({ ...form, title: v })} />
          <Field label="Revision" value={form.revision} onChange={(v) => setForm({ ...form, revision: v })} />
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
              {saving ? "Saving..." : "Create drawing"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : groups.size === 0 ? (
        <p className="text-sm text-mist">No drawings yet.</p>
      ) : (
        <div className="space-y-4">
          {Array.from(groups.entries()).map(([key, chain]) => {
            const sorted = [...chain].sort((a, b) => (a.revision ?? "").localeCompare(b.revision ?? ""));
            const project = projectByCode.get(sorted[0].project_id);
            return (
              <div key={key} className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="font-medium text-fg">{sorted[0].dwg_no} <span className="font-normal text-mist">- {project?.code ?? sorted[0].project_id}</span></h3>
                </div>
                <ol className="space-y-2">
                  {sorted.map((d, i) => (
                    <li key={d.id} className="flex items-center gap-3 rounded-lg border border-hair bg-midnight px-3 py-2">
                      <span className="font-mono text-xs text-mist">{i < sorted.length - 1 ? "↳ superseded" : "↳ current"}</span>
                      <span className="font-mono text-sm font-medium text-fg">Rev {d.revision || "-"}</span>
                      {editId === d.id ? (
                        <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} className="flex-1 rounded-lg border border-line bg-transparent px-2 py-1 text-sm text-fg focus:border-copper focus:outline-none" />
                      ) : (
                        <span className="flex-1 text-sm text-mist">{d.title || "-"}</span>
                      )}
                      <DrawingStatusBadge status={d.status} />
                      <div className="flex gap-2 text-xs whitespace-nowrap">
                        {editId === d.id ? (
                          <>
                            <button onClick={() => saveEditTitle(d.id)} disabled={saving} className="text-copper hover:underline">Save</button>
                            <button onClick={() => setEditId(null)} className="text-mist hover:underline">Cancel</button>
                          </>
                        ) : d.status === "released" ? (
                          <button onClick={() => setReviseId(reviseId === d.id ? null : d.id)} className="text-copper hover:underline">Revise</button>
                        ) : d.status === "superseded" ? (
                          <span className="text-mist">immutable (superseded)</span>
                        ) : (
                          <>
                            <button onClick={() => { setEditId(d.id); setEditTitle(d.title ?? ""); }} className="text-copper hover:underline">Edit</button>
                            <button onClick={() => handleRelease(d.id)} className="text-copper hover:underline">Release</button>
                          </>
                        )}
                      </div>
                      {reviseId === d.id && (
                        <div className="flex items-center gap-2">
                          <input value={reviseRev} onChange={(e) => setReviseRev(e.target.value)} className="w-16 rounded-lg border border-line bg-transparent px-2 py-1 text-sm text-fg focus:border-copper focus:outline-none" placeholder="new rev" />
                          <button onClick={() => handleRevise(d.id)} disabled={saving} className="rounded-lg bg-rust px-2 py-1 text-xs text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">Confirm revise</button>
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
  if (status === "released") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-moss/15 px-2 py-0.5 text-xs font-medium text-moss">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-moss" aria-hidden />
        Released
      </span>
    );
  }
  if (status === "for_review") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-copper/15 px-2 py-0.5 text-xs font-medium text-copper">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-copper" aria-hidden />
        For review
      </span>
    );
  }
  if (status === "superseded") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-midnight px-2 py-0.5 text-xs font-medium text-mist">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-mist" aria-hidden />
        Superseded
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

function Field({
  label, value, onChange, className, required,
}: { label: string; value: string; onChange: (v: string) => void; className?: string; required?: boolean }) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="mb-1 block font-medium text-fg">{label}</span>
      <input
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none"
      />
    </label>
  );
}
