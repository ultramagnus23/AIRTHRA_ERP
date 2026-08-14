"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createInvoice, listInvoices, listPos, listVendors, ErpApiError } from "@/lib/erp/api";
import type { Po, Vendor, VendorInvoice } from "@/lib/erp/types";

const emptyForm = { vendor_id: "", po_id: "", inv_no: "", date: "", taxable: "", gst: "", total: "" };

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<VendorInvoice[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [pos, setPos] = useState<Po[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  function load() {
    setLoading(true);
    Promise.all([listInvoices(), listVendors(), listPos()])
      .then(([i, v, p]) => { setInvoices(i); setVendors(v); setPos(p); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createInvoice({
        vendor_id: form.vendor_id, po_id: form.po_id || null, inv_no: form.inv_no, date: form.date || null,
        taxable: Number(form.taxable), gst: Number(form.gst), total: Number(form.total),
      });
      setForm(emptyForm);
      setShowForm(false);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create invoice");
    } finally {
      setSaving(false);
    }
  }

  const vendorById = new Map(vendors.map((v) => [v.id, v]));
  const poById = new Map(pos.map((p) => [p.id, p]));

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Vendor Invoices</h1>
          <p className="text-sm text-slate-500">3-way match against PO + GRN before approval.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
          {showForm ? "Cancel" : "+ Record invoice"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Vendor *</span>
            <select required value={form.vendor_id} onChange={(e) => setForm({ ...form, vendor_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- select --</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Linked PO</span>
            <select value={form.po_id} onChange={(e) => setForm({ ...form, po_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- none (match will fail) --</option>
              {pos.filter((p) => !form.vendor_id || p.vendor_id === form.vendor_id).map((p) => <option key={p.id} value={p.id}>{p.po_no}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Invoice no. *</span>
            <input required value={form.inv_no} onChange={(e) => setForm({ ...form, inv_no: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Date</span>
            <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Taxable *</span>
            <input required type="number" value={form.taxable} onChange={(e) => setForm({ ...form, taxable: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">GST *</span>
            <input required type="number" value={form.gst} onChange={(e) => setForm({ ...form, gst: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Total *</span>
            <input required type="number" value={form.total} onChange={(e) => setForm({ ...form, total: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving..." : "Record invoice"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : invoices.length === 0 ? (
        <p className="text-sm text-slate-500">No vendor invoices yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2">Invoice no.</th><th className="px-3 py-2">Vendor</th><th className="px-3 py-2">PO</th><th className="px-3 py-2">Total</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2"><Link href={`/invoices/${inv.id}`} className="font-medium text-teal-700 hover:underline">{inv.inv_no}</Link></td>
                  <td className="px-3 py-2 text-slate-600">{vendorById.get(inv.vendor_id)?.name ?? inv.vendor_id}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-600">{inv.po_id ? (poById.get(inv.po_id)?.po_no ?? inv.po_id) : "-"}</td>
                  <td className="px-3 py-2 text-slate-600">₹{inv.total}</td>
                  <td className="px-3 py-2"><StatusBadge status={inv.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    received: "bg-slate-100 text-slate-700", matched: "bg-blue-100 text-blue-800",
    approved: "bg-green-100 text-green-800", paid: "bg-teal-100 text-teal-800",
  };
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? "bg-slate-100"}`}>{status}</span>;
}
