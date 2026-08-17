"use client";

import { useEffect, useState } from "react";
import { createVendor, listVendors, updateVendor, ErpApiError } from "@/lib/erp/api";
import type { Vendor } from "@/lib/erp/types";

const STATE_CODES: Record<string, string> = {
  "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
  "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
  "10": "Bihar", "11": "Sikkim", "18": "Assam", "19": "West Bengal", "21": "Odisha",
  "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "27": "Maharashtra",
  "29": "Karnataka", "30": "Goa", "32": "Kerala", "33": "Tamil Nadu", "36": "Telangana", "37": "Andhra Pradesh",
};

const emptyForm = {
  name: "", gstin: "", address: "", state_code: "", contact: "", phone: "", email: "", category: "", rating: "", notes: "",
};

export default function VendorsPage() {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState(emptyForm);

  function load() {
    setLoading(true);
    listVendors()
      .then(setVendors)
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load vendors"))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await createVendor({
        name: form.name,
        gstin: form.gstin || null,
        address: form.address || null,
        state_code: form.state_code || null,
        contact: form.contact || null,
        phone: form.phone || null,
        email: form.email || null,
        category: form.category || null,
        rating: form.rating ? Number(form.rating) : null,
        notes: form.notes || null,
      });
      setForm(emptyForm);
      setShowForm(false);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create vendor");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(v: Vendor) {
    setEditId(v.id);
    setEditForm({
      name: v.name, gstin: v.gstin ?? "", address: v.address ?? "", state_code: v.state_code ?? "",
      contact: v.contact ?? "", phone: v.phone ?? "", email: v.email ?? "", category: v.category ?? "",
      rating: v.rating != null ? String(v.rating) : "", notes: v.notes ?? "",
    });
  }

  async function saveEdit(id: string) {
    setSaving(true);
    setError(null);
    try {
      await updateVendor(id, {
        name: editForm.name,
        gstin: editForm.gstin || null,
        address: editForm.address || null,
        state_code: editForm.state_code || null,
        contact: editForm.contact || null,
        phone: editForm.phone || null,
        email: editForm.email || null,
        category: editForm.category || null,
        rating: editForm.rating ? Number(editForm.rating) : null,
        notes: editForm.notes || null,
      });
      setEditId(null);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to update vendor");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-light text-fg">Vendors</h1>
          <p className="text-sm text-mist">Master data for PO/GST logic. State code drives CGST+SGST vs IGST.</p>
        </div>
        <button
          onClick={() => setShowForm((s) => !s)}
          className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper"
        >
          {showForm ? "Cancel" : "+ New vendor"}
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-3" style={{ boxShadow: "var(--shadow-sm)" }}>
          <Field label="Name *" value={form.name} onChange={(v) => setForm({ ...form, name: v })} required />
          <Field label="GSTIN" value={form.gstin} onChange={(v) => setForm({ ...form, gstin: v })} />
          <StateSelect value={form.state_code} onChange={(v) => setForm({ ...form, state_code: v })} />
          <Field label="Address" value={form.address} onChange={(v) => setForm({ ...form, address: v })} className="sm:col-span-3" />
          <Field label="Contact person" value={form.contact} onChange={(v) => setForm({ ...form, contact: v })} />
          <Field label="Phone" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} />
          <Field label="Email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} />
          <Field label="Category" value={form.category} onChange={(v) => setForm({ ...form, category: v })} />
          <Field label="Rating (1-5)" value={form.rating} onChange={(v) => setForm({ ...form, rating: v })} type="number" />
          <Field label="Notes" value={form.notes} onChange={(v) => setForm({ ...form, notes: v })} className="sm:col-span-3" />
          <div className="sm:col-span-3">
            <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
              {saving ? "Saving..." : "Create vendor"}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : vendors.length === 0 ? (
        <p className="text-sm text-mist">No vendors yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
              <tr>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">GSTIN</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Contact</th>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2">Rating</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((v) =>
                editId === v.id ? (
                  <tr key={v.id} className="border-t border-hair bg-midnight">
                    <td className="px-3 py-2"><input className="w-full rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-full rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.gstin} onChange={(e) => setEditForm({ ...editForm, gstin: e.target.value })} /></td>
                    <td className="px-3 py-2">
                      <select className="w-full rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.state_code} onChange={(e) => setEditForm({ ...editForm, state_code: e.target.value })}>
                        <option value="" className="bg-panel">--</option>
                        {Object.entries(STATE_CODES).map(([code, name]) => <option key={code} value={code} className="bg-panel">{code} - {name}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2"><input className="w-full rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.contact} onChange={(e) => setEditForm({ ...editForm, contact: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-full rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.category} onChange={(e) => setEditForm({ ...editForm, category: e.target.value })} /></td>
                    <td className="px-3 py-2"><input className="w-16 rounded-lg border border-line bg-transparent px-2 py-1 text-fg focus:border-copper focus:outline-none" value={editForm.rating} onChange={(e) => setEditForm({ ...editForm, rating: e.target.value })} /></td>
                    <td className="space-x-2 px-3 py-2 whitespace-nowrap">
                      <button onClick={() => saveEdit(v.id)} disabled={saving} className="text-copper hover:underline">Save</button>
                      <button onClick={() => setEditId(null)} className="text-mist hover:underline">Cancel</button>
                    </td>
                  </tr>
                ) : (
                  <tr key={v.id} className="border-t border-hair hover:bg-midnight">
                    <td className="px-3 py-2 font-medium text-fg">{v.name}</td>
                    <td className="px-3 py-2 font-mono text-xs text-mist">{v.gstin || "-"}</td>
                    <td className="px-3 py-2 text-mist">{v.state_code ? `${v.state_code} - ${STATE_CODES[v.state_code] ?? ""}` : "-"}</td>
                    <td className="px-3 py-2 text-mist">{v.contact || v.phone || "-"}</td>
                    <td className="px-3 py-2 text-mist">{v.category || "-"}</td>
                    <td className="px-3 py-2 font-mono text-mist">{v.rating ?? "-"}</td>
                    <td className="px-3 py-2 text-right">
                      <button onClick={() => startEdit(v)} className="text-copper hover:underline">Edit</button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Field({
  label, value, onChange, className, type = "text", required,
}: { label: string; value: string; onChange: (v: string) => void; className?: string; type?: string; required?: boolean }) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="mb-1 block font-medium text-fg">{label}</span>
      <input
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none"
      />
    </label>
  );
}

function StateSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-fg">State code (GST)</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
        <option value="" className="bg-panel">-- select --</option>
        {Object.entries(STATE_CODES).map(([code, name]) => (
          <option key={code} value={code} className="bg-panel">{code} - {name}</option>
        ))}
      </select>
    </label>
  );
}
