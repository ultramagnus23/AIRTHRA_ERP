"use client";

import { useEffect, useState } from "react";
import { createGrn, getPo, listGrn, listPos, ErpApiError } from "@/lib/erp/api";
import type { Grn, Po, PoLine } from "@/lib/erp/types";

interface LineForm { po_item_id: string; description: string; ordered: number; alreadyReceived: number; qty_received: string; qty_accepted: string; qty_rejected: string }

export default function GrnPage() {
  const [pos, setPos] = useState<Po[]>([]);
  const [grns, setGrns] = useState<Grn[]>([]);
  const [selectedPoId, setSelectedPoId] = useState("");
  const [poItems, setPoItems] = useState<PoLine[]>([]);
  const [grnNo, setGrnNo] = useState("");
  const [vehicleNo, setVehicleNo] = useState("");
  const [ewayBill, setEwayBill] = useState("");
  const [lines, setLines] = useState<LineForm[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  function load() {
    Promise.all([listPos(), listGrn()])
      .then(([p, g]) => { setPos(p.filter((x) => x.status === "issued" || x.status === "partial")); setGrns(g); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleSelectPo(poId: string) {
    setSelectedPoId(poId);
    setPoItems([]);
    setLines([]);
    if (!poId) return;
    try {
      const po = await getPo(poId);
      const items = po.items ?? [];
      setPoItems(items);
      setLines(
        items
          .filter((it) => it.received_qty < it.qty)
          .map((it) => ({
            po_item_id: it.id, description: it.description, ordered: it.qty, alreadyReceived: it.received_qty,
            qty_received: String(it.qty - it.received_qty), qty_accepted: String(it.qty - it.received_qty), qty_rejected: "0",
          })),
      );
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to load PO items");
    }
  }

  function updateLine(i: number, patch: Partial<LineForm>) {
    setLines((arr) => arr.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await createGrn({
        po_id: selectedPoId, grn_no: grnNo, vehicle_no: vehicleNo || null, eway_bill_no: ewayBill || null,
        lines: lines.map((l) => ({
          po_item_id: l.po_item_id, qty_received: Number(l.qty_received),
          qty_accepted: Number(l.qty_accepted), qty_rejected: Number(l.qty_rejected),
        })),
      });
      setGrnNo(""); setVehicleNo(""); setEwayBill(""); setSelectedPoId(""); setPoItems([]); setLines([]);
      setError(null);
      setSuccess(`GRN ${res.grn_no} recorded. PO status is now '${res.po_status}'.`);
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create GRN");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-light text-fg">GRN Receiving</h1>
      <p className="mb-4 text-sm text-mist">Record goods received against an issued/partial PO. Only qty_accepted counts toward PO fulfilment.</p>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}
      {success && <p className="mb-4 rounded-lg border border-hair bg-panel px-3 py-2 text-sm text-moss">{success}</p>}

      <form onSubmit={handleSubmit} className="mb-8 space-y-4 rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-fg">PO (issued/partial) *</span>
            <select required value={selectedPoId} onChange={(e) => handleSelectPo(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- select --</option>
              {pos.map((p) => <option key={p.id} value={p.id} className="bg-panel">{p.po_no} ({p.status})</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">GRN No. *</span>
            <input required value={grnNo} onChange={(e) => setGrnNo(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" placeholder="GRN-0001" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Vehicle no.</span>
            <input value={vehicleNo} onChange={(e) => setVehicleNo(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">E-way bill no.</span>
            <input value={ewayBill} onChange={(e) => setEwayBill(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
        </div>

        {poItems.length > 0 && (
          <div className="overflow-x-auto rounded-2xl border border-hair bg-panel">
            <table className="w-full text-left text-sm">
              <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
                <tr><th className="px-3 py-2">Item</th><th className="px-3 py-2">Ordered</th><th className="px-3 py-2">Already recv.</th><th className="px-3 py-2">Qty received</th><th className="px-3 py-2">Qty accepted</th><th className="px-3 py-2">Qty rejected</th></tr>
              </thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={l.po_item_id} className="border-t border-hair hover:bg-midnight">
                    <td className="px-3 py-2 text-fg">{l.description}</td>
                    <td className="px-3 py-2 font-mono text-fg">{l.ordered}</td>
                    <td className="px-3 py-2 font-mono text-mist">{l.alreadyReceived}</td>
                    <td className="px-3 py-2"><input type="number" step="any" value={l.qty_received} onChange={(e) => updateLine(i, { qty_received: e.target.value })} className="w-24 rounded-lg border border-line bg-transparent px-2 py-1 text-sm text-fg font-mono focus:border-copper focus:outline-none" /></td>
                    <td className="px-3 py-2"><input type="number" step="any" value={l.qty_accepted} onChange={(e) => updateLine(i, { qty_accepted: e.target.value })} className="w-24 rounded-lg border border-line bg-transparent px-2 py-1 text-sm text-fg font-mono focus:border-copper focus:outline-none" /></td>
                    <td className="px-3 py-2"><input type="number" step="any" value={l.qty_rejected} onChange={(e) => updateLine(i, { qty_rejected: e.target.value })} className="w-24 rounded-lg border border-line bg-transparent px-2 py-1 text-sm text-fg font-mono focus:border-copper focus:outline-none" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-3 py-2 font-mono text-xs text-mist">qty_received must equal qty_accepted + qty_rejected (enforced server-side).</p>
          </div>
        )}

        <button type="submit" disabled={saving || lines.length === 0} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
          {saving ? "Recording..." : "Record GRN"}
        </button>
      </form>

      <h2 className="mb-2 text-sm font-semibold text-fg">Recent GRNs</h2>
      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : grns.length === 0 ? (
        <p className="text-sm text-mist">No GRNs yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
              <tr><th className="px-3 py-2">GRN No.</th><th className="px-3 py-2">Date</th><th className="px-3 py-2">Vehicle</th><th className="px-3 py-2">E-way bill</th></tr>
            </thead>
            <tbody>
              {grns.map((g) => (
                <tr key={g.id} className="border-t border-hair hover:bg-midnight">
                  <td className="px-3 py-2 font-mono font-medium text-fg">{g.grn_no}</td>
                  <td className="px-3 py-2 font-mono text-mist">{g.date}</td>
                  <td className="px-3 py-2 text-mist">{g.vehicle_no || "-"}</td>
                  <td className="px-3 py-2 font-mono text-mist">{g.eway_bill_no || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
