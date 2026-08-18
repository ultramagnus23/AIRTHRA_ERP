"use client";

import { useEffect, useState } from "react";
import {
  createProject, createTask, listProjects, listPos, listTasks, updateTask, ErpApiError,
} from "@/lib/erp/api";
import type { Po, Project, Task } from "@/lib/erp/types";

const emptyProjectForm = { code: "", name: "", client: "", status: "active" };
const emptyTaskForm = { project_id: "", title: "", assignee: "", due: "", blocked_by_po_id: "" };

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [pos, setPos] = useState<Po[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showProjectForm, setShowProjectForm] = useState(false);
  const [projectForm, setProjectForm] = useState(emptyProjectForm);
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [taskForm, setTaskForm] = useState(emptyTaskForm);
  const [saving, setSaving] = useState(false);
  const [filterProject, setFilterProject] = useState<string>("");

  function load() {
    Promise.all([listProjects(), listTasks(), listPos()])
      .then(([p, t, po]) => {
        setProjects(p);
        setTasks(t);
        setPos(po);
      })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleCreateProject(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createProject({
        code: projectForm.code, name: projectForm.name,
        client: projectForm.client || null, status: projectForm.status,
      });
      setProjectForm(emptyProjectForm);
      setShowProjectForm(false);
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create project");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateTask(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createTask({
        project_id: taskForm.project_id || null,
        title: taskForm.title,
        assignee: taskForm.assignee || null,
        due: taskForm.due || null,
        blocked_by_po_id: taskForm.blocked_by_po_id || null,
      });
      setTaskForm(emptyTaskForm);
      setShowTaskForm(false);
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create task");
    } finally {
      setSaving(false);
    }
  }

  async function markDone(t: Task) {
    setError(null);
    try {
      await updateTask(t.id, { status: t.status === "done" ? "open" : "done" });
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to update task");
    }
  }

  const poById = new Map(pos.map((p) => [p.id, p]));
  const visibleTasks = filterProject ? tasks.filter((t) => t.project_id === filterProject) : tasks;

  return (
    <div className="space-y-8">
      <div>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="font-display text-2xl font-light text-fg">Projects</h1>
            <p className="text-sm text-mist">Parent of drawings/BOMs/tasks.</p>
          </div>
          <button onClick={() => setShowProjectForm((s) => !s)} className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">
            {showProjectForm ? "Cancel" : "+ New project"}
          </button>
        </div>

        {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

        {showProjectForm && (
          <form onSubmit={handleCreateProject} className="mb-6 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4" style={{ boxShadow: "var(--shadow-sm)" }}>
            <Field label="Code *" value={projectForm.code} onChange={(v) => setProjectForm({ ...projectForm, code: v })} required />
            <Field label="Name *" value={projectForm.name} onChange={(v) => setProjectForm({ ...projectForm, name: v })} required className="sm:col-span-2" />
            <Field label="Client" value={projectForm.client} onChange={(v) => setProjectForm({ ...projectForm, client: v })} />
            <div className="sm:col-span-4">
              <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
                {saving ? "Saving..." : "Create project"}
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
                <tr><th className="px-3 py-2">Code</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Client</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Tasks</th></tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className="cursor-pointer border-t border-hair hover:bg-midnight" onClick={() => setFilterProject(p.id === filterProject ? "" : p.id)}>
                    <td className="px-3 py-2 font-mono text-xs text-mist">{p.code}</td>
                    <td className="px-3 py-2 font-medium text-fg">{p.name}</td>
                    <td className="px-3 py-2 text-mist">{p.client || "-"}</td>
                    <td className="px-3 py-2"><StatusBadge status={p.status} /></td>
                    <td className="px-3 py-2 font-mono text-mist">{tasks.filter((t) => t.project_id === p.id).length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div>
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-medium text-fg">Tasks {filterProject && <span className="text-sm font-normal text-mist">(filtered by project - click again or clear to show all)</span>}</h2>
            <p className="text-sm text-mist">blocked_by_po_id renders as a badge; it clears automatically server-side once that PO is received.</p>
          </div>
          <div className="flex gap-2">
            {filterProject && <button onClick={() => setFilterProject("")} className="rounded-lg border border-line px-3 py-2 text-sm text-mist transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-midnight">Clear filter</button>}
            <button onClick={() => setShowTaskForm((s) => !s)} className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">
              {showTaskForm ? "Cancel" : "+ New task"}
            </button>
          </div>
        </div>

        {showTaskForm && (
          <form onSubmit={handleCreateTask} className="mb-6 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4" style={{ boxShadow: "var(--shadow-sm)" }}>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-fg">Project</span>
              <select value={taskForm.project_id} onChange={(e) => setTaskForm({ ...taskForm, project_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
                <option value="" className="bg-panel">-- none --</option>
                {projects.map((p) => <option key={p.id} value={p.id} className="bg-panel">{p.code} - {p.name}</option>)}
              </select>
            </label>
            <Field label="Title *" value={taskForm.title} onChange={(v) => setTaskForm({ ...taskForm, title: v })} required className="sm:col-span-2" />
            <Field label="Due" value={taskForm.due} onChange={(v) => setTaskForm({ ...taskForm, due: v })} type="date" />
            <Field label="Assignee (user id)" value={taskForm.assignee} onChange={(v) => setTaskForm({ ...taskForm, assignee: v })} />
            <label className="block text-sm sm:col-span-2">
              <span className="mb-1 block font-medium text-fg">Blocked by PO</span>
              <select value={taskForm.blocked_by_po_id} onChange={(e) => setTaskForm({ ...taskForm, blocked_by_po_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
                <option value="" className="bg-panel">-- not blocked --</option>
                {pos.map((p) => <option key={p.id} value={p.id} className="bg-panel">{p.po_no} ({p.status})</option>)}
              </select>
            </label>
            <div className="sm:col-span-4">
              <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
                {saving ? "Saving..." : "Create task"}
              </button>
            </div>
          </form>
        )}

        {!loading && (
          <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
            <table className="w-full text-left text-sm">
              <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
                <tr><th className="px-3 py-2">Title</th><th className="px-3 py-2">Project</th><th className="px-3 py-2">Due</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Blocked</th><th className="px-3 py-2"></th></tr>
              </thead>
              <tbody>
                {visibleTasks.length === 0 && (
                  <tr><td colSpan={6} className="px-3 py-4 text-center text-mist">No tasks.</td></tr>
                )}
                {visibleTasks.map((t) => {
                  const project = projects.find((p) => p.id === t.project_id);
                  const blockingPo = t.blocked_by_po_id ? poById.get(t.blocked_by_po_id) : null;
                  return (
                    <tr key={t.id} className="border-t border-hair hover:bg-midnight">
                      <td className="px-3 py-2 font-medium text-fg">{t.title}</td>
                      <td className="px-3 py-2 font-mono text-xs text-mist">{project ? project.code : "-"}</td>
                      <td className="px-3 py-2 font-mono text-xs text-mist">{t.due || "-"}</td>
                      <td className="px-3 py-2"><StatusBadge status={t.status} /></td>
                      <td className="px-3 py-2">
                        {t.blocked_by_po_id ? (
                          <span className="inline-flex items-center gap-1 rounded-md border border-rust px-2 py-0.5 text-xs font-medium text-rust" title={`Blocked until PO ${blockingPo?.po_no ?? t.blocked_by_po_id} reaches 'received'`}>
                            Blocked by {blockingPo?.po_no ?? "PO"}
                          </span>
                        ) : (
                          <span className="rounded-md border border-line px-2 py-0.5 text-xs text-mist">not blocked</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => markDone(t)} className="text-copper hover:underline">
                          {t.status === "done" ? "Reopen" : "Mark done"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "border-copper text-copper", open: "border-line text-mist",
    in_progress: "border-copper text-copper", blocked: "border-rust text-rust",
    done: "border-moss text-moss", cancelled: "border-rust text-rust",
    on_hold: "border-line text-mist", completed: "border-moss text-moss",
  };
  return <span className={`rounded-md border bg-midnight px-2 py-0.5 text-xs font-medium ${colors[status] ?? "border-line text-mist"}`}>{status}</span>;
}

function Field({
  label, value, onChange, className, type = "text", required,
}: { label: string; value: string; onChange: (v: string) => void; className?: string; type?: string; required?: boolean }) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="mb-1 block font-medium text-fg">{label}</span>
      <input type={type} required={required} value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
    </label>
  );
}
