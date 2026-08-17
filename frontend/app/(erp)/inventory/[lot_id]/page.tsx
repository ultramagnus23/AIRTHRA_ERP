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

  if (loading) return <p className="text-sm text-mist">Loading...</p>;
  if (error) return <p className="rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>;
  if (!data) return null;

  const { lot, qc_records, issue_lines, fabrication_jobs, unit_serials, installations } = data;

  return (
    <div>
      <Link href="/inventory" className="mb-4 inline-block text-sm text-copper hover:underline">&larr; Back to inventory</Link>
      <h1 className="mb-1 font-display text-2xl font-light text-fg">Genealogy: lot {lot.lot_id.slice(0, 8)}</h1>
      <p className="mb-6 text-sm text-mist">Full forward trace: vendor &rarr; PO &rarr; GRN &rarr; lot &rarr; QC &rarr; fabrication job &rarr; unit serial &rarr; installation.</p>

      <ol className="space-y-0">
        <ChainHop n={1} label="Vendor">
          {lot.vendor_name ? (
            <Kv pairs={[["Vendor", lot.vendor_name], ["GSTIN", lot.vendor_gstin ?? "-"]]} />
          ) : (
            <Empty text="No vendor linked (lot was not created from a GRN line)." />
          )}
        </ChainHop>

        <ChainHop n={2} label="Purchase order">
          {lot.po_no ? (
            <Kv pairs={[["PO no.", lot.po_no], ["PO date", lot.po_date ?? "-"], ["PO status", lot.po_status ?? "-"]]} />
          ) : (
            <Empty text="No PO linked." />
          )}
        </ChainHop>

        <ChainHop n={3} label="GRN (goods received)">
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

        <ChainHop n={4} label="Inventory lot" current>
          <Kv pairs={[
            ["Material", lot.material_name], ["Qty on hand", `${lot.qty_on_hand} ${lot.unit}`],
            ["Location", lot.location ?? "-"], ["Heat no.", lot.heat_no ?? "-"],
          ]} />
        </ChainHop>

        <ChainHop n={5} label={`QC records (${qc_records.length})`}>
          {qc_records.length === 0 ? (
            <Empty text="No QC records for this lot yet." />
          ) : (
            <ul className="space-y-2">
              {qc_records.map((qc) => (
                <li key={qc.id} className="rounded-lg border border-hair bg-midnight p-2 text-sm text-fg">
                  <span className={`mr-2 rounded-md px-2 py-0.5 text-xs font-medium ${qc.result === "pass" ? "border border-moss text-moss" : qc.result === "fail" ? "border border-rust text-rust" : "border border-line text-mist"}`}>
                    {qc.type}
                  </span>
                  {qc.result ?? "pending"} - inspector {qc.inspector ?? "-"} - <span className="font-mono">{new Date(qc.ts).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          )}
        </ChainHop>

        <ChainHop n={6} label={`Material issued to fabrication (${issue_lines.length})`}>
          {issue_lines.length === 0 ? (
            <Empty text="This lot has not been issued to any fabrication job yet." />
          ) : (
            <ul className="space-y-2">
              {issue_lines.map((il) => (
                <li key={il.id} className="rounded-lg border border-hair bg-midnight p-2 text-sm text-fg">
                  Issued <span className="font-mono">{il.qty}</span> on <span className="font-mono">{new Date(il.issued_at).toLocaleString()}</span> {il.fabrication_job_id ? `to job ${il.fabrication_job_id.slice(0, 8)}` : "(no job linked)"}
                </li>
              ))}
            </ul>
          )}
        </ChainHop>

        <ChainHop n={7} label={`Fabrication jobs (${fabrication_jobs.length})`}>
          {fabrication_jobs.length === 0 ? (
            <Empty text="No fabrication jobs downstream of this lot yet." />
          ) : (
            <ul className="space-y-2">
              {fabrication_jobs.map((j) => (
                <li key={j.id} className="rounded-lg border border-hair bg-midnight p-2 text-sm text-fg">
                  Job <span className="font-mono">{j.id.slice(0, 8)}</span> - <StatusBadge status={j.status} /> {j.unit_serial ? `- serial ${j.unit_serial}` : ""}
                </li>
              ))}
            </ul>
          )}
        </ChainHop>

        <ChainHop n={8} label={`Unit serials (${unit_serials.length})`}>
          {unit_serials.length === 0 ? (
            <Empty text="No unit serials downstream yet." />
          ) : (
            <ul className="space-y-2">
              {unit_serials.map((u) => (
                <li key={u.serial} className="rounded-lg border border-hair bg-midnight p-2 text-sm text-fg">
                  <span className="font-mono">{u.serial}</span> {u.model ? `(${u.model})` : ""} - <StatusBadge status={u.status} />
                </li>
              ))}
            </ul>
          )}
        </ChainHop>

        <ChainHop n={9} label={`Installations / plants (${installations.length})`} last>
          {installations.length === 0 ? (
            <Empty text="Not yet installed at any plant." />
          ) : (
            <ul className="space-y-2">
              {installations.map((i) => (
                <li key={i.id} className="rounded-lg border border-hair bg-midnight p-2 text-sm text-fg">
                  Plant <span className="font-mono">{i.plant_id}</span> - installed <span className="font-mono">{i.installed_at ? new Date(i.installed_at).toLocaleString() : "-"}</span>, commissioned <span className="font-mono">{i.commissioned_at ? new Date(i.commissioned_at).toLocaleString() : "-"}</span>
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
  n, label, children, current, last,
}: { n: number; label: string; children: React.ReactNode; current?: boolean; last?: boolean }) {
  return (
    <li className="relative pb-6 pl-12">
      {/* Connecting vertical line running through the numbered badge column */}
      {!last && <span className="absolute top-9 left-[15px] h-[calc(100%-2.25rem)] w-px bg-hair" aria-hidden />}
      {/* Numbered mono badge marking this hop in the chain */}
      <span
        className={`absolute top-0 left-0 flex h-8 w-8 items-center justify-center rounded-full border font-mono text-xs text-fg ${
          current ? "border-moss bg-moss/20" : "border-hair bg-midnight"
        }`}
        aria-hidden
      >
        {n}
      </span>

      <div
        className="relative overflow-hidden rounded-2xl border border-hair bg-panel p-3"
        style={{ boxShadow: "var(--shadow-sm)" }}
      >
        <div className="absolute inset-x-0 top-0 h-[2px] bg-moss" aria-hidden />
        <h3 className="mb-2 flex items-center gap-1.5 font-mono text-xs tracking-[0.1em] text-mist uppercase">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-moss" aria-hidden />
          {label}
        </h3>
        {children}
      </div>
    </li>
  );
}

function Kv({ pairs }: { pairs: [string, string][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
      {pairs.map(([k, v]) => (
        <div key={k}><dt className="text-mist">{k}</dt><dd className="font-mono text-fg">{v}</dd></div>
      ))}
    </dl>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="rounded-lg border border-dashed border-line p-3 text-sm text-mist">{text}</p>;
}

function StatusBadge({ status }: { status: string }) {
  const done = status === "completed" || status === "installed" || status === "dispatched";
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${done ? "border border-moss text-moss" : "border border-line text-mist"}`}>
      {status}
    </span>
  );
}
