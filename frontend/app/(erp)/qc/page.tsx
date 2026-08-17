"use client";

import { useEffect, useState } from "react";
import {
  createQcRecord, createUnitSerial, listFabricationJobs, listInventoryLots, listUnitSerials, ErpApiError,
} from "@/lib/erp/api";
import type { FabricationJob, InventoryLot, UnitSerial } from "@/lib/erp/types";

const emptyForm = {
  target: "lot" as "lot" | "job" | "serial",
  lot_id: "", job_id: "", unit_serial: "",
  type: "incoming" as "incoming" | "in_process" | "final",
  result: "pass", inspector: "",
};

export default function QcPage() {
  const [lots, setLots] = useState<InventoryLot[]>([]);
  const [jobs, setJobs] = useState<FabricationJob[]>([]);
  const [serials, setSerials] = useState<UnitSerial[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [newSerial, setNewSerial] = useState("");
  const [newSerialModel, setNewSerialModel] = useState("");

  function load() {
    Promise.all([listInventoryLots(), listFabricationJobs(), listUnitSerials()])
      .then(([l, j, s]) => { setLots(l.lots); setJobs(j.jobs); setSerials(s.unit_serials); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load"));
  }
  useEffect(load, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const rec = await createQcRecord({
        lot_id: form.target === "lot" ? form.lot_id : null,
        job_id: form.target === "job" ? form.job_id : null,
        unit_serial: form.target === "serial" ? form.unit_serial : null,
        type: form.type,
        result: form.result || null,
        inspector: form.inspector || null,
      });
      setSuccess(`QC record ${rec.id.slice(0, 8)} recorded (${rec.type}, result: ${rec.result}).`);
      setForm({ ...emptyForm, target: form.target });
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to record QC");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateSerial(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createUnitSerial({ serial: newSerial, model: newSerialModel || null });
      setNewSerial(""); setNewSerialModel("");
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create unit serial");
    }
  }

  const RESULT_ACCENT: Record<string, string> = { pass: "text-moss", fail: "text-rust", rework: "text-copper" };

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-light text-fg">QC Entry</h1>
      <p className="mb-4 text-sm text-mist">Record an incoming / in-process / final QC result against a lot, job, or unit serial.</p>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}
      {success && (
        <p className={`mb-4 rounded-lg border border-hair bg-panel px-3 py-2 text-sm ${RESULT_ACCENT[form.result] ?? "text-fg"}`}>
          {success}
        </p>
      )}

      <form onSubmit={handleSubmit} className="mb-8 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Target *</span>
          <select value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value as "lot" | "job" | "serial" })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
            <option value="lot" className="bg-panel">Inventory lot (incoming QC)</option>
            <option value="job" className="bg-panel">Fabrication job (in-process QC)</option>
            <option value="serial" className="bg-panel">Unit serial (final QC)</option>
          </select>
        </label>

        {form.target === "lot" && (
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-fg">Lot *</span>
            <select required value={form.lot_id} onChange={(e) => setForm({ ...form, lot_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- select --</option>
              {lots.map((l) => <option key={l.lot_id} value={l.lot_id} className="bg-panel">{l.lot_id.slice(0, 8)} ({l.heat_no || "no heat no."})</option>)}
            </select>
          </label>
        )}
        {form.target === "job" && (
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-fg">Fabrication job *</span>
            <select required value={form.job_id} onChange={(e) => setForm({ ...form, job_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- select --</option>
              {jobs.map((j) => <option key={j.id} value={j.id} className="bg-panel">{j.id.slice(0, 8)} ({j.status})</option>)}
            </select>
          </label>
        )}
        {form.target === "serial" && (
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-fg">Unit serial *</span>
            <select required value={form.unit_serial} onChange={(e) => setForm({ ...form, unit_serial: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
              <option value="" className="bg-panel">-- select --</option>
              {serials.map((s) => <option key={s.serial} value={s.serial} className="bg-panel">{s.serial}</option>)}
            </select>
          </label>
        )}

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">QC type</span>
          <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as typeof form.type })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
            <option value="incoming" className="bg-panel">Incoming</option>
            <option value="in_process" className="bg-panel">In-process</option>
            <option value="final" className="bg-panel">Final</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Result</span>
          <select value={form.result} onChange={(e) => setForm({ ...form, result: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
            <option value="pass" className="bg-panel">Pass</option>
            <option value="fail" className="bg-panel">Fail</option>
            <option value="rework" className="bg-panel">Rework</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Inspector</span>
          <input value={form.inspector} onChange={(e) => setForm({ ...form, inspector: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
        </label>

        <div className="sm:col-span-4">
          <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
            {saving ? "Saving..." : "Record QC result"}
          </button>
        </div>
      </form>

      <div className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <h2 className="mb-2 text-sm font-semibold text-fg">Register a new unit serial</h2>
        <p className="mb-3 text-xs text-mist">Needed before QC/jobs can reference it - unit_serials has no other creation UI in this schema.</p>
        <form onSubmit={handleCreateSerial} className="flex flex-wrap items-end gap-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Serial *</span>
            <input required value={newSerial} onChange={(e) => setNewSerial(e.target.value)} className="rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" placeholder="AIR-FGD-0001" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-fg">Model</span>
            <input value={newSerialModel} onChange={(e) => setNewSerialModel(e.target.value)} className="rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
          </label>
          <button type="submit" className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:border-copper">Create serial</button>
        </form>
        {serials.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2">
            {serials.map((s) => <li key={s.serial} className="rounded-md bg-midnight px-2 py-0.5 font-mono text-xs text-mist">{s.serial} ({s.status})</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}
