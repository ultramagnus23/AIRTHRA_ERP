"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  requestBomChange,
  listBomChangeRequests,
  approveBomChangeRequest,
  rejectBomChangeRequest,
  ErpApiError,
} from "@/lib/erp/api";
import type { BomChangeRequest } from "@/lib/erp/types";

const STATUS_STYLES: Record<BomChangeRequest["status"], string> = {
  pending: "border-copper/40 bg-copper/10 text-copper",
  approved: "border-moss/40 bg-moss/10 text-moss",
  rejected: "border-rust/40 bg-rust/10 text-rust",
};

/** Formal engineering-change-request trail for one BOM: request (with a
 * reason) -> approve (creates the new draft revision atomically) or
 * reject (with a note). Additive to the page's own direct "Revise"
 * button - see api/routers/erp_boms.py's module docstring for when each
 * path is appropriate. `onRevised` refetches the parent page's BOM after
 * an approval, since the BOM's own state doesn't change but a sibling
 * revision now exists worth surfacing.
 */
export default function ChangeRequestsPanel({
  bomId,
  bomStatus,
  onRevised,
}: {
  bomId: string;
  bomStatus: "draft" | "released";
  onRevised: () => void;
}) {
  const [requests, setRequests] = useState<BomChangeRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [reason, setReason] = useState("");
  const [affectedNote, setAffectedNote] = useState("");
  const [newRevision, setNewRevision] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [rejectNoteFor, setRejectNoteFor] = useState<string | null>(null);
  const [rejectNote, setRejectNote] = useState("");

  function refresh() {
    listBomChangeRequests(bomId)
      .then((res) => setRequests(res.change_requests))
      .catch((e: unknown) => setError(e instanceof ErpApiError ? e.message : "failed to load change requests"));
  }

  useEffect(refresh, [bomId]);

  async function handleRequest(e: React.FormEvent) {
    e.preventDefault();
    setBusy("request");
    setError(null);
    try {
      await requestBomChange(bomId, { reason, affected_note: affectedNote || null, requested_new_revision: newRevision });
      setShowForm(false);
      setReason("");
      setAffectedNote("");
      setNewRevision("");
      refresh();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to request change");
    } finally {
      setBusy(null);
    }
  }

  async function handleApprove(id: string) {
    setBusy(id);
    setError(null);
    try {
      await approveBomChangeRequest(id);
      refresh();
      onRevised();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to approve");
    } finally {
      setBusy(null);
    }
  }

  async function handleReject(id: string) {
    if (!rejectNote.trim()) {
      setError("a rejection requires a note explaining why");
      return;
    }
    setBusy(id);
    setError(null);
    try {
      await rejectBomChangeRequest(id, rejectNote);
      setRejectNoteFor(null);
      setRejectNote("");
      refresh();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to reject");
    } finally {
      setBusy(null);
    }
  }

  const pending = requests.filter((r) => r.status === "pending");

  return (
    <div className="mb-6 rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
      <div className="flex items-baseline justify-between">
        <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">
          Change requests ({requests.length})
        </h2>
        {bomStatus === "released" && !showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="rounded-full border border-line px-3 py-1.5 text-sm text-fg hover:border-copper"
          >
            + Request change
          </button>
        )}
      </div>

      {error && <p className="mt-2 text-sm text-rust">{error}</p>}

      {showForm && (
        <form onSubmit={handleRequest} className="mt-3 flex flex-col gap-3 rounded-xl border border-line bg-midnight p-4">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Reason (required)</span>
            <textarea
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              placeholder="Why is this change needed?"
              className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">Affected components (optional)</span>
            <input
              value={affectedNote}
              onChange={(e) => setAffectedNote(e.target.value)}
              placeholder="Which items/parts does this touch?"
              className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] text-mist uppercase">New revision label</span>
            <input
              required
              value={newRevision}
              onChange={(e) => setNewRevision(e.target.value)}
              placeholder="e.g. B"
              className="w-32 rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
            />
          </label>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={busy === "request"}
              className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
            >
              {busy === "request" ? "Submitting…" : "Submit request"}
            </button>
            <button type="button" onClick={() => setShowForm(false)} className="text-sm text-mist hover:text-fg">
              Cancel
            </button>
          </div>
        </form>
      )}

      {requests.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {requests.map((r) => (
            <li key={r.id} className="rounded-xl border border-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span
                  className={`inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-xs font-medium ${STATUS_STYLES[r.status]}`}
                >
                  {r.status}
                </span>
                <span className="font-mono text-xs text-mist">→ rev {r.requested_new_revision}</span>
              </div>
              <p className="mt-1.5 text-sm text-fg">{r.reason}</p>
              {r.affected_note && <p className="mt-0.5 text-xs text-mist">Affects: {r.affected_note}</p>}
              {r.review_note && (
                <p className="mt-1.5 font-mono text-xs text-mist">Review note: {r.review_note}</p>
              )}
              {r.status === "approved" && r.resulting_bom_id && (
                <Link href={`/boms/${r.resulting_bom_id}`} className="mt-1.5 inline-block text-xs text-copper hover:underline">
                  View resulting revision →
                </Link>
              )}

              {r.status === "pending" && (
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => handleApprove(r.id)}
                    disabled={busy === r.id}
                    className="rounded-lg bg-moss px-3 py-1 text-xs font-semibold text-bg disabled:opacity-50"
                  >
                    {busy === r.id ? "…" : "Approve"}
                  </button>
                  {rejectNoteFor === r.id ? (
                    <>
                      <input
                        value={rejectNote}
                        onChange={(e) => setRejectNote(e.target.value)}
                        placeholder="reason for rejection"
                        className="w-56 rounded-lg border border-line bg-transparent px-2 py-1 text-xs text-fg focus:border-copper focus:outline-none"
                      />
                      <button
                        onClick={() => handleReject(r.id)}
                        disabled={busy === r.id}
                        className="rounded-lg bg-rust px-3 py-1 text-xs font-semibold text-fg disabled:opacity-50"
                      >
                        Confirm reject
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setRejectNoteFor(r.id)}
                      className="text-xs text-mist hover:text-rust"
                    >
                      Reject
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {requests.length === 0 && !showForm && (
        <p className="mt-2 text-xs text-mist">No change requests filed for this BOM.</p>
      )}
      {pending.length > 0 && (
        <p className="mt-2 font-mono text-[11px] text-copper">{pending.length} pending review.</p>
      )}
    </div>
  );
}
