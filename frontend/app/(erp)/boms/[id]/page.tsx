"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  addBomItem, deleteBomItem, getBom, listMaterials, releaseBom, reviseBom, updateBomItem, weightPreview, ErpApiError,
} from "@/lib/erp/api";
import type { Bom, BomShape, Material, WeightPreview as WeightPreviewT } from "@/lib/erp/types";
import ChangeRequestsPanel from "./ChangeRequestsPanel";

const SHAPE_FIELDS: Record<BomShape, { key: string; label: string }[]> = {
  plate: [
    { key: "length_mm", label: "Length (mm)" },
    { key: "width_mm", label: "Width (mm)" },
    { key: "thickness_mm", label: "Thickness (mm)" },
  ],
  rod: [
    { key: "diameter_mm", label: "Diameter (mm)" },
    { key: "length_mm", label: "Length (mm)" },
  ],
  pipe: [
    { key: "od_mm", label: "OD (mm)" },
    { key: "wall_mm", label: "Wall thickness (mm)" },
    { key: "length_mm", label: "Length (mm)" },
  ],
  custom: [{ key: "unit_weight_kg", label: "Unit weight (kg) - catalog value" }],
};

interface ItemFormState {
  description: string;
  material_id: string;
  shape: BomShape;
  dims: Record<string, string>;
  qty: string;
  scrap_pct: string;
}

const emptyItemForm = (): ItemFormState => ({ description: "", material_id: "", shape: "plate", dims: {}, qty: "1", scrap_pct: "0" });

function DimsForm({ form, setForm }: { form: ItemFormState; setForm: (f: ItemFormState) => void }) {
  return (
    <>
      {SHAPE_FIELDS[form.shape].map((f) => (
        <label key={f.key} className="block text-sm">
          <span className="mb-1 block font-medium text-fg">{f.label}</span>
          <input
            type="number"
            step="any"
            value={form.dims[f.key] ?? ""}
            onChange={(e) => setForm({ ...form, dims: { ...form.dims, [f.key]: e.target.value } })}
            className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none"
          />
        </label>
      ))}
    </>
  );
}

function useDebouncedPreview(form: ItemFormState) {
  const [preview, setPreview] = useState<WeightPreviewT | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!form.material_id) { setPreview(null); return; }
    const dimsNumeric: Record<string, number> = {};
    let allFilled = true;
    for (const f of SHAPE_FIELDS[form.shape]) {
      const v = form.dims[f.key];
      if (v === undefined || v === "") { allFilled = false; break; }
      dimsNumeric[f.key] = Number(v);
    }
    if (!allFilled || !form.qty) { setPreview(null); return; }

    timer.current = setTimeout(() => {
      weightPreview({
        material_id: form.material_id, shape: form.shape, dims: dimsNumeric,
        qty: Number(form.qty), scrap_pct: Number(form.scrap_pct || 0),
      })
        .then((p) => { setPreview(p); setPreviewError(null); })
        .catch((e) => { setPreview(null); setPreviewError(e instanceof ErpApiError ? e.message : "preview failed"); });
    }, 300);

    return () => { if (timer.current) clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.material_id, form.shape, JSON.stringify(form.dims), form.qty, form.scrap_pct]);

  return { preview, previewError };
}

