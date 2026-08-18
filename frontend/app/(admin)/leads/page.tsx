"use client";

import { useEffect, useState } from "react";
import { listLeads, createLead, updateLeadStage, listAdminPlants, AdminApiError } from "@/lib/admin-api";
import type { AdminPlantSummary, Lead, LeadStage } from "@/lib/admin-types";

// Deliberately one flat table with a stage dropdown per row, not a
// drag-and-drop Kanban board - the enterprise spec is explicit that CRM
// here "does not need to become an 11th giant department," and a
// dropdown does everything a board does for a pipeline this small.
const STAGES: LeadStage[] = ["lead", "site_assessment", "proposal", "contract_sent", "won", "lost"];
const STAGE_LABELS: Record<LeadStage, string> = {
  lead: "Lead",
  site_assessment: "Site assessment",
  proposal: "Proposal",
  contract_sent: "Contract sent",
  won: "Won",
  lost: "Lost",
};
const STAGE_STYLES: Record<LeadStage, string> = {
  lead: "border-line bg-midnight text-mist",
  site_assessment: "border-copper/40 bg-copper/10 text-copper",
  proposal: "border-copper/40 bg-copper/10 text-copper",
  contract_sent: "border-sand/40 bg-sand/10 text-sand",
  won: "border-moss/40 bg-moss/10 text-moss",
  lost: "border-rust/40 bg-rust/10 text-rust",
};

