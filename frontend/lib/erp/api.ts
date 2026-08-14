// ERP-specific API client. Mirrors lib/api.ts's `request()` pattern (same
// /api/backend proxy, same httpOnly-cookie auth) but kept as a separate
// file since lib/api.ts is scaffold-owned and off-limits for this phase.
//
// Global rule (per the scaffold): NEVER compute business logic here or in a
// component - GST split, BOM weight/cost, PO numbering, amount-in-words,
// 3-way match are all computed server-side. This file fetches/mutates only.
import type {
  Bom,
  BomItem,
  BomShape,
  Drawing,
  FabricationJob,
  FabricationJobStatus,
  GenealogyResponse,
  Grn,
  InventoryLot,
  MatchResult,
  Material,
  Po,
  Project,
  QcRecord,
  Quotation,
  Task,
  Trip,
  UnitSerial,
  Vendor,
  VendorInvoice,
  WeightPreview,
} from "./types";

export class ErpApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/backend${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body;
    } catch {
      /* non-JSON error body */
    }
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new ErpApiError(res.status, message, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const get = <T>(path: string) => req<T>(path);
const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
const patch = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined });
const del = (path: string) => req<void>(path, { method: "DELETE" });

// --- Vendors -----------------------------------------------------------
export const listVendors = () => get<Vendor[]>("/erp/vendors");
export const getVendor = (id: string) => get<Vendor>(`/erp/vendors/${id}`);
export const createVendor = (body: Partial<Vendor>) => post<Vendor>("/erp/vendors", body);
export const updateVendor = (id: string, body: Partial<Vendor>) => patch<Vendor>(`/erp/vendors/${id}`, body);

// --- Materials -----------------------------------------------------------
export const listMaterials = () => get<Material[]>("/erp/materials");
export const getMaterial = (id: string) => get<Material>(`/erp/materials/${id}`);
export const createMaterial = (body: Partial<Material>) => post<Material>("/erp/materials", body);
export const updateMaterial = (id: string, body: Partial<Material>) => patch<Material>(`/erp/materials/${id}`, body);

// --- Quotations ------------------------------------------------------------
export const listQuotations = () => get<Quotation[]>("/erp/quotations");
export const getQuotation = (id: string) => get<Quotation>(`/erp/quotations/${id}`);
export const createQuotation = (body: {
  direction: "vendor" | "customer";
  party_id: string;
  project_id?: string | null;
  ref_no?: string | null;
  date?: string | null;
  valid_till?: string | null;
  status?: string;
}) => post<Quotation>("/erp/quotations", body);
export const updateQuotation = (id: string, body: Partial<Quotation>) => patch<Quotation>(`/erp/quotations/${id}`, body);
export const addQuotationLine = (
  id: string,
  body: { description: string; qty: number; unit: string; rate: number },
) => post(`/erp/quotations/${id}/lines`, body);
export const deleteQuotationLine = (id: string, lineId: string) => del(`/erp/quotations/${id}/lines/${lineId}`);

// --- Projects / tasks --------------------------------------------------
export const listProjects = () => get<Project[]>("/erp/projects");
export const getProject = (id: string) => get<Project>(`/erp/projects/${id}`);
export const createProject = (body: { code: string; name: string; client?: string | null; status?: string; quotation_id?: string | null }) =>
  post<Project>("/erp/projects", body);
export const updateProject = (id: string, body: Partial<Project>) => patch<Project>(`/erp/projects/${id}`, body);

export const listTasks = (projectId?: string) => get<Task[]>(`/erp/tasks${projectId ? `?project_id=${projectId}` : ""}`);
export const createTask = (body: {
  project_id?: string | null;
  title: string;
  assignee?: string | null;
  due?: string | null;
  status?: string;
  blocked_by_po_id?: string | null;
}) => post<Task>("/erp/tasks", body);
export const updateTask = (id: string, body: Partial<Task>) => patch<Task>(`/erp/tasks/${id}`, body);

