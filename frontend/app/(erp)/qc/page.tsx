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

  return (
    <div>
      <h1 className="mb-1 text-lg font-semibold text-slate-900">QC Entry</h1>
      <p className="mb-4 text-sm text-slate-500">Record an incoming / in-process / final QC result against a lot, job, or unit serial.</p>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {success && <p className="mb-4 rounded-md bg-green-50 px-3 py-2 text-sm text-green-700">{success}</p>}

      <form onSubmit={handleSubmit} className="mb-8 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-4">
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Target *</span>
          <select value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value as "lot" | "job" | "serial" })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
            <option value="lot">Inventory lot (incoming QC)</option>
            <option value="job">Fabrication job (in-process QC)</option>
            <option value="serial">Unit serial (final QC)</option>
          </select>
        </label>

        {form.target === "lot" && (
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-slate-700">Lot *</span>
            <select required value={form.lot_id} onChange={(e) => setForm({ ...form, lot_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- select --</option>
              {lots.map((l) => <option key={l.lot_id} value={l.lot_id}>{l.lot_id.slice(0, 8)} ({l.heat_no || "no heat no."})</option>)}
            </select>
          </label>
        )}
        {form.target === "job" && (
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-slate-700">Fabrication job *</span>
            <select required value={form.job_id} onChange={(e) => setForm({ ...form, job_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- select --</option>
              {jobs.map((j) => <option key={j.id} value={j.id}>{j.id.slice(0, 8)} ({j.status})</option>)}
            </select>
          </label>
        )}
        {form.target === "serial" && (
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1 block font-medium text-slate-700">Unit serial *</span>
            <select required value={form.unit_serial} onChange={(e) => setForm({ ...form, unit_serial: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
              <option value="">-- select --</option>
              {serials.map((s) => <option key={s.serial} value={s.serial}>{s.serial}</option>)}
            </select>
          </label>
        )}

        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">QC type</span>
          <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as typeof form.type })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
            <option value="incoming">Incoming</option>
            <option value="in_process">In-process</option>
            <option value="final">Final</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Result</span>
          <select value={form.result} onChange={(e) => setForm({ ...form, result: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
            <option value="pass">Pass</option>
            <option value="fail">Fail</option>
            <option value="rework">Rework</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Inspector</span>
          <input value={form.inspector} onChange={(e) => setForm({ ...form, inspector: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
        </label>

        <div className="sm:col-span-4">
          <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            {saving ? "Saving..." : "Record QC result"}
          </button>
        </div>
      </form>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-900">Register a new unit serial</h2>
        <p className="mb-3 text-xs text-slate-500">Needed before QC/jobs can reference it - unit_serials has no other creation UI in this schema.</p>
        <form onSubmit={handleCreateSerial} className="flex flex-wrap items-end gap-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Serial *</span>
            <input required value={newSerial} onChange={(e) => setNewSerial(e.target.value)} className="rounded-md border border-slate-300 px-3 py-2 text-sm" placeholder="AIR-FGD-0001" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Model</span>
            <input value={newSerialModel} onChange={(e) => setNewSerialModel(e.target.value)} className="rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <button type="submit" className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white">Create serial</button>
        </form>
        {serials.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2">
            {serials.map((s) => <li key={s.serial} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{s.serial} ({s.status})</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}
