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

  if (loading) return <p className="text-sm text-mist">Loading...</p>;
  if (error && !invoice) return <p className="rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>;
  if (!invoice) return null;

  const canApprove = invoice.status !== "approved" && invoice.status !== "paid" && match?.ok === true;
  const isApprovedLike = invoice.status === "approved" || invoice.status === "paid";

  return (
    <div>
      <Link href="/invoices" className="mb-4 inline-block text-sm text-copper hover:underline">&larr; Back to invoices</Link>

      <div className="mb-6 rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <div className="flex items-center justify-between">
          <h1 className="font-display text-2xl font-light text-fg">{invoice.inv_no}</h1>
          <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${isApprovedLike ? "border border-moss text-moss" : "border border-line text-mist"}`}>{invoice.status}</span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <div><dt className="text-mist">Date</dt><dd className="font-mono text-fg">{invoice.date || "-"}</dd></div>
          <div><dt className="text-mist">Taxable</dt><dd className="font-mono text-fg">₹{invoice.taxable}</dd></div>
          <div><dt className="text-mist">GST</dt><dd className="font-mono text-fg">₹{invoice.gst}</dd></div>
          <div><dt className="text-mist">Total</dt><dd className="font-mono text-fg">₹{invoice.total}</dd></div>
        </dl>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      <div className="mb-6 rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-fg">3-way match (PO vs GRN vs invoice)</h2>
          <button onClick={handleRecheck} disabled={checking} className="text-sm text-copper hover:underline disabled:opacity-50">
            {checking ? "Checking..." : "Re-check"}
          </button>
        </div>

        {!invoice.po_id && (
          <p className="mb-3 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-rust">
            <span className="font-medium">Mismatch —</span> this invoice is not linked to a PO. The 3-way match cannot pass and approval is blocked.
          </p>
        )}

        {po && (
          <div className="mb-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
            <div><dt className="text-mist">Linked PO</dt><dd className="font-mono text-fg">{po.po_no}</dd></div>
            <div><dt className="text-mist">PO status</dt><dd className="text-fg">{po.status}</dd></div>
          </div>
        )}

        {match && (
          <div className="space-y-3">
            {/* Overall match signal - the single most important call-out on this screen */}
            <div
              className={`flex items-center gap-2 rounded-2xl border px-3 py-2.5 text-sm font-medium ${
                match.ok ? "border-moss text-moss" : "border-rust text-rust"
              }`}
              style={{ boxShadow: "var(--shadow-sm)" }}
            >
              <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${match.ok ? "bg-moss" : "bg-rust"}`} aria-hidden />
              {match.ok ? "Matched — eligible for approval." : `Mismatch: ${match.reason}`}
            </div>

            {/* Per-check comparison — PO/GRN expected vs invoice actual */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {Object.entries(match.checks).map(([name, c]) => {
                const rawExpected = c.po_expected ?? c.grn_accepted_qty ?? "-";
                const invoiceVal = c.invoice;
                const invoiceNum = Number(invoiceVal);
                const expectedNum = Number(rawExpected);
                // Values arrive as raw floats (Decimal-from-Postgres via
                // JSON) with binary-float noise, e.g. 82.4249999999997 -
                // round for display only, never for the match logic
                // itself (that's already decided server-side).
                const fmtNum = (v: unknown) => {
                  if (v === null || v === undefined || v === "") return "-";
                  const n = Number(v);
                  return Number.isFinite(n) ? n.toFixed(3).replace(/\.?0+$/, "") : String(v);
                };
                const expected = fmtNum(rawExpected);
                const canDiff = !c.ok && Number.isFinite(invoiceNum) && Number.isFinite(expectedNum);
                const diff = canDiff ? invoiceNum - expectedNum : null;

                return (
                  <div
                    key={name}
                    className={`rounded-2xl border p-3 ${c.ok ? "border-moss" : "border-rust"}`}
                    style={{ boxShadow: "var(--shadow-sm)" }}
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <span className="font-mono text-xs tracking-[0.1em] text-mist uppercase">{name.replaceAll("_", " ")}</span>
                      <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${c.ok ? "border border-moss text-moss" : "border border-rust text-rust"}`}>
                        {c.ok ? "Matched" : "Mismatch"}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <dt className="text-xs text-mist">Invoice</dt>
                        <dd className="font-mono text-fg">{fmtNum(invoiceVal)}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-mist">PO / GRN expected</dt>
                        <dd className="font-mono text-fg">{expected}</dd>
                      </div>
                    </div>
                    {c.tolerance_pct && (
                      <p className="mt-2 font-mono text-[11px] text-mist">tolerance {c.tolerance_pct}</p>
                    )}
                    {diff !== null && (
                      <p className="mt-2 font-mono text-xs text-rust">
                        differs by {diff > 0 ? "+" : ""}{diff.toFixed(2)}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="mt-4">
          <button
            onClick={handleApprove}
            disabled={!canApprove || approving}
            title={!canApprove && match ? "Cannot approve: 3-way match must pass first (mirrors backend rejection)" : undefined}
            className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:cursor-not-allowed disabled:opacity-40"
          >
            {approving ? "Approving..." : isApprovedLike ? "Already approved" : "Approve invoice"}
          </button>
          {!canApprove && match && !isApprovedLike && (
            <p className="mt-1 text-xs text-mist">Approval is disabled because the 3-way match above has not passed - the backend would reject it with a 400.</p>
          )}
        </div>
      </div>
    </div>
  );
}
