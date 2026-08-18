// ERP-specific types. Mirror the row shapes returned by api/routers/erp_*.py,
// genealogy.py, production.py, logistics.py. Kept separate from lib/types.ts
// (shared/owned by the scaffold) per this phase's file-ownership rules.

export interface Vendor {
  id: string;
  name: string;
  gstin: string | null;
  address: string | null;
  state_code: string | null;
  contact: string | null;
  phone: string | null;
  email: string | null;
  category: string | null;
  rating: number | null;
  notes: string | null;
}

export interface Material {
  id: string;
  name: string;
  grade: string | null;
  density_kg_m3: number | null;
  rate_per_kg: number | null;
  hsn: string | null;
}

export interface HardwareComponent {
  id: string;
  category: string;
  category_order: number;
  sort_order: number;
  item: string;
  spec_function: string | null;
  tag_id: string | null;
  tier: number | null;
  segment: string | null;
  cost_inr: number | null;
}

export interface QuotationLine {
  id: string;
  quotation_id: string;
  description: string;
  qty: number;
  unit: string;
  rate: number;
}

export interface Quotation {
  id: string;
  direction: "vendor" | "customer";
  party_id: string;
  project_id: string | null;
  ref_no: string | null;
  date: string | null;
  valid_till: string | null;
  file_url: string | null;
  sha256: string | null;
  status: string;
  lines?: QuotationLine[];
}

export interface Project {
  id: string;
  code: string;
  name: string;
  client: string | null;
  status: string;
  quotation_id: string | null;
}

export interface Task {
  id: string;
  project_id: string | null;
  title: string;
  assignee: string | null;
  due: string | null;
  status: string;
  blocked_by_po_id: string | null;
}

export type DrawingStatus = "draft" | "for_review" | "released" | "superseded";

export interface Drawing {
  id: string;
  project_id: string;
  dwg_no: string;
  title: string | null;
  revision: string | null;
  file_url: string | null;
  sha256: string | null;
  status: DrawingStatus;
  released_by: string | null;
  released_at: string | null;
}

export type BomShape = "plate" | "rod" | "pipe" | "custom";

export interface BomItem {
  id: string;
  bom_id: string;
  description: string;
  material_id: string;
  shape: BomShape;
  dims: Record<string, number>;
  qty: number;
  scrap_pct: number;
  unit_weight_kg: number | null;
  total_weight_kg: number | null;
  cost: number | null;
}

export interface Bom {
  id: string;
  project_id: string;
  drawing_id: string | null;
  name: string;
  revision: string | null;
  status: "draft" | "released";
  supersedes_bom_id: string | null;
  items?: BomItem[];
}

export interface BomChangeRequest {
  id: string;
  bom_id: string;
  reason: string;
  affected_note: string | null;
  requested_new_revision: string;
  status: "pending" | "approved" | "rejected";
  requested_by: string | null;
  requested_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  resulting_bom_id: string | null;
}

export interface WeightPreview {
  unit_weight_kg: number;
  total_weight_kg: number;
  cost: number;
}

export interface PoItem {
  id: string;
  po_id: string;
  bom_item_id: string | null;
  description: string;
  hsn: string | null;
  qty: number;
  unit: string;
  rate: number;
  gst_rate: number;
  received_qty: number;
}

export interface PoLine extends PoItem {
  taxable: number;
  cgst: number;
  sgst: number;
  igst: number;
  total_gst: number;
  line_total: number;
}

export interface PoTotals {
  taxable: number;
  cgst: number;
  sgst: number;
  igst: number;
  freight: number;
  grand_total: number;
  vendor_state_code: string | null;
  company_state_code: string;
  tax_regime: string;
}

export interface Po {
  id: string;
  po_no: string;
  vendor_id: string;
  po_date: string;
  delivery_address: string | null;
  payment_terms: string | null;
  delivery_terms: string | null;
  freight: number | null;
  notes: string | null;
  status: string;
  items?: PoLine[];
  totals?: PoTotals;
  amount_in_words?: string;
}

