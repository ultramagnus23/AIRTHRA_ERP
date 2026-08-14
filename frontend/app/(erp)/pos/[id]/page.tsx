"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getPo, getPoPdf, getVendor, issuePo, ErpApiError } from "@/lib/erp/api";
import type { Po, Vendor } from "@/lib/erp/types";

export default function PoDetailPage() {
  const params = useParams<{ id: string }>();
  const [po, setPo] = useState<Po | null>(null);
  const [vendor, setVendor] = useState<Vendor | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);

  function load() {
    setLoading(true);
    getPo(params.id)
      .then((p) => { setPo(p); return getVendor(p.vendor_id); })
      .then(setVendor)
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load PO"))
      .finally(() => setLoading(false));
  }
  useEffect(load, [params.id]);

  async function handleIssue() {
    setError(null);
    try {
      await issuePo(params.id);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to issue PO");
    }
  }

  async function handlePdf() {
    setPdfBusy(true);
    setError(null);
    try {
      const res = await getPoPdf(params.id);
      setPdfUrl(res.url);
      window.open(res.url, "_blank");
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to generate PDF");
    } finally {
      setPdfBusy(false);
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Loading...</p>;
  if (error && !po) return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!po) return null;

  const totals = po.totals;

  return (
    <div>
      <Link href="/pos" className="mb-4 inline-block text-sm text-teal-700 hover:underline">&larr; Back to POs</Link>

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="font-mono text-lg font-semibold text-slate-900">{po.po_no}</h1>
          <div className="flex items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${po.status === "draft" ? "bg-slate-100 text-slate-700" : "bg-blue-100 text-blue-800"}`}>{po.status}</span>
            {po.status === "draft" && (
              <button onClick={handleIssue} className="rounded-md bg-teal-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-800">Issue PO</button>
            )}
            <button onClick={handlePdf} disabled={pdfBusy} className="rounded-md border border-teal-700 px-3 py-1.5 text-sm font-medium text-teal-700 hover:bg-teal-50 disabled:opacity-50">
              {pdfBusy ? "Generating..." : "Download PDF"}
            </button>
          </div>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <div><dt className="text-slate-500">Vendor</dt><dd className="text-slate-800">{vendor?.name ?? po.vendor_id}</dd></div>
          <div><dt className="text-slate-500">Vendor state</dt><dd className="text-slate-800">{vendor?.state_code ?? "-"}</dd></div>
          <div><dt className="text-slate-500">Date</dt><dd className="text-slate-800">{po.po_date}</dd></div>
          <div><dt className="text-slate-500">Freight</dt><dd className="text-slate-800">{po.freight ?? "-"}</dd></div>
        </dl>
        {pdfUrl && (
          <p className="mt-2 text-xs text-slate-500">Last generated PDF: <a href={pdfUrl} target="_blank" rel="noreferrer" className="text-teal-700 hover:underline">{pdfUrl}</a></p>
        )}
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Description</th><th className="px-3 py-2">HSN</th><th className="px-3 py-2">Qty</th>
              <th className="px-3 py-2">Unit</th><th className="px-3 py-2">Rate</th><th className="px-3 py-2">Taxable</th>
              <th className="px-3 py-2">GST%</th><th className="px-3 py-2">CGST</th><th className="px-3 py-2">SGST</th>
              <th className="px-3 py-2">IGST</th><th className="px-3 py-2">Line total</th><th className="px-3 py-2">Received</th>
            </tr>
          </thead>
          <tbody>
            {(po.items ?? []).map((it) => (
              <tr key={it.id} className="border-t border-slate-100">
                <td className="px-3 py-2">{it.description}</td>
                <td className="px-3 py-2 text-slate-600">{it.hsn || "-"}</td>
                <td className="px-3 py-2">{it.qty}</td>
                <td className="px-3 py-2 text-slate-600">{it.unit}</td>
                <td className="px-3 py-2">{it.rate}</td>
                <td className="px-3 py-2">{it.taxable}</td>
                <td className="px-3 py-2">{it.gst_rate}%</td>
                <td className="px-3 py-2">{it.cgst}</td>
                <td className="px-3 py-2">{it.sgst}</td>
                <td className="px-3 py-2">{it.igst}</td>
                <td className="px-3 py-2 font-medium">{it.line_total}</td>
                <td className="px-3 py-2 text-slate-600">{it.received_qty} / {it.qty}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totals && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-900">GST summary ({totals.tax_regime})</h3>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            <div><dt className="text-slate-500">Taxable</dt><dd className="text-slate-800">₹{totals.taxable}</dd></div>
            <div><dt className="text-slate-500">CGST</dt><dd className="text-slate-800">₹{totals.cgst}</dd></div>
            <div><dt className="text-slate-500">SGST</dt><dd className="text-slate-800">₹{totals.sgst}</dd></div>
            <div><dt className="text-slate-500">IGST</dt><dd className="text-slate-800">₹{totals.igst}</dd></div>
            <div><dt className="text-slate-500">Freight</dt><dd className="text-slate-800">₹{totals.freight}</dd></div>
            <div className="sm:col-span-2"><dt className="text-slate-500">Grand total</dt><dd className="text-lg font-semibold text-slate-900">₹{totals.grand_total}</dd></div>
          </dl>
          {po.amount_in_words && <p className="mt-3 text-sm italic text-slate-600">{po.amount_in_words}</p>}
        </div>
      )}
    </div>
  );
}