export default function BomEditorPage() {
  const params = useParams<{ id: string }>();
  const [bom, setBom] = useState<Bom | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [itemForm, setItemForm] = useState<ItemFormState>(emptyItemForm());
  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [reviseRev, setReviseRev] = useState("");
  const [showRevise, setShowRevise] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([getBom(params.id), listMaterials()])
      .then(([b, m]) => { setBom(b); setMaterials(m); })
      .catch((e) => setError(e instanceof ErpApiError ? e.message : "failed to load BOM"))
      .finally(() => setLoading(false));
  }, [params.id]);

  useEffect(load, [load]);

  const { preview, previewError } = useDebouncedPreview(itemForm);

  const readOnly = bom?.status === "released";

  async function handleAddItem(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const dimsNumeric: Record<string, number> = {};
    for (const f of SHAPE_FIELDS[itemForm.shape]) dimsNumeric[f.key] = Number(itemForm.dims[f.key] || 0);
    try {
      if (editingItemId) {
        await updateBomItem(params.id, editingItemId, {
          description: itemForm.description, material_id: itemForm.material_id, shape: itemForm.shape,
          dims: dimsNumeric, qty: Number(itemForm.qty), scrap_pct: Number(itemForm.scrap_pct || 0),
        });
      } else {
        await addBomItem(params.id, {
          description: itemForm.description, material_id: itemForm.material_id, shape: itemForm.shape,
          dims: dimsNumeric, qty: Number(itemForm.qty), scrap_pct: Number(itemForm.scrap_pct || 0),
        });
      }
      setItemForm(emptyItemForm());
      setEditingItemId(null);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to save item");
    } finally {
      setSaving(false);
    }
  }

  function startEditItem(item: NonNullable<Bom["items"]>[number]) {
    setEditingItemId(item.id);
    const dimsStr: Record<string, string> = {};
    for (const [k, v] of Object.entries(item.dims)) dimsStr[k] = String(v);
    setItemForm({
      description: item.description, material_id: item.material_id, shape: item.shape,
      dims: dimsStr, qty: String(item.qty), scrap_pct: String(item.scrap_pct),
    });
  }

  async function handleDeleteItem(itemId: string) {
    setError(null);
    try {
      await deleteBomItem(params.id, itemId);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to delete item");
    }
  }

  async function handleRelease() {
    setError(null);
    try {
      await releaseBom(params.id);
      load();
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to release BOM");
    }
  }

  async function handleRevise() {
    setSaving(true);
    setError(null);
    try {
      const nb = await reviseBom(params.id, { new_revision: reviseRev, copy_items: true });
      window.location.href = `/boms/${nb.id}`;
    } catch (e) {
      setError(e instanceof ErpApiError ? e.message : "failed to revise BOM");
      setSaving(false);
    }
  }

  if (loading) return <p className="text-sm text-mist">Loading...</p>;
  if (error && !bom) return <p className="rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>;
  if (!bom) return null;

  const items = bom.items ?? [];
  const totalWeight = items.reduce((s, i) => s + (i.total_weight_kg ?? 0), 0);
  const totalCost = items.reduce((s, i) => s + (i.cost ?? 0), 0);

  return (
    <div>
      <Link href="/boms" className="mb-4 inline-block text-sm text-copper hover:underline">&larr; Back to BOMs</Link>

      <div className="mb-6 flex items-start justify-between rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
        <div>
          <h1 className="font-display text-2xl font-light text-fg">{bom.name} <span className="font-mono text-sm font-normal text-mist">rev {bom.revision}</span></h1>
          {bom.supersedes_bom_id && (
            <p className="text-xs text-mist">
              Supersedes <Link href={`/boms/${bom.supersedes_bom_id}`} className="text-copper hover:underline">a previous released BOM</Link>
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <BomStatusBadge status={bom.status} />
          {bom.status === "draft" && items.length > 0 && (
            <button onClick={handleRelease} className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">Release</button>
          )}
          {bom.status === "released" && !showRevise && (
            <button onClick={() => { setShowRevise(true); setReviseRev(""); }} className="rounded-lg bg-rust px-3 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper">Revise</button>
          )}
          {showRevise && (
            <div className="flex items-center gap-2">
              <input value={reviseRev} onChange={(e) => setReviseRev(e.target.value)} placeholder="new revision e.g. B" className="w-32 rounded-lg border border-line bg-transparent px-2 py-1 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
              <button onClick={handleRevise} disabled={saving || !reviseRev} className="rounded-lg bg-rust px-3 py-1.5 text-sm text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">Confirm</button>
            </div>
          )}
        </div>
      </div>

      {error && <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">{error}</p>}
      {readOnly && (
        <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">
          This BOM is released and immutable. Use &quot;Revise&quot; above for your own direct revision, or file a
          formal change request below if the change needs someone else&apos;s sign-off.
        </p>
      )}

      <ChangeRequestsPanel bomId={params.id} bomStatus={bom.status} onRevised={load} />

      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-2">
        <StatTile label="Total weight" value={totalWeight.toFixed(2)} unit="kg" />
        <StatTile label="Total cost" value={totalCost.toFixed(2)} unit="₹" unitPrefix />
      </div>

      <div className="mb-4 overflow-x-auto rounded-2xl border border-hair bg-panel" style={{ boxShadow: "var(--shadow-sm)" }}>
        <table className="w-full text-left text-sm">
          <thead className="font-mono text-xs tracking-[0.1em] text-mist uppercase">
            <tr>
              <th className="px-3 py-2">Description</th><th className="px-3 py-2">Material</th><th className="px-3 py-2">Shape</th>
              <th className="px-3 py-2">Qty</th><th className="px-3 py-2">Unit wt (kg)</th><th className="px-3 py-2">Total wt (kg)</th>
              <th className="px-3 py-2">Cost</th><th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={8} className="px-3 py-4 text-center text-mist">No items yet.</td></tr>}
            {items.map((it) => (
              <tr key={it.id} className="border-t border-hair hover:bg-midnight">
                <td className="px-3 py-2 text-fg">{it.description}</td>
                <td className="px-3 py-2 text-mist">{materials.find((m) => m.id === it.material_id)?.name ?? it.material_id}</td>
                <td className="px-3 py-2 text-mist capitalize">{it.shape}</td>
                <td className="px-3 py-2 font-mono text-mist">{it.qty}</td>
                <td className="px-3 py-2 font-mono text-mist">{it.unit_weight_kg?.toFixed(3) ?? "-"}</td>
                <td className="px-3 py-2 font-mono font-medium text-fg">{it.total_weight_kg?.toFixed(3) ?? "-"}</td>
                <td className="px-3 py-2 font-mono font-medium text-fg">₹{it.cost?.toFixed(2) ?? "-"}</td>
                <td className="space-x-2 px-3 py-2 text-right whitespace-nowrap">
                  {!readOnly && (
                    <>
                      <button onClick={() => startEditItem(it)} className="text-copper hover:underline">Edit</button>
                      <button onClick={() => handleDeleteItem(it.id)} className="text-rust hover:underline">Delete</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!readOnly && (
        <form onSubmit={handleAddItem} className="rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
          <h3 className="mb-3 text-sm font-semibold text-fg">{editingItemId ? "Edit item" : "Add item"}</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <label className="block text-sm sm:col-span-2">
              <span className="mb-1 block font-medium text-fg">Description *</span>
              <input required value={itemForm.description} onChange={(e) => setItemForm({ ...itemForm, description: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-fg">Material *</span>
              <select required value={itemForm.material_id} onChange={(e) => setItemForm({ ...itemForm, material_id: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
                <option value="" className="bg-panel">-- select --</option>
                {materials.map((m) => <option key={m.id} value={m.id} className="bg-panel">{m.name} {m.grade ? `(${m.grade})` : ""}</option>)}
              </select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-fg">Shape *</span>
              <select value={itemForm.shape} onChange={(e) => setItemForm({ ...itemForm, shape: e.target.value as BomShape, dims: {} })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg focus:border-copper focus:outline-none">
                <option value="plate" className="bg-panel">Plate (L x W x T mm)</option>
                <option value="rod" className="bg-panel">Rod (diameter x L mm)</option>
                <option value="pipe" className="bg-panel">Pipe (OD x wall x L mm)</option>
                <option value="custom" className="bg-panel">Custom (direct unit weight)</option>
              </select>
            </label>

            <DimsForm form={itemForm} setForm={setItemForm} />

            <label className="block text-sm">
              <span className="mb-1 block font-medium text-fg">Qty</span>
              <input type="number" step="any" value={itemForm.qty} onChange={(e) => setItemForm({ ...itemForm, qty: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
            </label>
            {itemForm.shape !== "custom" && (
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-fg">Scrap %</span>
                <input type="number" step="any" value={itemForm.scrap_pct} onChange={(e) => setItemForm({ ...itemForm, scrap_pct: e.target.value })} className="w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none" />
              </label>
            )}
          </div>

          <WeightPreviewTile preview={preview} previewError={previewError} />

          <div className="mt-3 flex gap-2">
            <button type="submit" disabled={saving} className="rounded-lg bg-rust px-4 py-2 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50">
              {saving ? "Saving..." : editingItemId ? "Save item" : "Add item"}
            </button>
            {editingItemId && (
              <button type="button" onClick={() => { setEditingItemId(null); setItemForm(emptyItemForm()); }} className="rounded-lg border border-line px-4 py-2 text-sm text-mist">
                Cancel edit
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

// Stat-tile pattern mirrored from SensorTile.tsx, adapted for BOM
// weight/cost fields. Procurement/financial data = copper category
// per DESIGN.md's categorical color-coding.
function StatTile({ label, value, unit, unitPrefix }: { label: string; value: string; unit: string; unitPrefix?: boolean }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-hair bg-panel p-4" style={{ boxShadow: "var(--shadow-sm)" }}>
      <div className="absolute inset-x-0 top-0 h-[2px]" style={{ background: "oklch(0.72 0.15 54 / 0.55)" }} aria-hidden />
      <span className="flex items-center gap-1.5 font-mono text-xs tracking-[0.08em] text-mist uppercase">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-copper" aria-hidden />
        {label}
      </span>
      <p className="mt-2 font-mono text-2xl font-medium text-fg tabular-nums transition-colors duration-150">
        {unitPrefix ? `${unit}${value}` : (
          <>
            {value} <span className="text-sm font-normal text-mist">{unit}</span>
          </>
        )}
      </p>
    </div>
  );
}

// Live server-computed preview, restyled as the same stat-tile moment -
// copper top edge, mono uppercase label, mono values. Purely
// presentational: no new client-side calculation, values come straight
// from the existing weightPreview() API response.
function WeightPreviewTile({ preview, previewError }: { preview: WeightPreviewT | null; previewError: string | null }) {
  return (
    <div className="relative mt-3 overflow-hidden rounded-2xl border border-hair bg-midnight p-3" style={{ boxShadow: "var(--shadow-sm)" }}>
      <div className="absolute inset-x-0 top-0 h-[2px]" style={{ background: "oklch(0.72 0.15 54 / 0.55)" }} aria-hidden />
      <span className="flex items-center gap-1.5 font-mono text-xs tracking-[0.08em] text-mist uppercase">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-copper" aria-hidden />
        Live preview (server-computed)
      </span>
      <div className="mt-1.5 text-sm">
        {previewError ? (
          <span className="text-rust">{previewError}</span>
        ) : preview ? (
          <span className="font-mono text-fg transition-colors duration-150 tabular-nums">
            unit {preview.unit_weight_kg.toFixed(3)} kg &middot; total {preview.total_weight_kg.toFixed(3)} kg &middot; cost ₹{preview.cost.toFixed(2)}
          </span>
        ) : (
          <span className="text-mist">fill in material + all dimensions to preview</span>
        )}
      </div>
    </div>
  );
}

function BomStatusBadge({ status }: { status: string }) {
  if (status === "released") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-moss/15 px-2 py-0.5 text-xs font-medium text-moss">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-moss" aria-hidden />
        Released
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-midnight px-2 py-0.5 text-xs font-medium text-mist">
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-mist" aria-hidden />
      Draft
    </span>
  );
}
