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
          <h1 className="font-display text-2xl font-light text-fg">Vendor Invoices</h1>
          <p className="text-sm text-mist">3-way match against PO + GRN before approval.</p>
        </div>
        <button onClick={() => setShowForm((s) => !s)} className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">
          {showForm ? "Cancel" : "+ Record invoice"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4" style={{ boxShadow: "var(--shadow-sm)" }}>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Vendor *</span>
            <select required value={form.vendor_id} onChange={(e) => setForm({ ...form, vendor_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- select --</option>
              {vendors.map((v) => <option key={v.id} value={v.id} className="bg-panel">{v.name}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Linked PO</span>
            <select value={form.po_id} onChange={(e) => setForm({ ...form, po_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- none (match will fail) --</option>
              {pos.filter((p) => !form.vendor_id || p.vendor_id === form.vendor_id).map((p) => <option key={p.id} value={p.id} className="bg-panel">{p.po_no}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Invoice no. *</span>
            <input required value={form.inv_no} onChange={(e) => setForm({ ...form, inv_no: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Date</span>
            <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Taxable *</span>
            <input required type="number" value={form.taxable} onChange={(e) => setForm({ ...form, taxable: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">GST *</span>
            <input required type="number" value={form.gst} onChange={(e) => setForm({ ...form, gst: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Total *</span>
            <input required type="number" value={form.total} onChange={(e) => setForm({ ...form, total: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <div className="sm:col-span-4">
            <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
              {saving ? "Saving..." : "Record invoice"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : invoices.length === 0 ? (
        <p className="text-sm text-mist">No vendor invoices yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
              <tr><th className="px-3 py-2">Invoice no.</th><th className="px-3 py-2">Vendor</th><th className="px-3 py-2">PO</th><th className="px-3 py-2">Total</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id} className="border-t border-hair hover:bg-midnight">
                  <td className="px-3 py-2"><Link href={`/invoices/${inv.id}`} className="font-medium text-copper hover:underline">{inv.inv_no}</Link></td>
                  <td className="px-3 py-2 text-mist">{vendorById.get(inv.vendor_id)?.name ?? inv.vendor_id}</td>
                  <td className="px-3 py-2 font-mono text-xs text-mist">{inv.po_id ? (poById.get(inv.po_id)?.po_no ?? inv.po_id) : "-"}</td>
                  <td className="px-3 py-2 font-mono text-mist">₹{inv.total}</td>
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
  const styles: Record<string, string> = {
    received: "border border-line text-mist",
    matched: "border border-moss text-moss",
    approved: "border border-moss text-moss",
    paid: "border border-moss text-moss",
  };
  return <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${styles[status] ?? "border border-line text-mist"}`}>{status}</span>;
}
