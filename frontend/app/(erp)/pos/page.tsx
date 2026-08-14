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
          <h1 className="text-lg font-semibold text-slate-900">Purchase Orders</h1>
          <p className="text-sm text-slate-500">AIR/PO/&lt;FY&gt;/&lt;seq&gt; numbering, server-computed GST split.</p>
        </div>
        <Link href="/pos/new" className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">
          + New PO
        </Link>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : pos.length === 0 ? (
        <p className="text-sm text-slate-500">No purchase orders yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2">PO No.</th><th className="px-3 py-2">Vendor</th><th className="px-3 py-2">Date</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Freight</th></tr>
            </thead>
            <tbody>
              {pos.map((p) => (
                <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2"><Link href={`/pos/${p.id}`} className="font-mono text-sm font-medium text-teal-700 hover:underline">{p.po_no}</Link></td>
                  <td className="px-3 py-2 text-slate-600">{vendorById.get(p.vendor_id)?.name ?? p.vendor_id}</td>
                  <td className="px-3 py-2 text-slate-600">{p.po_date}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(p.status)}`}>{p.status}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-600">{p.freight ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function statusColor(status: string) {
  const colors: Record<string, string> = {
    draft: "bg-slate-100 text-slate-700", issued: "bg-blue-100 text-blue-800",
    partial: "bg-amber-100 text-amber-800", received: "bg-green-100 text-green-800",
    closed: "bg-slate-200 text-slate-600", cancelled: "bg-red-100 text-red-800",
  };
  return colors[status] ?? "bg-slate-100 text-slate-700";
}
