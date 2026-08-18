"use client";

import { useEffect, useRef, useState } from "react";
import { listDocuments, uploadDocument, deleteDocument, AdminApiError } from "@/lib/admin-api";
import type { DocumentEntityType, DocumentRecord } from "@/lib/admin-types";

function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Drop-in file attachment panel for any entity - a plant, a contract, a
 * vendor, a PO. One component instead of a bespoke upload widget per
 * page, matching the backend's generic (entity_type, entity_id) design
 * (migration 0009_documents). Usage: <DocumentsPanel entityType="plant"
 * entityId={plantId} />. */
export default function DocumentsPanel({
  entityType,
  entityId,
  title = "Documents",
}: {
  entityType: DocumentEntityType;
  entityId: string;
  title?: string;
}) {
  const [docs, setDocs] = useState<DocumentRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const notesInput = useRef<HTMLInputElement>(null);

  function refresh() {
    listDocuments(entityType, entityId)
      .then((res) => setDocs(res.documents))
      .catch((e: unknown) => setError(e instanceof AdminApiError ? e.message : "failed to load documents"));
  }

  useEffect(refresh, [entityType, entityId]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await uploadDocument(entityType, entityId, file, notesInput.current?.value || undefined);
      if (fileInput.current) fileInput.current.value = "";
      if (notesInput.current) notesInput.current.value = "";
      refresh();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId: string) {
    setDeleting(documentId);
    try {
      await deleteDocument(documentId);
      setDocs((prev) => (prev ? prev.filter((d) => d.document_id !== documentId) : prev));
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "delete failed");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="rounded-xl border border-line bg-midnight/60 p-3">
      <h3 className="mb-2 font-mono text-[11px] tracking-[0.1em] text-mist uppercase">
        {title} ({docs?.length ?? "…"})
      </h3>

      {docs && docs.length > 0 && (
        <ul className="mb-3 flex flex-col gap-1.5">
          {docs.map((d) => (
            <li key={d.document_id} className="flex items-center justify-between gap-2 text-sm">
              <a
                href={d.download_url}
                target="_blank"
                rel="noreferrer"
                className="min-w-0 truncate text-copper underline decoration-line hover:text-fg hover:decoration-copper"
                title={d.notes ?? undefined}
              >
                {d.filename}
              </a>
              <span className="shrink-0 font-mono text-[10px] text-mist">{fmtBytes(d.bytes)}</span>
              <button
                type="button"
                onClick={() => handleDelete(d.document_id)}
                disabled={deleting === d.document_id}
                className="shrink-0 text-[11px] text-mist hover:text-rust disabled:opacity-40"
              >
                {deleting === d.document_id ? "…" : "remove"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {docs && docs.length === 0 && <p className="mb-3 text-xs text-mist">No documents attached yet.</p>}

      <form onSubmit={handleUpload} className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInput}
          type="file"
          required
          className="max-w-[180px] text-xs text-mist file:mr-2 file:rounded-full file:border file:border-line file:bg-transparent file:px-2.5 file:py-1 file:text-xs file:text-fg"
        />
        <input
          ref={notesInput}
          type="text"
          placeholder="note (optional)"
          className="w-32 rounded-lg border border-line bg-transparent px-2 py-1 text-xs text-fg focus:border-copper focus:outline-none"
        />
        <button
          type="submit"
          disabled={uploading}
          className="rounded-full bg-copper px-3 py-1 text-xs font-medium text-bg disabled:opacity-40"
        >
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </form>
      {error && <p className="mt-1.5 text-xs text-rust">{error}</p>}
    </div>
  );
}
