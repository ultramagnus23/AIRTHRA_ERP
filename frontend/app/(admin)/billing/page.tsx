"use client";

import { Fragment, useEffect, useState } from "react";
import {
  approveInvoice,
  getInvoices,
  listAdminPlants,
  listContracts,
  createContract,
  AdminApiError,
} from "@/lib/admin-api";
import type { AdminPlantSummary, Contract, CreateContractInput, Invoice, InvoiceStatus } from "@/lib/admin-types";

// draft = pending/warning (copper), approved = success (moss),
// sent = neutral final state (mist/line) - matches DESIGN.md's semantic
// status-badge coding.
const STATUS_STYLES: Record<InvoiceStatus, string> = {
  draft: "border-copper/40 bg-copper/10 text-copper",
  approved: "border-moss/40 bg-moss/10 text-moss",
  sent: "border-line bg-midnight text-mist",
};

const STATUS_FILTERS: (InvoiceStatus | "all")[] = ["all", "draft", "approved", "sent"];

const INPUT = "rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none";

function fmtInr(n: number | null) {
  if (n === null) return "-";
  return `INR ${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function BillingPage() {
  const [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<InvoiceStatus | "all">("draft");
  const [approving, setApproving] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    getInvoices(statusFilter === "all" ? undefined : { status: statusFilter })
      .then((res) => setInvoices(res.invoices))
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load invoices"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  async function handleApprove(invoiceId: string) {
    setApproving(invoiceId);
    setRowError((prev) => ({ ...prev, [invoiceId]: "" }));
    try {
      const updated = await approveInvoice(invoiceId);
      setInvoices((prev) =>
        prev
          ? prev.map((inv) => (inv.invoice_id === invoiceId ? { ...inv, status: updated.status } : inv))
          : prev,
      );
    } catch (e) {
      setRowError((prev) => ({
        ...prev,
        [invoiceId]: e instanceof AdminApiError ? e.message : "approve failed",
      }));
    } finally {
      setApproving(null);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-display text-2xl font-light text-fg">Billing</h1>
        <p className="text-sm text-mist">
          Invoices are computed by workers/billing_worker.py against each plant&apos;s active
          contract below - a plant with no contract is skipped, never billed at a guessed rate.
        </p>
      </div>

      <ContractsSection />

      <section>
        <h2 className="mb-2 font-mono text-xs tracking-[0.15em] text-mist uppercase">Invoices</h2>
        <div className="mb-3 flex items-center gap-2 text-sm">
          <span className="font-mono text-xs tracking-[0.1em] text-mist uppercase">Status:</span>
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
                statusFilter === s ? "bg-rust text-fg" : "bg-midnight text-mist hover:text-fg"
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        {loading && <p className="font-mono text-sm text-mist">Loading...</p>}
        {error && <p className="text-sm text-rust">{error}</p>}

        {invoices && (
          <div
            className="overflow-x-auto rounded-2xl border border-hair bg-panel"
            style={{ boxShadow: "var(--shadow-sm)" }}
          >
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
                <tr>
                  <th className="px-4 py-2">Plant</th>
                  <th className="px-4 py-2">Period</th>
                  <th className="px-4 py-2">Amount</th>
                  <th className="px-4 py-2">SO2 (kg)</th>
                  <th className="px-4 py-2">Uptime %</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">PDF</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {invoices.map((inv) => {
                  const items = "total_inr" in inv.line_items ? inv.line_items : null;
                  const isOpen = expanded === inv.invoice_id;
                  return (
                    <Fragment key={inv.invoice_id}>
                      <tr className="border-b border-hair last:border-0">
                        <td className="px-4 py-2 font-mono text-xs text-fg">{inv.plant_id}</td>
                        <td className="px-4 py-2 font-mono text-fg">{inv.period}</td>
                        <td className="px-4 py-2">
                          {items ? (
                            <button
                              onClick={() => setExpanded(isOpen ? null : inv.invoice_id)}
                              className={`air-track font-mono ${
                                items.total_inr < 0 ? "text-rust" : "text-fg"
                              } underline decoration-line hover:decoration-copper`}
                            >
                              {fmtInr(inv.amount)}
                            </button>
                          ) : (
                            <span className="font-mono text-fg">{fmtInr(inv.amount)}</span>
                          )}
                        </td>
                        <td className="px-4 py-2 font-mono text-fg">{inv.so2_kg ?? "-"}</td>
                        <td className="px-4 py-2 font-mono text-fg">{inv.uptime_pct ?? "-"}</td>
                        <td className="px-4 py-2">
                          <span
                            className={`inline-flex items-center rounded-md border px-2.5 py-0.5 font-mono text-xs font-medium ${STATUS_STYLES[inv.status]}`}
                          >
                            {inv.status}
                          </span>
                        </td>
                        <td className="px-4 py-2">
                          {inv.pdf_url ? (
                            <a
                              href={inv.pdf_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs font-medium text-copper underline hover:text-fg"
                            >
                              Download
                            </a>
                          ) : (
                            <span className="text-xs text-mist">-</span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-right">
                          {inv.status === "draft" ? (
                            <button
                              onClick={() => handleApprove(inv.invoice_id)}
                              disabled={approving === inv.invoice_id}
                              className="rounded-lg bg-rust px-3 py-1 text-xs font-semibold text-fg transition-colors duration-150 hover:bg-copper disabled:opacity-50"
                            >
                              {approving === inv.invoice_id ? "Approving..." : "Approve"}
                            </button>
                          ) : null}
                          {rowError[inv.invoice_id] && (
                            <div className="mt-1 text-xs text-rust">{rowError[inv.invoice_id]}</div>
                          )}
                        </td>
                      </tr>
                      {isOpen && items && (
                        <tr key={`${inv.invoice_id}-detail`} className="border-b border-hair bg-midnight/40 last:border-0">
                          <td colSpan={8} className="px-4 py-3">
                            <div className="flex flex-wrap gap-x-8 gap-y-1 font-mono text-xs text-mist">
                              <span>Base fee: <span className="text-fg">{fmtInr(items.base_fee_inr)}</span></span>
                              <span>
                                Usage ({items.usage_rate_inr_per_kg}/kg): <span className="text-fg">{fmtInr(items.usage_fee_inr)}</span>
                              </span>
                              {items.performance_adjustment_inr !== 0 && (
                                <span>
                                  Performance ({items.performance_note}):{" "}
                                  <span className={items.performance_adjustment_inr < 0 ? "text-rust" : "text-moss"}>
                                    {items.performance_adjustment_inr > 0 ? "+" : ""}
                                    {fmtInr(items.performance_adjustment_inr)}
                                  </span>
                                </span>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
                {invoices.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-6 text-center text-mist">
                      No invoices for this filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function ContractsSection() {
  const [plants, setPlants] = useState<AdminPlantSummary[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<CreateContractInput>({
    plant_id: "",
    effective_from: new Date().toISOString().slice(0, 10),
    base_fee_inr: 0,
    usage_rate_inr_per_kg: 0,
  });

  function refresh() {
    Promise.all([listAdminPlants(), listContracts()])
      .then(([p, c]) => {
        setPlants(p.plants);
        setContracts(c.contracts);
      })
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load contracts"));
  }

  useEffect(refresh, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createContract(form);
      setOpen(false);
      setForm((f) => ({ ...f, plant_id: "", base_fee_inr: 0, usage_rate_inr_per_kg: 0 }));
      refresh();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to create contract");
    } finally {
      setBusy(false);
    }
  }

  const active = contracts.filter((c) => c.status === "active");

  return (
    <section
      className="rounded-2xl border border-hair bg-panel p-4"
      style={{ boxShadow: "var(--shadow-sm)" }}
    >
      <div className="flex items-baseline justify-between">
        <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">
          Active contracts ({active.length} of {plants.length} plants)
        </h2>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="air-track rounded-full border border-line px-3 py-1.5 text-sm text-fg hover:border-copper"
        >
          {open ? "Cancel" : "+ New / renew contract"}
        </button>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[680px] text-left text-sm">
          <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
            <tr>
              <th className="px-2 py-2">Plant</th>
              <th className="px-2 py-2">Since</th>
              <th className="px-2 py-2">Base fee</th>
              <th className="px-2 py-2">Usage rate</th>
              <th className="px-2 py-2">Bonus</th>
              <th className="px-2 py-2">Penalty</th>
            </tr>
          </thead>
          <tbody>
            {plants.map((p) => {
              const c = active.find((c) => c.plant_id === p.plant_id);
              return (
                <tr key={p.plant_id} className="border-b border-hair last:border-0">
                  <td className="px-2 py-2 font-mono text-xs text-fg">{p.plant_id}</td>
                  {c ? (
                    <>
                      <td className="px-2 py-2 font-mono text-xs text-mist">{c.effective_from}</td>
                      <td className="px-2 py-2 font-mono text-fg">{fmtInr(c.base_fee_inr)}</td>
                      <td className="px-2 py-2 font-mono text-fg">INR {c.usage_rate_inr_per_kg}/kg</td>
                      <td className="px-2 py-2 font-mono text-xs text-moss">
                        {c.performance_bonus_threshold_pct !== null
                          ? `+${fmtInr(c.performance_bonus_inr)} @ >=${c.performance_bonus_threshold_pct}%`
                          : "-"}
                      </td>
                      <td className="px-2 py-2 font-mono text-xs text-rust">
                        {c.performance_penalty_threshold_pct !== null
                          ? `-${fmtInr(c.performance_penalty_inr)} @ <${c.performance_penalty_threshold_pct}%`
                          : "-"}
                      </td>
                    </>
                  ) : (
                    <td colSpan={5} className="px-2 py-2 text-mist">
                      No active contract — not billed
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {open && (
        <form
          onSubmit={handleSubmit}
          className="air-rise mt-4 flex flex-col gap-3 rounded-xl border border-line bg-midnight p-4"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[11px] text-mist uppercase">Plant</span>
              <select
                required
                value={form.plant_id}
                onChange={(e) => setForm((f) => ({ ...f, plant_id: e.target.value }))}
                className={INPUT}
              >
                <option value="" className="bg-panel">select a plant</option>
                {plants.map((p) => (
                  <option key={p.plant_id} value={p.plant_id} className="bg-panel">
                    {p.plant_id}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[11px] text-mist uppercase">Effective from</span>
              <input
                type="date"
                required
                value={form.effective_from}
                onChange={(e) => setForm((f) => ({ ...f, effective_from: e.target.value }))}
                className={INPUT}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[11px] text-mist uppercase">Base fee (INR/mo)</span>
              <input
                type="number"
                min={0}
                value={form.base_fee_inr}
                onChange={(e) => setForm((f) => ({ ...f, base_fee_inr: Number(e.target.value) }))}
                className={INPUT}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[11px] text-mist uppercase">Usage rate (INR/kg SO2)</span>
              <input
                type="number"
                min={0}
                required
                value={form.usage_rate_inr_per_kg}
                onChange={(e) => setForm((f) => ({ ...f, usage_rate_inr_per_kg: Number(e.target.value) }))}
                className={INPUT}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[11px] text-mist uppercase">Bonus threshold (uptime %)</span>
              <input
                type="number"
                min={0}
                max={100}
                value={form.performance_bonus_threshold_pct ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    performance_bonus_threshold_pct: e.target.value === "" ? null : Number(e.target.value),
                  }))
                }
                className={INPUT}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[11px] text-mist uppercase">Bonus amount (INR)</span>
              <input
                type="number"
                min={0}
                value={form.performance_bonus_inr ?? 0}
                onChange={(e) => setForm((f) => ({ ...f, performance_bonus_inr: Number(e.target.value) }))}
                className={INPUT}
              />
            </label>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={busy}
              className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
            >
              {busy ? "Saving…" : "Save contract"}
            </button>
            {error && <span className="text-sm text-rust">{error}</span>}
          </div>
        </form>
      )}
    </section>
  );
}
