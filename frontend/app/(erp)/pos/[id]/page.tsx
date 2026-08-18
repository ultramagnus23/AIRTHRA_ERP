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
      setLoading(true);
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

  if (loading) return <p className="text-sm text-mist">Loading...</p>;
  if (error && !po) return <p className="rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>;
  if (!po) return null;

  const totals = po.totals;

  return (
    <div>
      <Link href="/pos" className="mb-4 inline-block text-sm text-copper hover:underline">&larr; Back to POs</Link>

      <div className="mb-6 rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="font-mono text-lg font-semibold text-fg">{po.po_no}</h1>
          <div className="flex items-center gap-2">
            <StatusBadge status={po.status} />
            {po.status === "draft" && (
              <button onClick={handleIssue} className="rounded-lg bg-rust px-3 py-1.5 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">Issue PO</button>
            )}
            <button onClick={handlePdf} disabled={pdfBusy} className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:border-copper disabled:opacity-50">
              {pdfBusy ? "Generating..." : "Download PDF"}
            </button>
          </div>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <div><dt className="text-mist">Vendor</dt><dd className="text-fg">{vendor?.name ?? po.vendor_id}</dd></div>
          <div><dt className="text-mist">Vendor state</dt><dd className="font-mono text-fg">{vendor?.state_code ?? "-"}</dd></div>
          <div><dt className="text-mist">Date</dt><dd className="font-mono text-fg">{po.po_date}</dd></div>
          <div><dt className="text-mist">Freight</dt><dd className="font-mono text-fg">{po.freight ?? "-"}</dd></div>
        </dl>
        {pdfUrl && (
          <p className="mt-2 text-xs text-mist">Last generated PDF: <a href={pdfUrl} target="_blank" rel="noreferrer" className="text-copper hover:underline">{pdfUrl}</a></p>
        )}
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      <div className="mb-4 overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
        <table className="w-full text-left text-sm">
          <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
            <tr>
              <th className="px-3 py-2">Description</th><th className="px-3 py-2">HSN</th><th className="px-3 py-2">Qty</th>
              <th className="px-3 py-2">Unit</th><th className="px-3 py-2">Rate</th><th className="px-3 py-2">Taxable</th>
              <th className="px-3 py-2">GST%</th><th className="px-3 py-2">CGST</th><th className="px-3 py-2">SGST</th>
              <th className="px-3 py-2">IGST</th><th className="px-3 py-2">Line total</th><th className="px-3 py-2">Received</th>
            </tr>
          </thead>
          <tbody>
            {(po.items ?? []).map((it) => (
              <tr key={it.id} className="border-t border-hair hover:bg-midnight">
                <td className="px-3 py-2 text-fg">{it.description}</td>
                <td className="px-3 py-2 font-mono text-mist">{it.hsn || "-"}</td>
                <td className="px-3 py-2 font-mono text-fg">{it.qty}</td>
                <td className="px-3 py-2 text-mist">{it.unit}</td>
                <td className="px-3 py-2 font-mono text-fg">{it.rate}</td>
                <td className="px-3 py-2 font-mono text-fg">{it.taxable}</td>
                <td className="px-3 py-2 font-mono text-fg">{it.gst_rate}%</td>
                <td className="px-3 py-2 font-mono text-fg">{it.cgst}</td>
                <td className="px-3 py-2 font-mono text-fg">{it.sgst}</td>
                <td className="px-3 py-2 font-mono text-fg">{it.igst}</td>
                <td className="px-3 py-2 font-mono font-medium text-fg">{it.line_total}</td>
                <td className="px-3 py-2 font-mono text-mist">{it.received_qty} / {it.qty}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totals && (
        <div
          className="relative overflow-hidden rounded-2xl border border-hair bg-panel p-4"
          style={{ boxShadow: "var(--shadow-sm)" }}
        >
          <div
            className="absolute inset-x-0 top-0 h-[2px]"
            style={{ background: "oklch(0.72 0.15 54 / 0.55)" }}
            aria-hidden
          />
          <span className="flex items-center gap-1.5 font-mono text-xs tracking-[0.08em] text-mist uppercase">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-copper" aria-hidden />
            GST summary ({totals.tax_regime})
          </span>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <div><dt className="text-xs text-mist">Taxable</dt><dd className="font-mono text-fg">₹{totals.taxable}</dd></div>
            <div><dt className="text-xs text-mist">CGST</dt><dd className="font-mono text-fg">₹{totals.cgst}</dd></div>
            <div><dt className="text-xs text-mist">SGST</dt><dd className="font-mono text-fg">₹{totals.sgst}</dd></div>
            <div><dt className="text-xs text-mist">IGST</dt><dd className="font-mono text-fg">₹{totals.igst}</dd></div>
            <div><dt className="text-xs text-mist">Freight</dt><dd className="font-mono text-fg">₹{totals.freight}</dd></div>
            <div className="sm:col-span-2"><dt className="text-xs text-mist">Grand total</dt><dd className="font-mono text-lg font-medium text-copper">₹{totals.grand_total}</dd></div>
          </dl>
          {po.amount_in_words && <p className="mt-3 text-sm italic text-mist">{po.amount_in_words}</p>}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    draft: "bg-midnight text-mist",
    issued: "bg-copper/15 text-copper",
    partial: "bg-copper/15 text-copper",
    received: "bg-moss/15 text-moss",
    closed: "bg-midnight text-mist",
    cancelled: "bg-rust/15 text-rust",
  };
  return (
    <span className={`rounded-md px-2 py-0.5 font-mono text-xs uppercase tracking-[0.05em] ${styles[status] ?? "bg-midnight text-mist"}`}>
      {status}
    </span>
  );
}
