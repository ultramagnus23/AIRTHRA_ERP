"use client";

import { useEffect, useState } from "react";
import { approveInvoice, getInvoices, AdminApiError } from "@/lib/admin-api";
import type { Invoice, InvoiceStatus } from "@/lib/admin-types";

const STATUS_STYLES: Record<InvoiceStatus, string> = {
  draft: "bg-amber-100 text-amber-800 border-amber-300",
  approved: "bg-emerald-100 text-emerald-800 border-emerald-300",
  sent: "bg-slate-100 text-slate-700 border-slate-300",
};

const STATUS_FILTERS: (InvoiceStatus | "all")[] = ["all", "draft", "approved", "sent"];

export default function BillingPage() {
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<InvoiceStatus | "all">("draft");
  const [approving, setApproving] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});

  function load() {
    setLoading(true);
    setError(null);
    getInvoices(statusFilter === "all" ? undefined : { status: statusFilter })
      .then((res) => setInvoices(res.invoices))
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load invoices"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  async function handleApprove(invoiceId: string) {
    setApproving(invoiceId);
    setRowError((prev) => ({ ...prev, [invoiceId]: "" }));
    try {
      const updated = await approveInvoice(invoiceId);
      setInvoices((prev) =>
        prev
          ? prev.map((inv) => (inv.invoice_id === invoiceId ? { ...inv, status: updated.status } : inv))
          : prev,
      );
    } catch (e) {
      setRowError((prev) => ({
        ...prev,
        [invoiceId]: e instanceof AdminApiError ? e.message : "approve failed",
      }));
    } finally {
      setApproving(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Billing inbox</h1>
        <p className="text-sm text-slate-600">
          GET /admin/invoices + POST /admin/invoices/{"{id}"}/approve. Draft → approved is the
          only transition wired here (approved → sent/dispatch is explicitly out of scope in
          P7&apos;s backend).
        </p>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="text-slate-600">Status:</span>
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium ${
              statusFilter === s ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-slate-500">Loading...</p>}
      {error && <p className="text-sm text-red-700">{error}</p>}

      {invoices && (
        <div className="overflow-x-auto rounded-md border border-slate-200 bg-white">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Plant</th>
                <th className="px-4 py-2">Period</th>
                <th className="px-4 py-2">Amount</th>
                <th className="px-4 py-2">SO2 (kg)</th>
                <th className="px-4 py-2">Uptime %</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">PDF</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.invoice_id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2 font-mono text-xs text-slate-700">{inv.plant_id}</td>
                  <td className="px-4 py-2">{inv.period}</td>
                  <td className="px-4 py-2">{inv.amount ?? "-"}</td>
                  <td className="px-4 py-2">{inv.so2_kg ?? "-"}</td>
                  <td className="px-4 py-2">{inv.uptime_pct ?? "-"}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${STATUS_STYLES[inv.status]}`}
                    >
                      {inv.status}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    {inv.pdf_url ? (
                      <a
                        href={inv.pdf_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-xs font-medium text-amber-700 underline hover:text-amber-800"
                      >
                        Download
                      </a>
                    ) : (
                      <span className="text-xs text-slate-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {inv.status === "draft" ? (
                      <button
                        onClick={() => handleApprove(inv.invoice_id)}
                        disabled={approving === inv.invoice_id}
                        className="rounded-md bg-amber-500 px-3 py-1 text-xs font-semibold text-slate-900 hover:bg-amber-400 disabled:opacity-50"
                      >
                        {approving === inv.invoice_id ? "Approving..." : "Approve"}
                      </button>
                    ) : null}
                    {rowError[inv.invoice_id] && (
                      <div className="mt-1 text-xs text-red-700">{rowError[inv.invoice_id]}</div>
                    )}
                  </td>
                </tr>
              ))}
              {invoices.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-slate-500">
                    No invoices for this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
