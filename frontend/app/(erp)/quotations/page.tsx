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
          <h1 className="text-lg font-semibold text-slate-900">Quotations</h1>
          <p className="text-sm text-slate-500">Vendor (inbound) or customer (outbound) quotes, linked to a project.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
          {showForm ? "Cancel" : "+ New quotation"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Direction</span>
            <select value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value as "vendor" | "customer" })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="vendor">Vendor (inbound quote from a vendor)</option>
              <option value="customer">Customer (outbound quote to a customer)</option>
            </select>
          </label>
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-slate-700">
              Party ID {form.direction === "vendor" ? "(vendor UUID)" : "(no customers table in this schema - free text id)"}
            </span>
            <input required value={form.party_id} onChange={(e) => setForm({ ...form, party_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-mono" placeholder="paste vendor id from /vendors, or any identifier" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Project</span>
            <select value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- none --</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}
            </select>
          </label>
          <Field label="Ref no." value={form.ref_no} onChange={(v) => setForm({ ...form, ref_no: v })} />
          <Field label="Date" value={form.date} onChange={(v) => setForm({ ...form, date: v })} type="date" />
          <Field label="Valid till" value={form.valid_till} onChange={(v) => setForm({ ...form, valid_till: v })} type="date" />
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving..." : "Create quotation"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : quotations.length === 0 ? (
        <p className="text-sm text-slate-500">No quotations yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2">Ref no.</th><th className="px-3 py-2">Direction</th><th className="px-3 py-2">Project</th><th className="px-3 py-2">Date</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {quotations.map((q) => (
                <tr key={q.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2"><Link href={`/quotations/${q.id}`} className="font-medium text-teal-700 hover:underline">{q.ref_no || q.id.slice(0, 8)}</Link></td>
                  <td className="px-3 py-2 text-slate-600 capitalize">{q.direction}</td>
                  <td className="px-3 py-2 text-slate-600">{q.project_id ? (projectByCode.get(q.project_id)?.code ?? "-") : "-"}</td>
                  <td className="px-3 py-2 text-slate-600">{q.date || "-"}</td>
                  <td className="px-3 py-2 text-slate-600">{q.status}</td>
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
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-teal-500 focus:outline-none" />
    </label>
  );
}
