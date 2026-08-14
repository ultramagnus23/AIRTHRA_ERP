"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { approveInvoice, checkThreeWayMatch, getInvoice, getPo, ErpApiError } from "@/lib/erp/api";
import type { MatchResult, Po, VendorInvoice } from "@/lib/erp/types";

export default function InvoiceDetailPage() {
  const params = useParams<{ id: string }>();
  const [invoice, setInvoice] = useState<VendorInvoice | null>(null);
  const [po, setPo] = useState<Po | null>(null);
  const [match, setMatch] = useState<MatchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    getInvoice(params.id)
      .then(async (inv) => {
        setInvoice(inv);
        if (inv.po_id) setPo(await getPo(inv.po_id));
        return checkThreeWayMatch(params.id);
      })
      .then(setMatch)
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load invoice"))
      .finally(() => setLoading(false));
  }
  useEffect(load, [params.id]);

  async function handleRecheck() {
    setChecking(true);
    setError(null);
    try {
      setMatch(await checkThreeWayMatch(params.id));
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to check match");
    } finally {
      setChecking(false);
    }
  }

  async function handleApprove() {
    setApproving(true);
    setError(null);
    try {
      const inv = await approveInvoice(params.id);
      setInvoice(inv);
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to approve invoice");
    } finally {
      setApproving(false);
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Loading...</p>;
  if (error && !invoice) return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!invoice) return null;

  const canApprove = invoice.status !== "approved" && invoice.status !== "paid" && match?.ok === true;

  return (
    <div>
      <Link href="/invoices" className="mb-4 inline-block text-sm text-teal-700 hover:underline">&larr; Back to invoices</Link>

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold text-slate-900">{invoice.inv_no}</h1>
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${invoice.status === "approved" || invoice.status === "paid" ? "bg-green-100 text-green-800" : "bg-slate-100 text-slate-700"}`}>{invoice.status}</span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <div><dt className="text-slate-500">Date</dt><dd className="text-slate-800">{invoice.date || "-"}</dd></div>
          <div><dt className="text-slate-500">Taxable</dt><dd className="text-slate-800">₹{invoice.taxable}</dd></div>
          <div><dt className="text-slate-500">GST</dt><dd className="text-slate-800">₹{invoice.gst}</dd></div>
          <div><dt className="text-slate-500">Total</dt><dd className="text-slate-800">₹{invoice.total}</dd></div>
        </dl>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">3-way match (PO vs GRN vs invoice)</h2>
          <button onClick={handleRecheck} disabled={checking} className="text-sm text-teal-700 hover:underline disabled:opacity-50">
            {checking ? "Checking..." : "Re-check"}
          </button>
        </div>

        {!invoice.po_id && (
          <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">This invoice is not linked to a PO - 3-way match cannot pass.</p>
        )}

        {po && (
          <div className="mb-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
            <div><dt className="text-slate-500">Linked PO</dt><dd className="font-mono text-slate-800">{po.po_no}</dd></div>
            <div><dt className="text-slate-500">PO status</dt><dd className="text-slate-800">{po.status}</dd></div>
          </div>
        )}

        {match && (
          <div className="space-y-2">
            <p className={`rounded-md px-3 py-2 text-sm font-medium ${match.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
              {match.ok ? "Match OK - eligible for approval." : `Match failed: ${match.reason}`}
            </p>
            <div className="overflow-x-auto rounded-md border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr><th className="px-3 py-2">Check</th><th className="px-3 py-2">Invoice value</th><th className="px-3 py-2">PO expected / ordered</th><th className="px-3 py-2">Result</th></tr>
                </thead>
                <tbody>
                  {Object.entries(match.checks).map(([name, c]) => (
                    <tr key={name} className="border-t border-slate-100">
                      <td className="px-3 py-2 capitalize">{name.replaceAll("_", " ")}</td>
                      <td className="px-3 py-2">{c.invoice ?? c.grn_accepted_qty}</td>
                      <td className="px-3 py-2">{c.po_expected ?? c.ordered_qty}</td>
                      <td className="px-3 py-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${c.ok ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>{c.ok ? "OK" : "FAIL"}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="mt-4">
          <button
            onClick={handleApprove}
            disabled={!canApprove || approving}
            title={!canApprove && match ? "Cannot approve: 3-way match must pass first (mirrors backend rejection)" : undefined}
            className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {approving ? "Approving..." : invoice.status === "approved" || invoice.status === "paid" ? "Already approved" : "Approve invoice"}
          </button>
          {!canApprove && match && invoice.status !== "approved" && invoice.status !== "paid" && (
            <p className="mt-1 text-xs text-slate-500">Approval is disabled because the 3-way match above has not passed - the backend would reject it with a 400.</p>
          )}
        </div>
      </div>
    </div>
  );
}
