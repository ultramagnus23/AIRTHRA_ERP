"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  addBomItem, deleteBomItem, getBom, listMaterials, releaseBom, reviseBom, updateBomItem, weightPreview, ErpApiError,
} from "@/lib/erp/api";
import type { Bom, BomShape, Material, WeightPreview as WeightPreviewT } from "@/lib/erp/types";

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
          <span className="mb-1 block font-medium text-slate-700">{f.label}</span>
          <input
            type="number"
            step="any"
            value={form.dims[f.key] ?? ""}
            onChange={(e) => setForm({ ...form, dims: { ...form.dims, [f.key]: e.target.value } })}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
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

  if (loading) return <p className="text-sm text-slate-500">Loading...</p>;
  if (error && !bom) return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>;
  if (!bom) return null;

  const items = bom.items ?? [];
  const totalWeight = items.reduce((s, i) => s + (i.total_weight_kg ?? 0), 0);
  const totalCost = items.reduce((s, i) => s + (i.cost ?? 0), 0);

  return (
    <div>
      <Link href="/boms" className="mb-4 inline-block text-sm text-teal-700 hover:underline">&larr; Back to BOMs</Link>

      <div className="mb-6 flex items-start justify-between rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{bom.name} <span className="font-mono text-sm font-normal text-slate-500">rev {bom.revision}</span></h1>
          {bom.supersedes_bom_id && (
            <p className="text-xs text-slate-500">
              Supersedes <Link href={`/boms/${bom.supersedes_bom_id}`} className="text-teal-700 hover:underline">a previous released BOM</Link>
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${bom.status === "released" ? "bg-green-100 text-green-800" : "bg-slate-100 text-slate-700"}`}>{bom.status}</span>
          {bom.status === "draft" && items.length > 0 && (
            <button onClick={handleRelease} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">Release</button>
          )}
          {bom.status === "released" && !showRevise && (
            <button onClick={() => { setShowRevise(true); setReviseRev(""); }} className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white hover:bg-teal-800">Revise</button>
          )}
          {showRevise && (
            <div className="flex items-center gap-2">
              <input value={reviseRev} onChange={(e) => setReviseRev(e.target.value)} placeholder="new revision e.g. B" className="w-32 rounded border border-slate-300 px-2 py-1 text-sm" />
              <button onClick={handleRevise} disabled={saving || !reviseRev} className="rounded bg-teal-700 px-3 py-1.5 text-sm text-white disabled:opacity-50">Confirm</button>
            </div>
          )}
        </div>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {readOnly && (
        <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
          This BOM is released and immutable. Use &quot;Revise&quot; above to create a new draft revision before editing items.
        </p>
      )}

      <div className="mb-4 grid grid-cols-2 gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Total weight</p>
          <p className="text-2xl font-semibold text-slate-900">{totalWeight.toFixed(2)} kg</p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Total cost</p>
          <p className="text-2xl font-semibold text-slate-900">₹{totalCost.toFixed(2)}</p>
        </div>
      </div>

      <div className="mb-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Description</th><th className="px-3 py-2">Material</th><th className="px-3 py-2">Shape</th>
              <th className="px-3 py-2">Qty</th><th className="px-3 py-2">Unit wt (kg)</th><th className="px-3 py-2">Total wt (kg)</th>
              <th className="px-3 py-2">Cost</th><th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={8} className="px-3 py-4 text-center text-slate-400">No items yet.</td></tr>}
            {items.map((it) => (
              <tr key={it.id} className="border-t border-slate-100">
                <td className="px-3 py-2">{it.description}</td>
                <td className="px-3 py-2 text-slate-600">{materials.find((m) => m.id === it.material_id)?.name ?? it.material_id}</td>
                <td className="px-3 py-2 capitalize text-slate-600">{it.shape}</td>
                <td className="px-3 py-2">{it.qty}</td>
                <td className="px-3 py-2">{it.unit_weight_kg?.toFixed(3) ?? "-"}</td>
                <td className="px-3 py-2 font-medium">{it.total_weight_kg?.toFixed(3) ?? "-"}</td>
                <td className="px-3 py-2 font-medium">₹{it.cost?.toFixed(2) ?? "-"}</td>
                <td className="space-x-2 px-3 py-2 whitespace-nowrap text-right">
                  {!readOnly && (
                    <>
                      <button onClick={() => startEditItem(it)} className="text-teal-700 hover:underline">Edit</button>
                      <button onClick={() => handleDeleteItem(it.id)} className="text-red-600 hover:underline">Delete</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!readOnly && (
        <form onSubmit={handleAddItem} className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-900">{editingItemId ? "Edit item" : "Add item"}</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <label className="block text-sm sm:col-span-2">
              <span className="mb-1 block font-medium text-slate-700">Description *</span>
              <input required value={itemForm.description} onChange={(e) => setItemForm({ ...itemForm, description: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Material *</span>
              <select required value={itemForm.material_id} onChange={(e) => setItemForm({ ...itemForm, material_id: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
                <option value="">-- select --</option>
                {materials.map((m) => <option key={m.id} value={m.id}>{m.name} {m.grade ? `(${m.grade})` : ""}</option>)}
              </select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Shape *</span>
              <select value={itemForm.shape} onChange={(e) => setItemForm({ ...itemForm, shape: e.target.value as BomShape, dims: {} })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm">
                <option value="plate">Plate (L x W x T mm)</option>
                <option value="rod">Rod (diameter x L mm)</option>
                <option value="pipe">Pipe (OD x wall x L mm)</option>
                <option value="custom">Custom (direct unit weight)</option>
              </select>
            </label>

            <DimsForm form={itemForm} setForm={setItemForm} />

            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-700">Qty</span>
              <input type="number" step="any" value={itemForm.qty} onChange={(e) => setItemForm({ ...itemForm, qty: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
            </label>
            {itemForm.shape !== "custom" && (
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-slate-700">Scrap %</span>
                <input type="number" step="any" value={itemForm.scrap_pct} onChange={(e) => setItemForm({ ...itemForm, scrap_pct: e.target.value })} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
              </label>
            )}
          </div>

          <div className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-sm">
            <span className="font-medium text-slate-700">Live preview (server-computed): </span>
            {previewError ? (
              <span className="text-red-600">{previewError}</span>
            ) : preview ? (
              <span className="text-slate-800">
                unit {preview.unit_weight_kg.toFixed(3)} kg &middot; total {preview.total_weight_kg.toFixed(3)} kg &middot; cost ₹{preview.cost.toFixed(2)}
              </span>
            ) : (
              <span className="text-slate-400">fill in material + all dimensions to preview</span>
            )}
          </div>

          <div className="mt-3 flex gap-2">
            <button type="submit" disabled={saving} className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
              {saving ? "Saving..." : editingItemId ? "Save item" : "Add item"}
            </button>
            {editingItemId && (
              <button type="button" onClick={() => { setEditingItemId(null); setItemForm(emptyItemForm()); }} className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-600">
                Cancel edit
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