// --- Drawings ------------------------------------------------------------
export const listDrawings = () => get<Drawing[]>("/erp/drawings");
export const getDrawing = (id: string) => get<Drawing>(`/erp/drawings/${id}`);
export const createDrawing = (body: { project_id: string; dwg_no: string; title?: string | null; revision?: string | null }) =>
  post<Drawing>("/erp/drawings", body);
export const updateDrawing = (id: string, body: Partial<Drawing>) => patch<Drawing>(`/erp/drawings/${id}`, body);
export const releaseDrawing = (id: string) => post<Drawing>(`/erp/drawings/${id}/release`);
export const reviseDrawing = (id: string, body: { new_revision: string; title?: string | null }) =>
  post<Drawing>(`/erp/drawings/${id}/revise`, body);

// --- BOMs ------------------------------------------------------------------
export const listBoms = () => get<Bom[]>("/erp/boms");
export const getBom = (id: string) => get<Bom>(`/erp/boms/${id}`);
export const createBom = (body: { project_id: string; drawing_id?: string | null; name: string; revision?: string | null }) =>
  post<Bom>("/erp/boms", body);
export const updateBom = (id: string, body: Partial<Bom>) => patch<Bom>(`/erp/boms/${id}`, body);
export const weightPreview = (body: {
  material_id: string;
  shape: BomShape;
  dims: Record<string, number>;
  qty: number;
  scrap_pct: number;
}) => post<WeightPreview>("/erp/boms/weight-preview", body);
export const addBomItem = (
  bomId: string,
  body: { description: string; material_id: string; shape: BomShape; dims: Record<string, number>; qty: number; scrap_pct: number },
) => post<BomItem>(`/erp/boms/${bomId}/items`, body);
export const updateBomItem = (bomId: string, itemId: string, body: Partial<BomItem>) =>
  patch<BomItem>(`/erp/boms/${bomId}/items/${itemId}`, body);
export const deleteBomItem = (bomId: string, itemId: string) => del(`/erp/boms/${bomId}/items/${itemId}`);
export const releaseBom = (id: string) => post<Bom>(`/erp/boms/${id}/release`);
export const reviseBom = (id: string, body: { new_revision: string; name?: string | null; copy_items?: boolean }) =>
  post<Bom>(`/erp/boms/${id}/revise`, body);

// --- POs ---------------------------------------------------------------
export const listPos = () => get<Po[]>("/erp/pos");
export const getPo = (id: string) => get<Po>(`/erp/pos/${id}`);
export const createPo = (body: {
  vendor_id: string;
  po_date?: string | null;
  delivery_address?: string | null;
  payment_terms?: string | null;
  delivery_terms?: string | null;
  freight?: number | null;
  notes?: string | null;
  items: { bom_item_id?: string | null; description: string; hsn?: string | null; qty: number; unit: string; rate: number; gst_rate?: number }[];
}) => post<Po>("/erp/pos", body);
export const createPoFromBom = (body: {
  bom_id: string;
  vendor_id: string;
  po_date?: string | null;
  delivery_address?: string | null;
  payment_terms?: string | null;
  delivery_terms?: string | null;
  freight?: number | null;
  notes?: string | null;
  default_gst_rate?: number;
}) => post<Po>("/erp/pos/from-bom", body);
export const updatePo = (id: string, body: Partial<Po>) => patch<Po>(`/erp/pos/${id}`, body);
export const addPoItem = (
  id: string,
  body: { bom_item_id?: string | null; description: string; hsn?: string | null; qty: number; unit: string; rate: number; gst_rate?: number },
) => post(`/erp/pos/${id}/items`, body);
export const issuePo = (id: string) => post<Po>(`/erp/pos/${id}/issue`);
export const getPoPdf = (id: string) => get<{ po_id: string; po_no: string; url: string; sha256: string; bytes: number }>(`/erp/pos/${id}/pdf`);

// --- GRN -----------------------------------------------------------------
export const listGrn = (poId?: string) => get<Grn[]>(`/erp/grn${poId ? `?po_id=${poId}` : ""}`);
export const getGrn = (id: string) => get<Grn>(`/erp/grn/${id}`);
export const createGrn = (body: {
  po_id: string;
  grn_no: string;
  vehicle_no?: string | null;
  eway_bill_no?: string | null;
  notes?: string | null;
  lines: { po_item_id: string; qty_received: number; qty_accepted: number; qty_rejected?: number }[];
}) => post<Grn>("/erp/grn", body);

