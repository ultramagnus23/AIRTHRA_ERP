"use client";

import { Fragment, useEffect, useState } from "react";
import {
  listAdminPlants,
  listBuyers,
  createBuyer,
  listBatches,
  createBatch,
  recordBatchQc,
  allocateBatch,
  dispatchBatch,
  generateCoa,
  AdminApiError,
} from "@/lib/admin-api";
import type { AdminPlantSummary, Buyer, ProductBatch } from "@/lib/admin-types";

const QC_STYLES: Record<ProductBatch["qc_status"], string> = {
  pending: "border-line bg-midnight text-mist",
  passed: "border-moss/40 bg-moss/10 text-moss",
  failed: "border-rust/40 bg-rust/10 text-rust",
};
const STATUS_STYLES: Record<ProductBatch["status"], string> = {
  produced: "border-copper/40 bg-copper/10 text-copper",
  allocated: "border-sand/40 bg-sand/10 text-sand",
  dispatched: "border-moss/40 bg-moss/10 text-moss",
};

const INPUT = "rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none";

export default function OfftakePage() {
  const [plants, setPlants] = useState<AdminPlantSummary[]>([]);
  const [buyers, setBuyers] = useState<Buyer[]>([]);
  const [batches, setBatches] = useState<ProductBatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    Promise.all([listAdminPlants(), listBuyers(), listBatches()])
      .then(([p, b, batchesRes]) => {
        setPlants(p.plants);
        setBuyers(b.buyers);
        setBatches(batchesRes.batches);
      })
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load offtake data"));
  }

  useEffect(refresh, []);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-display text-2xl font-light text-fg">Offtake</h1>
        <p className="text-sm text-mist">
          Product batches (the chemical output each plant produces) → QC → Certificate of Analysis →
          buyer allocation → dispatch. QC is never inferred from sensor data — every pass/fail is a
          named human decision.
        </p>
      </div>

      {error && <p className="text-sm text-rust">{error}</p>}

      <BuyersSection buyers={buyers} onCreated={refresh} />
      <BatchesSection plants={plants} buyers={buyers} batches={batches} onChanged={refresh} />
    </div>
  );
}

function BuyersSection({ buyers, onCreated }: { buyers: Buyer[]; onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [gstin, setGstin] = useState("");
  const [contact, setContact] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createBuyer({ name, gstin: gstin || null, contact: contact || null, phone: phone || null });
      setName("");
      setGstin("");
      setContact("");
      setPhone("");
      setOpen(false);
      onCreated();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to create buyer");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
      <div className="flex items-baseline justify-between">
        <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">Buyers ({buyers.length})</h2>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="air-track rounded-full border border-line px-3 py-1.5 text-sm text-fg hover:border-copper"
        >
          {open ? "Cancel" : "+ New buyer"}
        </button>
      </div>

      {buyers.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {buyers.map((b) => (
            <span key={b.id} className="rounded-full border border-line px-3 py-1 font-mono text-xs text-fg">
              {b.name} {b.gstin && <span className="text-mist">· {b.gstin}</span>}
            </span>
          ))}
        </div>
      )}

      {open && (
        <form onSubmit={handleSubmit} className="air-rise mt-4 flex flex-wrap items-end gap-3 rounded-xl border border-line bg-midnight p-4">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Name</span>
            <input required value={name} onChange={(e) => setName(e.target.value)} className={INPUT} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">GSTIN</span>
            <input value={gstin} onChange={(e) => setGstin(e.target.value)} className={INPUT} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Contact</span>
            <input value={contact} onChange={(e) => setContact(e.target.value)} className={INPUT} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Phone</span>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} className={INPUT} />
          </label>
          <button type="submit" disabled={busy} className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40">
            {busy ? "Saving…" : "Save buyer"}
          </button>
          {error && <span className="text-sm text-rust">{error}</span>}
        </form>
      )}
    </section>
  );
}