export interface GrnLine {
  id: string;
  grn_id: string;
  po_item_id: string;
  qty_received: number;
  qty_accepted: number;
  qty_rejected: number;
}

export interface Grn {
  id: string;
  po_id: string;
  grn_no: string;
  date: string;
  received_by: string | null;
  vehicle_no: string | null;
  eway_bill_no: string | null;
  notes: string | null;
  lines?: GrnLine[];
  po_status?: string;
}

export interface VendorInvoice {
  id: string;
  vendor_id: string;
  po_id: string | null;
  inv_no: string;
  date: string | null;
  taxable: number;
  gst: number;
  total: number;
  file_url: string | null;
  sha256: string | null;
  status: string;
}

export interface MatchCheck {
  ok: boolean;
  invoice: string;
  po_expected?: string;
  tolerance_pct?: string;
  ordered_qty?: string;
  grn_accepted_qty?: string;
}

export interface MatchResult {
  ok: boolean;
  reason: string | null;
  checks: Record<string, MatchCheck>;
}

export interface InventoryLot {
  lot_id: string;
  grn_line_id: string | null;
  material_id: string;
  qty_on_hand: number;
  unit: string;
  location: string | null;
  heat_no: string | null;
  mtc_url: string | null;
  sha256: string | null;
}

export interface GenealogyResponse {
  lot: {
    lot_id: string;
    material_id: string;
    material_name: string;
    qty_on_hand: number;
    unit: string;
    location: string | null;
    heat_no: string | null;
    mtc_url: string | null;
    sha256: string | null;
    grn_line_id: string | null;
    grn_id: string | null;
    po_item_id: string | null;
    qty_received: number | null;
    qty_accepted: number | null;
    qty_rejected: number | null;
    grn_no: string | null;
    grn_date: string | null;
    vehicle_no: string | null;
    eway_bill_no: string | null;
    po_id: string | null;
    po_no: string | null;
    po_date: string | null;
    po_status: string | null;
    vendor_id: string | null;
    vendor_name: string | null;
    vendor_gstin: string | null;
  };
  qc_records: {
    id: string;
    lot_id: string;
    job_id: string | null;
    unit_serial: string | null;
    type: string;
    result: string | null;
    inspector: string | null;
    ts: string;
    report_url: string | null;
    sha256: string | null;
  }[];
  issue_lines: {
    id: string;
    lot_id: string;
    qty: number;
    fabrication_job_id: string | null;
    issued_at: string;
    issued_by: string | null;
  }[];
  fabrication_jobs: FabricationJob[];
  unit_serials: UnitSerial[];
  installations: {
    id: string;
    serial: string;
    plant_id: string;
    installed_at: string | null;
    commissioned_at: string | null;
  }[];
}

export type FabricationJobStatus = "planned" | "in_progress" | "on_hold" | "completed" | "cancelled";

export interface FabricationJob {
  id: string;
  project_id: string;
  bom_id: string | null;
  unit_serial: string | null;
  status: FabricationJobStatus;
  started: string | null;
  finished: string | null;
}

export type UnitSerialStatus = "fabrication" | "qc" | "dispatched" | "installed";

export interface UnitSerial {
  serial: string;
  model: string | null;
  project_id: string | null;
  status: UnitSerialStatus;
}

export interface QcRecord {
  id: string;
  lot_id: string | null;
  job_id: string | null;
  unit_serial: string | null;
  type: "incoming" | "in_process" | "final";
  result: string | null;
  inspector: string | null;
  ts: string;
  report_url: string | null;
  sha256: string | null;
}

export interface Trip {
  id: string;
  vehicle_no: string;
  driver: string | null;
  phone: string | null;
  purpose: "koh_delivery" | "k2so3_pickup" | "dispatch";
  origin: string | null;
  dest_plant_id: string | null;
  eway_bill_no: string | null;
  status: string;
  started: string | null;
  completed: string | null;
  token?: string;
}
