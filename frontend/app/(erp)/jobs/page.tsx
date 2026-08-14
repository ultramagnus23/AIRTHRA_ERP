"use client";

import { useEffect, useState } from "react";
import {
  createFabricationJob, listBoms, listFabricationJobs, listProjects, listUnitSerials,
  updateFabricationJobStatus, ErpApiError,
} from "@/lib/erp/api";
import type { Bom, FabricationJob, FabricationJobStatus, Project, UnitSerial } from "@/lib/erp/types";

// Simple grouped/columned board (documented choice: a table grouped by
// status column, not a drag-and-drop kanban - status changes go through
// explicit "Advance" buttons that only offer the transitions
// api/routers/production.py's _JOB_TRANSITIONS actually allows, so the UI
// never implies a move the backend would reject).
const COLUMNS: { status: FabricationJobStatus; label: string; next: FabricationJobStatus[] }[] = [
  { status: "planned", label: "Planned", next: ["in_progress", "cancelled"] },
  { status: "in_progress", label: "In progress", next: ["on_hold", "completed", "cancelled"] },
  { status: "on_hold", label: "On hold", next: ["in_progress", "cancelled"] },
  { status: "completed", label: "Completed", next: [] },
  { status: "cancelled", label: "Cancelled", next: [] },
];

const emptyForm = { project_id: "", bom_id: "", unit_serial: "" };

export default function JobsPage() {
  const [jobs, setJobs] = useState<FabricationJob[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [boms, setBoms] = useState<Bom[]>([]);
  const [serials, setSerials] = useState<UnitSerial[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  function load() {
    setLoading(true);
    Promise.all([listFabricationJobs(), listProjects(), listBoms(), listUnitSerials()])
      .then(([j, p, b, s]) => { setJobs(j.jobs); setProjects(p); setBoms(b); setSerials(s.unit_serials); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createFabricationJob({ project_id: form.project_id, bom_id: form.bom_id || null, unit_serial: form.unit_serial || null });
      setForm(emptyForm);
      setShowForm(false);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create job");
    } finally {
      setSaving(false);
    }
  }

  async function advance(job: FabricationJob, next: FabricationJobStatus) {
    setError(null);
    try {
      await updateFabricationJobStatus(job.id, next);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to update job status");
    }
  }

  const projectByCode = new Map(projects.map((p) => [p.id, p]));
  const bomById = new Map(boms.map((b) => [b.id, b]));

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Fabrication Jobs</h1>
          <p className="text-sm text-slate-500">Grouped-by-status board. Status changes follow the backend&apos;s allowed transitions only.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
          {showForm ? "Cancel" : "+ New job"}
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
            <span className="mb-1 block font-medium text-slate-700">BOM</span>
            <select value={form.bom_id} onChange={(e) => setForm({ ...form, bom_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- none --</option>
              {boms.filter((b) => !form.project_id || b.project_id === form.project_id).map((b) => <option key={b.id} value={b.id}>{b.name} rev {b.revision}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Unit serial</span>
            <select value={form.unit_serial} onChange={(e) => setForm({ ...form, unit_serial: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- none --</option>
              {serials.map((s) => <option key={s.serial} value={s.serial}>{s.serial}</option>)}
            </select>
          </label>
          <div className="flex items-end">
            <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving..." : "Create job"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-5">
          {COLUMNS.map((col) => (
            <div key={col.status} className="rounded-lg border border-slate-200 bg-white p-3">
              <h3 className="mb-2 flex items-center justify-between text-xs font-semibold uppercase text-slate-500">
                {col.label} <span className="rounded-full bg-slate-100 px-1.5 text-slate-600">{jobs.filter((j) => j.status === col.status).length}</span>
              </h3>
              <div className="space-y-2">
                {jobs.filter((j) => j.status === col.status).map((j) => (
                  <div key={j.id} className="rounded-md border border-slate-200 p-2 text-xs">
                    <p className="font-medium text-slate-900">{projectByCode.get(j.project_id)?.code ?? j.project_id.slice(0, 8)}</p>
                    {j.bom_id && <p className="text-slate-500">{bomById.get(j.bom_id)?.name ?? j.bom_id.slice(0, 8)}</p>}
                    {j.unit_serial && <p className="text-slate-500">serial {j.unit_serial}</p>}
                    <div className="mt-1 flex flex-wrap gap-1">
                      {col.next.map((n) => (
                        <button key={n} onClick={() => advance(j, n)} className="rounded border border-teal-700 px-1.5 py-0.5 text-[11px] text-teal-700 hover:bg-teal-50">
                          &rarr; {n.replaceAll("_", " ")}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                {jobs.filter((j) => j.status === col.status).length === 0 && <p className="text-xs text-slate-400">-</p>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