const INPUT = "rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none";

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[] | null>(null);
  const [plants, setPlants] = useState<AdminPlantSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [pendingWin, setPendingWin] = useState<string | null>(null);
  const [pendingLoss, setPendingLoss] = useState<string | null>(null);
  const [winPlantId, setWinPlantId] = useState("");
  const [lossReason, setLossReason] = useState("");

  const [companyName, setCompanyName] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [source, setSource] = useState("");
  const [capacity, setCapacity] = useState("");
  const [notes, setNotes] = useState("");

  function refresh() {
    Promise.all([listLeads(), listAdminPlants()])
      .then(([l, p]) => {
        setLeads(l.leads);
        setPlants(p.plants);
      })
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load leads"));
  }

  useEffect(refresh, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setBusy("create");
    setError(null);
    try {
      await createLead({
        company_name: companyName,
        contact_name: contactName || null,
        contact_email: contactEmail || null,
        source: source || null,
        estimated_boiler_capacity_tpd: capacity ? Number(capacity) : null,
        notes: notes || null,
      });
      setCompanyName("");
      setContactName("");
      setContactEmail("");
      setSource("");
      setCapacity("");
      setNotes("");
      setOpen(false);
      refresh();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to create lead");
    } finally {
      setBusy(null);
    }
  }

  async function handleAdvance(lead: Lead, nextStage: LeadStage) {
    if (nextStage === "won") {
      setPendingWin(lead.id);
      return;
    }
    if (nextStage === "lost") {
      setPendingLoss(lead.id);
      return;
    }
    setBusy(lead.id);
    setError(null);
    try {
      await updateLeadStage(lead.id, { stage: nextStage });
      refresh();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to update stage");
    } finally {
      setBusy(null);
    }
  }

  async function confirmWin(leadId: string) {
    if (!winPlantId) return;
    setBusy(leadId);
    setError(null);
    try {
      await updateLeadStage(leadId, { stage: "won", converted_plant_id: winPlantId });
      setPendingWin(null);
      setWinPlantId("");
      refresh();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to mark won");
    } finally {
      setBusy(null);
    }
  }

  async function confirmLoss(leadId: string) {
    if (!lossReason.trim()) return;
    setBusy(leadId);
    setError(null);
    try {
      await updateLeadStage(leadId, { stage: "lost", lost_reason: lossReason });
      setPendingLoss(null);
      setLossReason("");
      refresh();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to mark lost");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="font-display text-2xl font-light text-fg">Leads</h1>
          <p className="text-sm text-mist">
            Lead → site assessment → proposal → contract sent → won (linked to a real deployed plant)
            or lost (with a reason). Cross-cutting, not a separate department.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="air-track rounded-full border border-line px-3 py-1.5 text-sm text-fg hover:border-copper"
        >
          {open ? "Cancel" : "+ New lead"}
        </button>
      </div>

      {error && <p className="text-sm text-rust">{error}</p>}

      {open && (
        <form onSubmit={handleCreate} className="air-rise flex flex-wrap items-end gap-3 rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Company (required)</span>
            <input required value={companyName} onChange={(e) => setCompanyName(e.target.value)} className={`${INPUT} w-56`} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Contact name</span>
            <input value={contactName} onChange={(e) => setContactName(e.target.value)} className={INPUT} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Contact email</span>
            <input type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} className={INPUT} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Source</span>
            <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="referral, inbound, ..." className={`${INPUT} w-40`} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Boiler capacity (TPD)</span>
            <input type="number" min={0} value={capacity} onChange={(e) => setCapacity(e.target.value)} className={`${INPUT} w-32`} />
          </label>
          <label className="flex flex-col gap-1 flex-1 min-w-[200px]">
            <span className="font-mono text-[11px] text-mist uppercase">Notes</span>
            <input value={notes} onChange={(e) => setNotes(e.target.value)} className={INPUT} />
          </label>
          <button type="submit" disabled={busy === "create"} className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40">
            {busy === "create" ? "Saving…" : "Create lead"}
          </button>
        </form>
      )}

      <div className="overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
            <tr>
              <th className="px-3 py-2">Company</th>
              <th className="px-3 py-2">Contact</th>
              <th className="px-3 py-2">Capacity</th>
              <th className="px-3 py-2">Stage</th>
              <th className="px-3 py-2">Detail</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {(leads ?? []).map((lead) => (
              <tr key={lead.id} className="border-b border-hair last:border-0 align-top">
                <td className="px-3 py-2">
                  <div className="font-medium text-fg">{lead.company_name}</div>
                  {lead.source && <div className="font-mono text-[10px] text-mist">{lead.source}</div>}
                </td>
                <td className="px-3 py-2 text-xs text-mist">
                  {lead.contact_name}
                  {lead.contact_email && <div>{lead.contact_email}</div>}
                </td>
                <td className="px-3 py-2 font-mono text-fg">
                  {lead.estimated_boiler_capacity_tpd ? `${lead.estimated_boiler_capacity_tpd} TPD` : "—"}
                </td>
                <td className="px-3 py-2">
                  <span className={`inline-flex rounded-md border px-2 py-0.5 font-mono text-xs font-medium ${STAGE_STYLES[lead.stage]}`}>
                    {STAGE_LABELS[lead.stage]}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs text-mist">
                  {lead.stage === "won" && `→ ${lead.converted_plant_id}`}
                  {lead.stage === "lost" && lead.lost_reason}
                </td>
                <td className="px-3 py-2">
                  {lead.stage !== "won" && lead.stage !== "lost" && (
                    <select
                      value=""
                      onChange={(e) => handleAdvance(lead, e.target.value as LeadStage)}
                      disabled={busy === lead.id}
                      className={`${INPUT} text-xs`}
                    >
                      <option value="" className="bg-panel">move to…</option>
                      {STAGES.filter((s) => s !== lead.stage).map((s) => (
                        <option key={s} value={s} className="bg-panel">{STAGE_LABELS[s]}</option>
                      ))}
                    </select>
                  )}
                  {pendingWin === lead.id && (
                    <div className="air-rise mt-2 flex items-center gap-2 rounded-lg border border-moss/40 bg-moss/10 p-2">
                      <select value={winPlantId} onChange={(e) => setWinPlantId(e.target.value)} className={`${INPUT} text-xs`}>
                        <option value="" className="bg-panel">select deployed plant</option>
                        {plants.map((p) => (
                          <option key={p.plant_id} value={p.plant_id} className="bg-panel">{p.plant_id}</option>
                        ))}
                      </select>
                      <button onClick={() => confirmWin(lead.id)} disabled={!winPlantId} className="rounded-lg bg-moss px-2 py-1 text-xs font-semibold text-bg disabled:opacity-40">
                        Confirm won
                      </button>
                    </div>
                  )}
                  {pendingLoss === lead.id && (
                    <div className="air-rise mt-2 flex items-center gap-2 rounded-lg border border-rust/40 bg-rust/10 p-2">
                      <input value={lossReason} onChange={(e) => setLossReason(e.target.value)} placeholder="why lost?" className={`${INPUT} w-40 text-xs`} />
                      <button onClick={() => confirmLoss(lead.id)} disabled={!lossReason.trim()} className="rounded-lg bg-rust px-2 py-1 text-xs font-semibold text-fg disabled:opacity-40">
                        Confirm lost
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {leads?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-mist">No leads yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
