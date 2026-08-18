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
      setLoading(true);
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
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to update job status");
    }
  }

  const projectByCode = new Map(projects.map((p) => [p.id, p]));
  const bomById = new Map(boms.map((b) => [b.id, b]));

  const COLUMN_ACCENT: Record<FabricationJobStatus, string> = {
    planned: "text-mist",
    in_progress: "text-copper",
    on_hold: "text-copper",
    completed: "text-moss",
    cancelled: "text-rust",
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-light text-fg">Fabrication Jobs</h1>
          <p className="text-sm text-mist">Grouped-by-status board. Status changes follow the backend&apos;s allowed transitions only.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">
          {showForm ? "Cancel" : "+ New job"}
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
            <span className="mb-1 block font-medium text-fg">BOM</span>
            <select value={form.bom_id} onChange={(e) => setForm({ ...form, bom_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- none --</option>
              {boms.filter((b) => !form.project_id || b.project_id === form.project_id).map((b) => <option key={b.id} value={b.id} className="bg-panel">{b.name} rev {b.revision}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Unit serial</span>
            <select value={form.unit_serial} onChange={(e) => setForm({ ...form, unit_serial: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- none --</option>
              {serials.map((s) => <option key={s.serial} value={s.serial} className="bg-panel">{s.serial}</option>)}
            </select>
          </label>
          <div className="flex items-end">
            <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
              {saving ? "Saving..." : "Create job"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-5">
          {COLUMNS.map((col) => (
            <div key={col.status} className="rounded-2xl bg-midnight p-3">
              <h3 className="mb-2 flex items-center justify-between font-mono text-xs tracking-[0.1em] uppercase text-mist">
                <span className={COLUMN_ACCENT[col.status]}>{col.label}</span>
                <span className="rounded-md bg-panel px-1.5 text-mist">{jobs.filter((j) => j.status === col.status).length}</span>
              </h3>
              <div className="space-y-2">
                {jobs.filter((j) => j.status === col.status).map((j) => (
                  <div key={j.id} className="rounded-2xl border border-hair bg-panel p-2 text-xs" style={{ boxShadow: "var(--shadow-sm)" }}>
                    <p className="font-medium text-fg">{projectByCode.get(j.project_id)?.code ?? j.project_id.slice(0, 8)}</p>
                    {j.bom_id && <p className="text-mist">{bomById.get(j.bom_id)?.name ?? j.bom_id.slice(0, 8)}</p>}
                    {j.unit_serial && <p className="font-mono text-mist">serial {j.unit_serial}</p>}
                    <div className="mt-1 flex flex-wrap gap-1">
                      {col.next.map((n) => (
                        <button key={n} onClick={() => advance(j, n)} className="rounded-md border border-line px-1.5 py-0.5 text-[11px] text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:border-copper">
                          &rarr; {n.replaceAll("_", " ")}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                {jobs.filter((j) => j.status === col.status).length === 0 && <p className="text-xs text-mist">-</p>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
