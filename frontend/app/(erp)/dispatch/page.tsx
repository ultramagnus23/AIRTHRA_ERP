"use client";

import { useEffect, useState } from "react";
import { createTrip, listTrips, ErpApiError } from "@/lib/erp/api";
import type { Trip } from "@/lib/erp/types";

const emptyForm = {
  vehicle_no: "", driver: "", phone: "",
  purpose: "koh_delivery" as "koh_delivery" | "k2so3_pickup" | "dispatch",
  origin: "", dest_plant_id: "", eway_bill_no: "",
};

// Route is /dispatch, not /logistics: app/(admin)/logistics/page.tsx already
// owns that path (fleet-wide logistics view built by the concurrent admin
// console phase) - Next.js route groups don't add a path segment, so
// (erp)/logistics and (admin)/logistics would collide. This screen is the
// ERP-side dispatcher action (start a trip) called for in the PRD brief;
// the "logistics" label is kept in the nav for continuity with that PRD
// wording even though the URL is /dispatch.
export default function LogisticsPage() {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [lastTrip, setLastTrip] = useState<Trip | null>(null);

  function load() {
    listTrips()
      .then((t) => setTrips(t.trips))
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load trips"))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setLastTrip(null);
    try {
      const trip = await createTrip({
        vehicle_no: form.vehicle_no, driver: form.driver || null, phone: form.phone || null,
        purpose: form.purpose, origin: form.origin || null, dest_plant_id: form.dest_plant_id || null,
        eway_bill_no: form.eway_bill_no || null,
      });
      setLastTrip(trip);
      setForm(emptyForm);
      setLoading(true);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to create trip");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-light text-fg">Dispatch / Trips</h1>
      <p className="mb-4 text-sm text-mist">
        Start a trip (dispatcher action). The live GPS trip map itself is the driver-facing mobile page - this only creates the trip and its one-time token.
      </p>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}

      {lastTrip?.token && (
        <div className="mb-4 rounded-2xl border border-hair bg-panel px-3 py-3 text-sm text-fg" style={{ boxShadow: "var(--shadow-sm)" }}>
          <p className="font-medium text-copper">Trip {lastTrip.id.slice(0, 8)} started. One-time driver token (not retrievable again):</p>
          <code className="mt-1 block break-all rounded-lg bg-midnight px-2 py-1 font-mono text-xs text-fg">{lastTrip.token}</code>
          <p className="mt-1 text-xs text-mist">Share this with the driver device - it authenticates GPS pings for this trip only.</p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="mb-8 grid grid-cols-1 gap-3 rounded-2xl border border-hair bg-panel p-4 sm:grid-cols-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Vehicle no. *</span>
          <input required value={form.vehicle_no} onChange={(e) => setForm({ ...form, vehicle_no: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" placeholder="GA-05-AB-1234" />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Driver</span>
          <input value={form.driver} onChange={(e) => setForm({ ...form, driver: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Phone</span>
          <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Purpose *</span>
          <select value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value as typeof form.purpose })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
            <option value="koh_delivery" className="bg-panel">KOH delivery</option>
            <option value="k2so3_pickup" className="bg-panel">K2SO3 pickup</option>
            <option value="dispatch" className="bg-panel">Dispatch (equipment)</option>
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Origin</span>
          <input value={form.origin} onChange={(e) => setForm({ ...form, origin: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" placeholder="Airthra Research, Verna, Goa" />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">Destination plant id</span>
          <input value={form.dest_plant_id} onChange={(e) => setForm({ ...form, dest_plant_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" placeholder="goa_pilot_01" />
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-fg">E-way bill no.</span>
          <input value={form.eway_bill_no} onChange={(e) => setForm({ ...form, eway_bill_no: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
        </label>
        <div className="flex items-end sm:col-span-4">
          <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
            {saving ? "Starting..." : "Start trip"}
          </button>
        </div>
      </form>

      <h2 className="mb-2 text-sm font-semibold text-fg">Trips</h2>
      {loading ? (
        <p className="text-sm text-mist">Loading...</p>
      ) : trips.length === 0 ? (
        <p className="text-sm text-mist">No trips yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
          <table className="w-full text-left text-sm">
            <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
              <tr><th className="px-3 py-2">Vehicle</th><th className="px-3 py-2">Purpose</th><th className="px-3 py-2">Origin</th><th className="px-3 py-2">Destination</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Started</th></tr>
            </thead>
            <tbody>
              {trips.map((t) => (
                <tr key={t.id} className="border-t border-hair hover:bg-midnight">
                  <td className="px-3 py-2 font-mono font-medium text-fg">{t.vehicle_no}</td>
                  <td className="px-3 py-2 capitalize text-mist">{t.purpose.replaceAll("_", " ")}</td>
                  <td className="px-3 py-2 text-mist">{t.origin || "-"}</td>
                  <td className="px-3 py-2 text-mist">{t.dest_plant_id || "-"}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${t.status === "completed" ? "bg-moss/20 text-moss" : t.status === "in_transit" ? "bg-copper/20 text-copper" : "bg-midnight text-mist"}`}>{t.status}</span>
                  </td>
                  <td className="px-3 py-2 font-mono text-mist">{t.started ? new Date(t.started).toLocaleString() : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
