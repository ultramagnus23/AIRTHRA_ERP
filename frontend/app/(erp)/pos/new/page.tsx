"use client";

import { useEffect, useState } from "react";
import { createPo, createPoFromBom, listBoms, listVendors, ErpApiError } from "@/lib/erp/api";
import type { Bom, Vendor } from "@/lib/erp/types";

interface ItemRow { description: string; hsn: string; qty: string; unit: string; rate: string; gst_rate: string }
const emptyItem = (): ItemRow => ({ description: "", hsn: "", qty: "1", unit: "nos", rate: "0", gst_rate: "18" });

export default function NewPoPage() {
  const [mode, setMode] = useState<"scratch" | "bom">("scratch");
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [boms, setBoms] = useState<Bom[]>([]);
  const [vendorId, setVendorId] = useState("");
  const [bomId, setBomId] = useState("");
  const [poDate, setPoDate] = useState("");
  const [deliveryAddress, setDeliveryAddress] = useState("");
  const [paymentTerms, setPaymentTerms] = useState("");
  const [deliveryTerms, setDeliveryTerms] = useState("");
  const [freight, setFreight] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<ItemRow[]>([emptyItem()]);
  const [defaultGst, setDefaultGst] = useState("18");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listVendors(), listBoms()])
      .then(([v, b]) => { setVendors(v); setBoms(b.filter((x) => x.status === "released")); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"));
  }, []);

  function updateItem(i: number, patch: Partial<ItemRow>) {
    setItems((arr) => arr.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      let po;
      if (mode === "bom") {
        if (!bomId) throw new Error("select a released BOM");
        po = await createPoFromBom({
          bom_id: bomId, vendor_id: vendorId, po_date: poDate || null,
          delivery_address: deliveryAddress || null, payment_terms: paymentTerms || null,
          delivery_terms: deliveryTerms || null, freight: freight ? Number(freight) : null,
          notes: notes || null, default_gst_rate: Number(defaultGst),
        });
      } else {
        po = await createPo({
          vendor_id: vendorId, po_date: poDate || null,
          delivery_address: deliveryAddress || null, payment_terms: paymentTerms || null,
          delivery_terms: deliveryTerms || null, freight: freight ? Number(freight) : null,
          notes: notes || null,
          items: items
            .filter((it) => it.description)
            .map((it) => ({
              description: it.description, hsn: it.hsn || null, qty: Number(it.qty),
              unit: it.unit, rate: Number(it.rate), gst_rate: Number(it.gst_rate),
            })),
        });
      }
      window.location.href = `/pos/${po.id}`;
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : e instanceof Error ? e.message : "failed to create PO");
      setSaving(false);
    }
  }

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-light text-fg">New Purchase Order</h1>
      <p className="mb-4 text-sm text-mist">PO number, GST split and amount-in-words are all computed server-side after creation.</p>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      <div className="mb-4 flex gap-2">
        <button
          onClick={() => setMode("scratch")}
          className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-200 [transition-timing-function:var(--ease)] ${
            mode === "scratch" ? "bg-rust text-fg" : "border border-line text-mist hover:border-copper"
          }`}
        >
          From scratch
        </button>
        <button
          onClick={() => setMode("bom")}
          className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors duration-200 [transition-timing-function:var(--ease)] ${
            mode === "bom" ? "bg-rust text-fg" : "border border-line text-mist hover:border-copper"
          }`}
        >
          From a released BOM
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4" style={{ boxShadow: "var(--shadow-sm)" }}>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Vendor *</span>
            <select required value={vendorId} onChange={(e) => setVendorId(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- select --</option>
              {vendors.map((v) => <option key={v.id} value={v.id} className="bg-panel">{v.name} ({v.state_code ?? "?"})</option>)}
            </select>
          </label>
          {mode === "bom" && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-fg">Released BOM *</span>
              <select required value={bomId} onChange={(e) => setBomId(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
                <option value="" className="bg-panel">-- select --</option>
                {boms.map((b) => <option key={b.id} value={b.id} className="bg-panel">{b.name} rev {b.revision}</option>)}
              </select>
            </label>
          )}
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">PO date</span>
            <input type="date" value={poDate} onChange={(e) => setPoDate(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Freight</span>
            <input type="number" value={freight} onChange={(e) => setFreight(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          {mode === "bom" && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-fg">Default GST rate %</span>
              <input type="number" value={defaultGst} onChange={(e) => setDefaultGst(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
            </label>
          )}
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-fg">Delivery address</span>
            <input value={deliveryAddress} onChange={(e) => setDeliveryAddress(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Payment terms</span>
            <input value={paymentTerms} onChange={(e) => setPaymentTerms(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Delivery terms</span>
            <input value={deliveryTerms} onChange={(e) => setDeliveryTerms(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <label className="block text-sm sm:col-span-4">
            <span className="mb-1 block font-medium text-fg">Notes</span>
            <input value={notes} onChange={(e) => setNotes(e.target.value)} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
        </div>

        {mode === "scratch" && (
          <div className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
            <h3 className="mb-3 text-sm font-semibold text-fg">Line items</h3>
            <div className="space-y-2">
              {items.map((it, i) => (
                <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-6">
                  <input placeholder="Description" value={it.description} onChange={(e) => updateItem(i, { description: e.target.value })} className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none sm:col-span-2" />
                  <input placeholder="HSN" value={it.hsn} onChange={(e) => updateItem(i, { hsn: e.target.value })} className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none font-mono" />
                  <input placeholder="Qty" type="number" value={it.qty} onChange={(e) => updateItem(i, { qty: e.target.value })} className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none font-mono" />
                  <input placeholder="Unit" value={it.unit} onChange={(e) => updateItem(i, { unit: e.target.value })} className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
                  <input placeholder="Rate" type="number" value={it.rate} onChange={(e) => updateItem(i, { rate: e.target.value })} className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none font-mono" />
                  <input placeholder="GST %" type="number" value={it.gst_rate} onChange={(e) => updateItem(i, { gst_rate: e.target.value })} className="rounded-lg border border-line bg-transparent px-2 py-1.5 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none font-mono" />
                </div>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <button type="button" onClick={() => setItems((arr) => [...arr, emptyItem()])} className="rounded-lg border border-line px-3 py-1.5 text-sm text-fg hover:border-copper transition-colors duration-200 [transition-timing-function:var(--ease)]">+ Add line</button>
              {items.length > 1 && (
                <button type="button" onClick={() => setItems((arr) => arr.slice(0, -1))} className="rounded-lg border border-line px-3 py-1.5 text-sm text-fg hover:border-copper transition-colors duration-200 [transition-timing-function:var(--ease)]">Remove last</button>
              )}
            </div>
          </div>
        )}

        <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
          {saving ? "Creating..." : "Create PO"}
        </button>
      </form>
    </div>
  );
}
