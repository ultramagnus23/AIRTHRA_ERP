"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listPos, listVendors, ErpApiError } from "@/lib/erp/api";
import type { Po, Vendor } from "@/lib/erp/types";

export default function PosPage() {
  const [pos, setPos] = useState<Po[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listPos(), listVendors()])
      .then(([p, v]) => { setPos(p); setVendors(v); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }, []);

  const vendorById = new Map(vendors.map((v) => [v.id, v]));

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-light text-fg">Purchase Orders</h1>
          <p className="text-sm text-mist">AIR/PO/&lt;FY&gt;/&lt;seq&gt; numbering, server-computed GST split.</p>
        </div>
        <Link href="/pos/new" className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">
          + New PO
        </Link>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : pos.length === 0 ? (
        <p className="text-sm text-mist">No purchase orders yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
              <tr><th className="px-3 py-2">PO No.</th><th className="px-3 py-2">Vendor</th><th className="px-3 py-2">Date</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Freight</th></tr>
            </thead>
            <tbody>
              {pos.map((p) => (
                <tr key={p.id} className="border-t border-hair hover:bg-midnight">
                  <td className="px-3 py-2"><Link href={`/pos/${p.id}`} className="font-mono text-sm font-medium text-copper hover:underline">{p.po_no}</Link></td>
                  <td className="px-3 py-2 text-fg">{vendorById.get(p.vendor_id)?.name ?? p.vendor_id}</td>
                  <td className="px-3 py-2 font-mono text-mist">{p.po_date}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="px-3 py-2 font-mono text-mist">{p.freight ?? "-"}</td>
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
