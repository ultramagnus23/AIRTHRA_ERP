"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createQuotation, listProjects, listQuotations, ErpApiError } from "@/lib/erp/api";
import type { Project, Quotation } from "@/lib/erp/types";

const emptyForm = { direction: "vendor" as "vendor" | "customer", party_id: "", project_id: "", ref_no: "", date: "", valid_till: "" };

export default function QuotationsPage() {
  const [quotations, setQuotations] = useState<Quotation[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  function load() {
    setLoading(true);
    Promise.all([listQuotations(), listProjects()])
      .then(([q, p]) => { setQuotations(q); setProjects(p); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createQuotation({
        direction: form.direction,
        party_id: form.party_id,
        project_id: form.project_id || null,
        ref_no: form.ref_no || null,
        date: form.date || null,
        valid_till: form.valid_till || null,
      });
      setForm(emptyForm);
      setShowForm(false);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create quotation");
    } finally {
      setSaving(false);
    }
  }

  const projectByCode = new Map(projects.map((p) => [p.id, p]));

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-light text-fg">Quotations</h1>
          <p className="text-sm text-mist">Vendor (inbound) or customer (outbound) quotes, linked to a project.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">
          {showForm ? "Cancel" : "+ New quotation"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4" style={{ boxShadow: "var(--shadow-sm)" }}>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Direction</span>
            <select value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value as "vendor" | "customer" })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="vendor" className="bg-panel">Vendor (inbound quote from a vendor)</option>
              <option value="customer" className="bg-panel">Customer (outbound quote to a customer)</option>
            </select>
          </label>
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-fg">
              Party ID {form.direction === "vendor" ? "(vendor UUID)" : "(no customers table in this schema - free text id)"}
            </span>
            <input required value={form.party_id} onChange={(e) => setForm({ ...form, party_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm font-mono text-fg placeholder:text-mist focus:border-copper focus:outline-none" placeholder="paste vendor id from /vendors, or any identifier" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Project</span>
            <select value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- none --</option>
              {projects.map((p) => <option key={p.id} value={p.id} className="bg-panel">{p.code} - {p.name}</option>)}
            </select>
          </label>
          <Field label="Ref no." value={form.ref_no} onChange={(v) => setForm({ ...form, ref_no: v })} />
          <Field label="Date" value={form.date} onChange={(v) => setForm({ ...form, date: v })} type="date" />
          <Field label="Valid till" value={form.valid_till} onChange={(v) => setForm({ ...form, valid_till: v })} type="date" />
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
              {saving ? "Saving..." : "Create quotation"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : quotations.length === 0 ? (
        <p className="text-sm text-mist">No quotations yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
              <tr><th className="px-3 py-2">Ref no.</th><th className="px-3 py-2">Direction</th><th className="px-3 py-2">Project</th><th className="px-3 py-2">Date</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {quotations.map((q) => (
                <tr key={q.id} className="border-t border-hair hover:bg-midnight">
                  <td className="px-3 py-2"><Link href={`/quotations/${q.id}`} className="font-medium text-copper hover:underline">{q.ref_no || q.id.slice(0, 8)}</Link></td>
                  <td className="px-3 py-2 text-mist capitalize">{q.direction}</td>
                  <td className="px-3 py-2 font-mono text-xs text-mist">{q.project_id ? (projectByCode.get(q.project_id)?.code ?? "-") : "-"}</td>
                  <td className="px-3 py-2 font-mono text-xs text-mist">{q.date || "-"}</td>
                  <td className="px-3 py-2 text-mist">{q.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Field({
  label, value, onChange, className, type = "text",
}: { label: string; value: string; onChange: (v: string) => void; className?: string; type?: string }) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="mb-1 block font-medium text-fg">{label}</span>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
    </label>
  );
}