// --- Vendor invoices -----------------------------------------------------
export const listInvoices = () => get<VendorInvoice[]>("/erp/vendor-invoices");
export const getInvoice = (id: string) => get<VendorInvoice>(`/erp/vendor-invoices/${id}`);
export const createInvoice = (body: {
  vendor_id: string;
  po_id?: string | null;
  inv_no: string;
  date?: string | null;
  taxable: number;
  gst: number;
  total: number;
}) => post<VendorInvoice>("/erp/vendor-invoices", body);
export const checkThreeWayMatch = (id: string) => post<MatchResult>(`/erp/vendor-invoices/${id}/check`);
export const approveInvoice = (id: string) => post<VendorInvoice>(`/erp/vendor-invoices/${id}/approve`);

// --- Inventory / genealogy -------------------------------------------------
export const listInventoryLots = (materialId?: string) =>
  get<{ lots: InventoryLot[] }>(`/erp/inventory-lots${materialId ? `?material_id=${materialId}` : ""}`);
export const createInventoryLot = (body: {
  grn_line_id?: string | null;
  material_id: string;
  qty_on_hand: number;
  unit: string;
  location?: string | null;
  heat_no?: string | null;
}) => post<InventoryLot>("/erp/inventory-lots", body);
export const getInventoryLot = (id: string) => get<InventoryLot>(`/erp/inventory-lots/${id}`);
export const getLotGenealogy = (lotId: string) => get<GenealogyResponse>(`/erp/genealogy/lot/${lotId}`);
export const vendorRecall = (vendorId: string, start: string, end: string) =>
  get(`/erp/genealogy/vendor-recall?vendor_id=${vendorId}&start=${start}&end=${end}`);

// --- Fabrication jobs / unit serials --------------------------------------
export const listFabricationJobs = (params?: { project_id?: string; status?: string }) => {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set("project_id", params.project_id);
  if (params?.status) qs.set("status", params.status);
  const s = qs.toString();
  return get<{ jobs: FabricationJob[] }>(`/erp/fabrication-jobs${s ? `?${s}` : ""}`);
};
export const createFabricationJob = (body: { project_id: string; bom_id?: string | null; unit_serial?: string | null }) =>
  post<FabricationJob>("/erp/fabrication-jobs", body);
export const updateFabricationJobStatus = (id: string, status: FabricationJobStatus) =>
  patch<FabricationJob>(`/erp/fabrication-jobs/${id}/status`, { status });

export const listUnitSerials = (projectId?: string) =>
  get<{ unit_serials: UnitSerial[] }>(`/erp/unit-serials${projectId ? `?project_id=${projectId}` : ""}`);
export const createUnitSerial = (body: { serial: string; model?: string | null; project_id?: string | null }) =>
  post<UnitSerial>("/erp/unit-serials", body);

// --- QC records ------------------------------------------------------------
export const createQcRecord = (body: {
  lot_id?: string | null;
  job_id?: string | null;
  unit_serial?: string | null;
  type: "incoming" | "in_process" | "final";
  result?: string | null;
  inspector?: string | null;
}) => post<QcRecord>("/erp/qc-records", body);

// --- Logistics / dispatch --------------------------------------------------
export const listTrips = (params?: { status?: string; dest_plant_id?: string }) => {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.dest_plant_id) qs.set("dest_plant_id", params.dest_plant_id);
  const s = qs.toString();
  return get<{ trips: Trip[] }>(`/logistics/trips${s ? `?${s}` : ""}`);
};
export const createTrip = (body: {
  vehicle_no: string;
  driver?: string | null;
  phone?: string | null;
  purpose: "koh_delivery" | "k2so3_pickup" | "dispatch";
  origin?: string | null;
  dest_plant_id?: string | null;
  eway_bill_no?: string | null;
}) => post<Trip>("/logistics/trips", body);
