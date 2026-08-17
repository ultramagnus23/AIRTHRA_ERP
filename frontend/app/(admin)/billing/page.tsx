"use client";

import { useEffect, useState } from "react";
import { approveInvoice, getInvoices, AdminApiError } from "@/lib/admin-api";
import type { Invoice, InvoiceStatus } from "@/lib/admin-types";

// draft = pending/warning (copper), approved = success (moss),
// sent = neutral final state (mist/line) - matches DESIGN.md's semantic
// status-badge coding.
const STATUS_STYLES: Record<InvoiceStatus, string> = {
  draft: "border-copper/40 bg-copper/10 text-copper",
  approved: "border-moss/40 bg-moss/10 text-moss",
  sent: "border-line bg-midnight text-mist",
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
        <h1 className="font-display text-2xl font-light text-fg">Billing inbox</h1>
        <p className="text-sm text-mist">
          GET /admin/invoices + POST /admin/invoices/{"{id}"}/approve. Draft → approved is the
          only transition wired here (approved → sent/dispatch is explicitly out of scope in
          P7&apos;s backend).
        </p>
      </div>

      <div className="flex items-center gap-2 text-sm">
        <span className="font-mono text-xs tracking-[0.1em] text-mist uppercase">Status:</span>
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
              statusFilter === s ? "bg-rust text-fg" : "bg-midnight text-mist hover:text-fg"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {loading && <p className="font-mono text-sm text-mist">Loading...</p>}
      {error && <p className="text-sm text-rust">{error}</p>}

      {invoices && (
        <div
          className="overflow-x-auto rounded-2xl border border-hair bg-panel"
          style={{ boxShadow: "var(--shadow-sm)" }}
        >
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
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
                <tr key={inv.invoice_id} className="border-b border-hair last:border-0">
                  <td className="px-4 py-2 font-mono text-xs text-fg">{inv.plant_id}</td>
                  <td className="px-4 py-2 font-mono text-fg">{inv.period}</td>
                  <td className="px-4 py-2 font-mono text-fg">{inv.amount ?? "-"}</td>
                  <td className="px-4 py-2 font-mono text-fg">{inv.so2_kg ?? "-"}</td>
                  <td className="px-4 py-2 font-mono text-fg">{inv.uptime_pct ?? "-"}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-flex items-center rounded-md border px-2.5 py-0.5 font-mono text-xs font-medium ${STATUS_STYLES[inv.status]}`}
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
                        className="text-xs font-medium text-copper underline hover:text-fg"
                      >
                        Download
                      </a>
                    ) : (
                      <span className="text-xs text-mist">-</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {inv.status === "draft" ? (
                      <button
                        onClick={() => handleApprove(inv.invoice_id)}
                        disabled={approving === inv.invoice_id}
                        className="rounded-lg bg-rust px-3 py-1 text-xs font-semibold text-fg transition-colors duration-150 hover:bg-copper disabled:opacity-50"
                      >
                        {approving === inv.invoice_id ? "Approving..." : "Approve"}
                      </button>
                    ) : null}
                    {rowError[inv.invoice_id] && (
                      <div className="mt-1 text-xs text-rust">{rowError[inv.invoice_id]}</div>
                    )}
                  </td>
                </tr>
              ))}
              {invoices.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-mist">
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
