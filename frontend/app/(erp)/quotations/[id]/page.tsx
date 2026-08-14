"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { addQuotationLine, deleteQuotationLine, getQuotation, ErpApiError } from "@/lib/erp/api";
import type { Quotation } from "@/lib/erp/types";

const emptyLine = { description: "", qty: "1", unit: "nos", rate: "0" };

export default function QuotationDetailPage() {
  const params = useParams<{ id: string }>();
  const [quotation, setQuotation] = useState<Quotation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lineForm, setLineForm] = useState(emptyLine);
  const [saving, setSaving] = useState(false);

  function load() {
    setLoading(true);
    getQuotation(params.id)
      .then(setQuotation)
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load quotation"))
      .finally(() => setLoading(false));
  }
  useEffect(load, [params.id]);

  async function handleAddLine(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await addQuotationLine(params.id, {
        description: lineForm.description, qty: Number(lineForm.qty), unit: lineForm.unit, rate: Number(lineForm.rate),
      });
      setLineForm(emptyLine);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to add line");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteLine(lineId: string) {
    setError(null);
    try {
      await deleteQuotationLine(params.id, lineId);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to delete line");
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Loading...</p>;
  if (error && !quotation) return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!quotation) return null;

  const total = (quotation.lines ?? []).reduce((sum, l) => sum + l.qty * l.rate, 0);

  return (
    <div>
      <Link href="/quotations" className="mb-4 inline-block text-sm text-teal-700 hover:underline">&larr; Back to quotations</Link>
      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold text-slate-900">{quotation.ref_no || quotation.id}</h1>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{quotation.status}</span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <div><dt className="text-slate-500">Direction</dt><dd className="capitalize text-slate-800">{quotation.direction}</dd></div>
          <div><dt className="text-slate-500">Party</dt><dd className="font-mono text-xs text-slate-800">{quotation.party_id}</dd></div>
          <div><dt className="text-slate-500">Date</dt><dd className="text-slate-800">{quotation.date || "-"}</dd></div>
          <div><dt className="text-slate-500">Valid till</dt><dd className="text-slate-800">{quotation.valid_till || "-"}</dd></div>
        </dl>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <h2 className="mb-2 text-sm font-semibold text-slate-900">Line items</h2>
      <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr><th className="px-3 py-2">Description</th><th className="px-3 py-2">Qty</th><th className="px-3 py-2">Unit</th><th className="px-3 py-2">Rate</th><th className="px-3 py-2">Amount</th><th className="px-3 py-2"></th></tr>
          </thead>
          <tbody>
            {(quotation.lines ?? []).map((l) => (
              <tr key={l.id} className="border-t border-slate-100">
                <td className="px-3 py-2">{l.description}</td>
                <td className="px-3 py-2">{l.qty}</td>
                <td className="px-3 py-2">{l.unit}</td>
                <td className="px-3 py-2">{l.rate}</td>
                <td className="px-3 py-2">{(l.qty * l.rate).toFixed(2)}</td>
                <td className="px-3 py-2 text-right"><button onClick={() => handleDeleteLine(l.id)} className="text-red-600 hover:underline">Remove</button></td>
              </tr>
            ))}
            {(quotation.lines ?? []).length === 0 && <tr><td colSpan={6} className="px-3 py-4 text-center text-slate-400">No lines yet.</td></tr>}
          </tbody>
          {(quotation.lines ?? []).length > 0 && (
            <tfoot>
              <tr className="border-t border-slate-200 font-semibold">
                <td colSpan={4} className="px-3 py-2 text-right">Total</td>
                <td className="px-3 py-2">{total.toFixed(2)}</td>
                <td></td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <form onSubmit={handleAddLine} className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-5">
        <label className="block text-sm sm:col-span-2">
          <span className="mb-1 block font-medium text-slate-700">Description *</span>
          <input required value={lineForm.description} onChange={(e) => setLineForm({ ...lineForm, description: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Qty</span>
          <input type="number" value={lineForm.qty} onChange={(e) => setLineForm({ ...lineForm, qty: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Unit</span>
          <input value={lineForm.unit} onChange={(e) => setLineForm({ ...lineForm, unit: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Rate</span>
          <input type="number" value={lineForm.rate} onChange={(e) => setLineForm({ ...lineForm, rate: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
        </label>
        <div className="sm:col-span-5">
          <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            {saving ? "Adding..." : "Add line"}
          </button>
        </div>
      </form>
    </div>
  );
}