function BatchesSection({
  plants,
  buyers,
  batches,
  onChanged,
}: {
  plants: AdminPlantSummary[];
  buyers: Buyer[];
  batches: ProductBatch[] | null;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [plantId, setPlantId] = useState("");
  const [batchNo, setBatchNo] = useState("");
  const [productName, setProductName] = useState("K2SO3");
  const [qtyKg, setQtyKg] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qcFormFor, setQcFormFor] = useState<string | null>(null);
  const [allocFormFor, setAllocFormFor] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setBusy("create");
    setError(null);
    try {
      await createBatch({ plant_id: plantId, batch_no: batchNo, product_name: productName, qty_kg: Number(qtyKg) });
      setBatchNo("");
      setQtyKg("");
      setOpen(false);
      onChanged();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to create batch");
    } finally {
      setBusy(null);
    }
  }

  async function handleDispatch(id: string) {
    setBusy(id);
    setError(null);
    try {
      await dispatchBatch(id);
      onChanged();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to dispatch");
    } finally {
      setBusy(null);
    }
  }

  async function handleGenerateCoa(id: string) {
    setBusy(id);
    setError(null);
    try {
      await generateCoa(id);
      onChanged();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to generate CoA");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
      <div className="flex items-baseline justify-between">
        <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">
          Product batches ({batches?.length ?? "…"})
        </h2>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="air-track rounded-full border border-line px-3 py-1.5 text-sm text-fg hover:border-copper"
        >
          {open ? "Cancel" : "+ New batch"}
        </button>
      </div>

      {open && (
        <form onSubmit={handleCreate} className="air-rise mt-4 flex flex-wrap items-end gap-3 rounded-xl border border-line bg-midnight p-4">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Plant</span>
            <select required value={plantId} onChange={(e) => setPlantId(e.target.value)} className={INPUT}>
              <option value="" className="bg-panel">select</option>
              {plants.map((p) => (
                <option key={p.plant_id} value={p.plant_id} className="bg-panel">{p.plant_id}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Batch no.</span>
            <input required value={batchNo} onChange={(e) => setBatchNo(e.target.value)} placeholder="GOA-K2SO3-2026-08-003" className={`${INPUT} w-56`} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Product</span>
            <input required value={productName} onChange={(e) => setProductName(e.target.value)} className={`${INPUT} w-28`} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Qty (kg)</span>
            <input required type="number" min={0} step="any" value={qtyKg} onChange={(e) => setQtyKg(e.target.value)} className={`${INPUT} w-28`} />
          </label>
          <button type="submit" disabled={busy === "create"} className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40">
            {busy === "create" ? "Saving…" : "Create batch"}
          </button>
        </form>
      )}
      {error && <p className="mt-2 text-sm text-rust">{error}</p>}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
            <tr>
              <th className="px-2 py-2">Batch</th>
              <th className="px-2 py-2">Product</th>
              <th className="px-2 py-2">Qty</th>
              <th className="px-2 py-2">QC</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2">Buyer</th>
              <th className="px-2 py-2">CoA</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {(batches ?? []).map((b) => {
              const buyer = buyers.find((x) => x.id === b.buyer_id);
              return (
                <Fragment key={b.id}>
                  <tr className="border-b border-hair last:border-0">
                    <td className="px-2 py-2">
                      <div className="font-mono text-xs text-fg">{b.batch_no}</div>
                      <div className="font-mono text-[10px] text-mist">{b.plant_id}</div>
                    </td>
                    <td className="px-2 py-2 text-fg">{b.product_name}</td>
                    <td className="px-2 py-2 font-mono text-fg">{b.qty_kg} kg</td>
                    <td className="px-2 py-2">
                      <span className={`inline-flex rounded-md border px-2 py-0.5 font-mono text-xs font-medium ${QC_STYLES[b.qc_status]}`}>
                        {b.qc_status}
                      </span>
                    </td>
                    <td className="px-2 py-2">
                      <span className={`inline-flex rounded-md border px-2 py-0.5 font-mono text-xs font-medium ${STATUS_STYLES[b.status]}`}>
                        {b.status}
                      </span>
                    </td>
                    <td className="px-2 py-2 font-mono text-xs text-mist">{buyer?.name ?? "—"}</td>
                    <td className="px-2 py-2">
                      {b.coa_download_url ? (
                        <a href={b.coa_download_url} target="_blank" rel="noreferrer" className="text-xs text-copper underline hover:text-fg">
                          Download
                        </a>
                      ) : b.qc_status === "passed" ? (
                        <button onClick={() => handleGenerateCoa(b.id)} disabled={busy === b.id} className="text-xs text-copper hover:text-fg disabled:opacity-40">
                          Generate
                        </button>
                      ) : (
                        <span className="text-xs text-mist">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {b.qc_status === "pending" && (
                        <button onClick={() => setQcFormFor(qcFormFor === b.id ? null : b.id)} className="text-xs text-copper hover:text-fg">
                          Record QC
                        </button>
                      )}
                      {b.qc_status === "passed" && b.status === "produced" && (
                        <button onClick={() => setAllocFormFor(allocFormFor === b.id ? null : b.id)} className="text-xs text-copper hover:text-fg">
                          Allocate
                        </button>
                      )}
                      {b.status === "allocated" && (
                        <button onClick={() => handleDispatch(b.id)} disabled={busy === b.id} className="text-xs text-copper hover:text-fg disabled:opacity-40">
                          {busy === b.id ? "…" : "Dispatch"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {qcFormFor === b.id && (
                    <tr className="border-b border-hair last:border-0">
                      <td colSpan={8} className="px-2 py-3">
                        <QcForm
                          batchId={b.id}
                          onDone={() => {
                            setQcFormFor(null);
                            onChanged();
                          }}
                        />
                      </td>
                    </tr>
                  )}
                  {allocFormFor === b.id && (
                    <tr className="border-b border-hair last:border-0">
                      <td colSpan={8} className="px-2 py-3">
                        <AllocateForm
                          batchId={b.id}
                          buyers={buyers}
                          onDone={() => {
                            setAllocFormFor(null);
                            onChanged();
                          }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {batches?.length === 0 && (
              <tr>
                <td colSpan={8} className="px-2 py-6 text-center text-mist">No batches yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function QcForm({ batchId, onDone }: { batchId: string; onDone: () => void }) {
  const [passed, setPassed] = useState(true);
  const [inspector, setInspector] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await recordBatchQc(batchId, { passed, inspector, result: result || null });
      onDone();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to record QC");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3 rounded-xl border border-line bg-midnight p-3">
      <label className="flex flex-col gap-1">
        <span className="font-mono text-[11px] text-mist uppercase">Result</span>
        <select value={passed ? "pass" : "fail"} onChange={(e) => setPassed(e.target.value === "pass")} className={INPUT}>
          <option value="pass" className="bg-panel">Pass</option>
          <option value="fail" className="bg-panel">Fail</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-mono text-[11px] text-mist uppercase">Inspector (required)</span>
        <input required value={inspector} onChange={(e) => setInspector(e.target.value)} className={INPUT} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-mono text-[11px] text-mist uppercase">Result note</span>
        <input value={result} onChange={(e) => setResult(e.target.value)} placeholder="e.g. assay 98.6%" className={`${INPUT} w-56`} />
      </label>
      <button type="submit" disabled={busy} className="rounded-full bg-copper px-3 py-1.5 text-xs font-medium text-bg disabled:opacity-40">
        {busy ? "Saving…" : "Submit QC"}
      </button>
      {error && <span className="text-xs text-rust">{error}</span>}
    </form>
  );
}

function AllocateForm({ batchId, buyers, onDone }: { batchId: string; buyers: Buyer[]; onDone: () => void }) {
  const [buyerId, setBuyerId] = useState("");
  const [rate, setRate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await allocateBatch(batchId, { buyer_id: buyerId, rate_inr_per_kg: rate ? Number(rate) : null });
      onDone();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to allocate");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3 rounded-xl border border-line bg-midnight p-3">
      <label className="flex flex-col gap-1">
        <span className="font-mono text-[11px] text-mist uppercase">Buyer</span>
        <select required value={buyerId} onChange={(e) => setBuyerId(e.target.value)} className={INPUT}>
          <option value="" className="bg-panel">select</option>
          {buyers.map((b) => (
            <option key={b.id} value={b.id} className="bg-panel">{b.name}</option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-mono text-[11px] text-mist uppercase">Rate (INR/kg)</span>
        <input type="number" min={0} step="any" value={rate} onChange={(e) => setRate(e.target.value)} className={`${INPUT} w-28`} />
      </label>
      <button type="submit" disabled={busy} className="rounded-full bg-copper px-3 py-1.5 text-xs font-medium text-bg disabled:opacity-40">
        {busy ? "Saving…" : "Confirm allocation"}
      </button>
      {error && <span className="text-xs text-rust">{error}</span>}
    </form>
  );
}
