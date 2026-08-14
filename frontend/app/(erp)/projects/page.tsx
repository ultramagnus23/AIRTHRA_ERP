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
    setLoading(true);
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
            <h1 className="text-lg font-semibold text-slate-900">Projects</h1>
            <p className="text-sm text-slate-500">Parent of drawings/BOMs/tasks.</p>
          </div>
          <button onClick={() => setShowProjectForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
            {showProjectForm ? "Cancel" : "+ New project"}
          </button>
        </div>

        {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        {showProjectForm && (
          <form onSubmit={handleCreateProject} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
            <Field label="Code *" value={projectForm.code} onChange={(v) => setProjectForm({ ...projectForm, code: v })} required />
            <Field label="Name *" value={projectForm.name} onChange={(v) => setProjectForm({ ...projectForm, name: v })} required className="sm:col-span-2" />
            <Field label="Client" value={projectForm.client} onChange={(v) => setProjectForm({ ...projectForm, client: v })} />
            <div className="sm:col-span-4">
              <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
                {saving ? "Saving..." : "Create project"}
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
                <tr><th className="px-3 py-2">Code</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Client</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Tasks</th></tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setFilterProject(p.id === filterProject ? "" : p.id)}>
                    <td className="px-3 py-2 font-mono text-xs text-slate-700">{p.code}</td>
                    <td className="px-3 py-2 font-medium text-slate-900">{p.name}</td>
                    <td className="px-3 py-2 text-slate-600">{p.client || "-"}</td>
                    <td className="px-3 py-2"><StatusBadge status={p.status} /></td>
                    <td className="px-3 py-2 text-slate-600">{tasks.filter((t) => t.project_id === p.id).length}</td>
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
            <h2 className="text-lg font-semibold text-slate-900">Tasks {filterProject && <span className="text-sm font-normal text-slate-500">(filtered by project - click again or clear to show all)</span>}</h2>
            <p className="text-sm text-slate-500">blocked_by_po_id renders as a badge; it clears automatically server-side once that PO is received.</p>
          </div>
          <div className="flex gap-2">
            {filterProject && <button onClick={() => setFilterProject("")} className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">Clear filter</button>}
            <button onClick={() => setShowTaskForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
              {showTaskForm ? "Cancel" : "+ New task"}
            </button>
          </div>
        </div>

        {showTaskForm && (
          <form onSubmit={handleCreateTask} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Project</span>
              <select value={taskForm.project_id} onChange={(e) => setTaskForm({ ...taskForm, project_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
                <option value="">-- none --</option>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}
              </select>
            </label>
            <Field label="Title *" value={taskForm.title} onChange={(v) => setTaskForm({ ...taskForm, title: v })} required className="sm:col-span-2" />
            <Field label="Due" value={taskForm.due} onChange={(v) => setTaskForm({ ...taskForm, due: v })} type="date" />
            <Field label="Assignee (user id)" value={taskForm.assignee} onChange={(v) => setTaskForm({ ...taskForm, assignee: v })} />
            <label className="block text-sm sm:col-span-2">
              <span className="mb-1 block font-medium text-slate-700">Blocked by PO</span>
              <select value={taskForm.blocked_by_po_id} onChange={(e) => setTaskForm({ ...taskForm, blocked_by_po_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
                <option value="">-- not blocked --</option>
                {pos.map((p) => <option key={p.id} value={p.id}>{p.po_no} ({p.status})</option>)}
              </select>
            </label>
            <div className="sm:col-span-4">
              <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
                {saving ? "Saving..." : "Create task"}
              </button>
            </div>
          </form>
        )}

        {!loading && (
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr><th className="px-3 py-2">Title</th><th className="px-3 py-2">Project</th><th className="px-3 py-2">Due</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Blocked</th><th className="px-3 py-2"></th></tr>
              </thead>
              <tbody>
                {visibleTasks.length === 0 && (
                  <tr><td colSpan={6} className="px-3 py-4 text-center text-slate-400">No tasks.</td></tr>
                )}
                {visibleTasks.map((t) => {
                  const project = projects.find((p) => p.id === t.project_id);
                  const blockingPo = t.blocked_by_po_id ? poById.get(t.blocked_by_po_id) : null;
                  return (
                    <tr key={t.id} className="border-t border-slate-100 hover:bg-slate-50">
                      <td className="px-3 py-2 font-medium text-slate-900">{t.title}</td>
                      <td className="px-3 py-2 text-slate-600">{project ? project.code : "-"}</td>
                      <td className="px-3 py-2 text-slate-600">{t.due || "-"}</td>
                      <td className="px-3 py-2"><StatusBadge status={t.status} /></td>
                      <td className="px-3 py-2">
                        {t.blocked_by_po_id ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800" title={`Blocked until PO ${blockingPo?.po_no ?? t.blocked_by_po_id} reaches 'received'`}>
                            Blocked by {blockingPo?.po_no ?? "PO"}
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">not blocked</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => markDone(t)} className="text-teal-700 hover:underline">
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
    active: "bg-teal-100 text-teal-800", open: "bg-slate-100 text-slate-700",
    in_progress: "bg-blue-100 text-blue-800", blocked: "bg-amber-100 text-amber-800",
    done: "bg-green-100 text-green-800", cancelled: "bg-red-100 text-red-800",
    on_hold: "bg-amber-100 text-amber-800", completed: "bg-green-100 text-green-800",
  };
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? "bg-slate-100 text-slate-700"}`}>{status}</span>;
}

function Field({
  label, value, onChange, className, type = "text", required,
}: { label: string; value: string; onChange: (v: string) => void; className?: string; type?: string; required?: boolean }) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input type={type} required={required} value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-teal-500 focus:outline-none" />
    </label>
  );
}
