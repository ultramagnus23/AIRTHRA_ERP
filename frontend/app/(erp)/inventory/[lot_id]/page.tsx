"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getLotGenealogy, ErpApiError } from "@/lib/erp/api";
import type { GenealogyResponse } from "@/lib/erp/types";

export default function LotGenealogyPage() {
  const params = useParams<{ lot_id: string }>();
  const [data, setData] = useState<GenealogyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getLotGenealogy(params.lot_id)
      .then(setData)
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load genealogy"))
      .finally(() => setLoading(false));
  }, [params.lot_id]);

  if (loading) return <p className="text-sm text-slate-500">Loading...</p>;
  if (error) return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!data) return null;

  const { lot, qc_records, issue_lines, fabrication_jobs, unit_serials, installations } = data;

  return (
    <div>
      <Link href="/inventory" className="mb-4 inline-block text-sm text-teal-700 hover:underline">&larr; Back to inventory</Link>
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Genealogy: lot {lot.lot_id.slice(0, 8)}</h1>
      <p className="mb-6 text-sm text-slate-500">Full forward trace: vendor &rarr; PO &rarr; GRN &rarr; lot &rarr; QC &rarr; fabrication job &rarr; unit serial &rarr; installation.</p>

      <ol className="space-y-0">
        <ChainHop title="1. Vendor" color="bg-violet-600">
          {lot.vendor_name ? (
            <Kv pairs={[["Vendor", lot.vendor_name], ["GSTIN", lot.vendor_gstin ?? "-"]]} />
          ) : (
            <Empty text="No vendor linked (lot was not created from a GRN line)." />
          )}
        </ChainHop>

        <ChainHop title="2. Purchase order" color="bg-indigo-600">
          {lot.po_no ? (
            <Kv pairs={[["PO no.", lot.po_no], ["PO date", lot.po_date ?? "-"], ["PO status", lot.po_status ?? "-"]]} />
          ) : (
            <Empty text="No PO linked." />
          )}
        </ChainHop>

        <ChainHop title="3. GRN (goods received)" color="bg-blue-600">
          {lot.grn_no ? (
            <Kv pairs={[
              ["GRN no.", lot.grn_no], ["GRN date", lot.grn_date ?? "-"], ["Vehicle", lot.vehicle_no ?? "-"],
              ["E-way bill", lot.eway_bill_no ?? "-"], ["Qty received", String(lot.qty_received ?? "-")],
              ["Qty accepted", String(lot.qty_accepted ?? "-")], ["Qty rejected", String(lot.qty_rejected ?? "-")],
            ]} />
          ) : (
            <Empty text="No GRN linked." />
          )}
        </ChainHop>

        <ChainHop title="4. Inventory lot" color="bg-cyan-600" current>
          <Kv pairs={[
            ["Material", lot.material_name], ["Qty on hand", `${lot.qty_on_hand} ${lot.unit}`],
            ["Location", lot.location ?? "-"], ["Heat no.", lot.heat_no ?? "-"],
          ]} />
        </ChainHop>

        <ChainHop title={`5. QC records (${qc_records.length})`} color="bg-teal-600">
          {qc_records.length === 0 ? (
            <Empty text="No QC records for this lot yet." />
          ) : (
            <ul className="space-y-2">
              {qc_records.map((qc) => (
                <li key={qc.id} className="rounded-md border border-slate-200 bg-white p-2 text-sm">
                  <span className={`mr-2 rounded-full px-2 py-0.5 text-xs font-medium ${qc.result === "pass" ? "bg-green-100 text-green-800" : qc.result === "fail" ? "bg-red-100 text-red-800" : "bg-slate-100 text-slate-700"}`}>
                    {qc.type}
                  </span>
                  {qc.result ?? "pending"} - inspector {qc.inspector ?? "-"} - {new Date(qc.ts).toLocaleString()}
                </li>
              ))}
            </ul>
          )}
        </ChainHop>

        <ChainHop title={`6. Material issued to fabrication (${issue_lines.length})`} color="bg-green-600">
          {issue_lines.length === 0 ? (
            <Empty text="This lot has not been issued to any fabrication job yet." />
          ) : (
            <ul className="space-y-2">
              {issue_lines.map((il) => (
                <li key={il.id} className="rounded-md border border-slate-200 bg-white p-2 text-sm">
                  Issued {il.qty} on {new Date(il.issued_at).toLocaleString()} {il.fabrication_job_id ? `to job ${il.fabrication_job_id.slice(0, 8)}` : "(no job linked)"}
                </li>
              ))}
            </ul>
          )}
        </ChainHop>

        <ChainHop title={`7. Fabrication jobs (${fabrication_jobs.length})`} color="bg-lime-600">
          {fabrication_jobs.length === 0 ? (
            <Empty text="No fabrication jobs downstream of this lot yet." />
          ) : (
            <ul className="space-y-2">
              {fabrication_jobs.map((j) => (
                <li key={j.id} className="rounded-md border border-slate-200 bg-white p-2 text-sm">
                  Job {j.id.slice(0, 8)} - <StatusBadge status={j.status} /> {j.unit_serial ? `- serial ${j.unit_serial}` : ""}
                </li>
              ))}
            </ul>
          )}
        </ChainHop>

        <ChainHop title={`8. Unit serials (${unit_serials.length})`} color="bg-amber-600">
          {unit_serials.length === 0 ? (
            <Empty text="No unit serials downstream yet." />
          ) : (
            <ul className="space-y-2">
              {unit_serials.map((u) => (
                <li key={u.serial} className="rounded-md border border-slate-200 bg-white p-2 text-sm">
                  {u.serial} {u.model ? `(${u.model})` : ""} - <StatusBadge status={u.status} />
                </li>
              ))}
            </ul>
          )}
        </ChainHop>

        <ChainHop title={`9. Installations / plants (${installations.length})`} color="bg-rose-600" last>
          {installations.length === 0 ? (
            <Empty text="Not yet installed at any plant." />
          ) : (
            <ul className="space-y-2">
              {installations.map((i) => (
                <li key={i.id} className="rounded-md border border-slate-200 bg-white p-2 text-sm">
                  Plant {i.plant_id} - installed {i.installed_at ? new Date(i.installed_at).toLocaleString() : "-"}, commissioned {i.commissioned_at ? new Date(i.commissioned_at).toLocaleString() : "-"}
                </li>
              ))}
            </ul>
          )}
        </ChainHop>
      </ol>
    </div>
  );
}

function ChainHop({
  title, color, children, current, last,
}: { title: string; color: string; children: React.ReactNode; current?: boolean; last?: boolean }) {
  return (
    <li className="relative pb-6 pl-8">
      {!last && <span className="absolute top-3 left-[11px] h-full w-px bg-slate-200" aria-hidden />}
      <span className={`absolute top-1 left-0 h-6 w-6 rounded-full ${color} ${current ? "ring-4 ring-teal-200" : ""}`} aria-hidden />
      <h3 className="mb-2 text-sm font-semibold text-slate-900">{title}</h3>
      {children}
    </li>
  );
}

function Kv({ pairs }: { pairs: [string, string][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-md border border-slate-200 bg-white p-3 text-sm sm:grid-cols-3">
      {pairs.map(([k, v]) => (
        <div key={k}><dt className="text-slate-500">{k}</dt><dd className="text-slate-800">{v}</dd></div>
      ))}
    </dl>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="rounded-md border border-dashed border-slate-200 bg-slate-50 p-3 text-sm text-slate-400">{text}</p>;
}

function StatusBadge({ status }: { status: string }) {
  return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{status}</span>;
}
