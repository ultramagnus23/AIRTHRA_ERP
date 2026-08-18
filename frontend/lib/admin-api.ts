// Typed client-side API wrapper for the (admin) route group only.
//
// Deliberately a sibling of lib/api.ts rather than an edit to it - that
// file is shared/owned by the scaffold (client dashboard + whatever ERP
// helpers land there) and off-limits per the admin-console build brief.
// Same underlying pattern though: every call hits Next.js's own
// /api/backend/* proxy (app/api/backend/[...path]/route.ts, untouched)
// so the browser only needs the same-origin httpOnly cookie.
//
// Same global rule as lib/api.ts: NEVER compute risk weights, KPIs,
// burn-rate trends, or any other derived number here or in a component -
// every number the admin console shows is already computed server-side
// by api/routers/admin_*.py; this file only fetches and the components
// only render.
import type {
  AdminAlarmsResponse,
  AdminPlantsResponse,
  AdminUsersResponse,
  AuditLogResponse,
  BatchesResponse,
  BurnRatesResponse,
  Buyer,
  BuyersResponse,
  Contract,
  ContractsResponse,
  CreateBatchInput,
  CreateBuyerInput,
  CreateContractInput,
  CreateLeadInput,
  CreatePlantInput,
  CreateUserInput,
  CreateUserResult,
  DocumentEntityType,
  DocumentRecord,
  DocumentsResponse,
  FleetResponse,
  InvoicesResponse,
  Invoice,
  Lead,
  LeadsResponse,
  LeadStage,
  MetricsResponse,
  MrvExportResponse,
  PatchUserInput,
  PatchUserResult,
  ProductBatch,
  RiskScoresResponse,
} from "./admin-types";

export class AdminApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/backend${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    throw new AdminApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function getFleet() {
  return request<FleetResponse>("/admin/fleet");
}

export function getTriageAlarms(state: string = "raised") {
  const qs = state ? `?state=${encodeURIComponent(state)}` : "";
  return request<AdminAlarmsResponse>(`/admin/alarms${qs}`);
}

export function getMetrics(params: {
  metric: string;
  group_by?: string;
  period?: string;
  source?: string;
}) {
  const qs = new URLSearchParams({ metric: params.metric });
  qs.set("group_by", params.group_by ?? "plant_id");
  qs.set("period", params.period ?? "24h");
  if (params.source) qs.set("source", params.source);
  return request<MetricsResponse>(`/admin/metrics?${qs.toString()}`);
}

export function getBurnRates() {
  return request<BurnRatesResponse>("/admin/logistics/burn_rates");
}

export function getRiskScores(periodDays: number = 30) {
  return request<RiskScoresResponse>(`/admin/risk_scores?period_days=${periodDays}`);
}

export function getInvoices(params?: { plant_id?: string; period?: string; status?: string }) {
  const qs = new URLSearchParams();
  if (params?.plant_id) qs.set("plant_id", params.plant_id);
  if (params?.period) qs.set("period", params.period);
  if (params?.status) qs.set("status", params.status);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<InvoicesResponse>(`/admin/invoices${suffix}`);
}

export function approveInvoice(invoiceId: string) {
  return request<Invoice>(`/admin/invoices/${invoiceId}/approve`, { method: "POST" });
}

export function exportMrv(plantId: string, period: string) {
  return request<MrvExportResponse>(
    `/admin/mrv_export/${plantId}?period=${encodeURIComponent(period)}`,
    { method: "POST" },
  );
}

// --- Tenant onboarding (api/routers/admin_tenants.py) ---

export function listAdminPlants() {
  return request<AdminPlantsResponse>("/admin/plants");
}

export function createPlant(body: CreatePlantInput) {
  return request<{ plant_id: string; sensors_created: number }>("/admin/plants", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listAdminUsers() {
  return request<AdminUsersResponse>("/admin/users");
}

export function createUser(body: CreateUserInput) {
  return request<CreateUserResult>("/admin/users", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function reinviteUser(userId: string) {
  return request<{ invite_token: string; invite_expires_at: string }>(
    `/admin/users/${userId}/reinvite`,
    { method: "POST" },
  );
}

export function patchUser(userId: string, body: PatchUserInput) {
  return request<PatchUserResult>(`/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function getAuditLog(limit: number = 100) {
  return request<AuditLogResponse>(`/admin/audit-log?limit=${limit}`);
}

// --- Contracts (api/routers/admin_billing.py) ---

export function listContracts(plantId?: string) {
  const suffix = plantId ? `?plant_id=${encodeURIComponent(plantId)}` : "";
  return request<ContractsResponse>(`/admin/contracts${suffix}`);
}

export function createContract(body: CreateContractInput) {
  return request<Contract>("/admin/contracts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- Documents (api/routers/admin_documents.py) ---
// uploadDocument bypasses request()'s JSON helper deliberately: it must
// send multipart/form-data with the browser's own boundary, which means
// NOT setting a Content-Type header at all (fetch/FormData set the
// correct one, including the boundary, only when the caller doesn't).
// The proxy (app/api/backend/[...path]/route.ts) forwards whatever
// Content-Type the incoming request carries, so this works unmodified.

export function listDocuments(entityType: DocumentEntityType, entityId: string) {
  return request<DocumentsResponse>(
    `/admin/documents?entity_type=${entityType}&entity_id=${encodeURIComponent(entityId)}`,
  );
}

export async function uploadDocument(
  entityType: DocumentEntityType,
  entityId: string,
  file: File,
  notes?: string,
): Promise<DocumentRecord> {
  const form = new FormData();
  form.set("entity_type", entityType);
  form.set("entity_id", entityId);
  if (notes) form.set("notes", notes);
  form.set("file", file);

  const res = await fetch("/api/backend/admin/documents", { method: "POST", body: form, cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new AdminApiError(res.status, detail);
  }
  return (await res.json()) as DocumentRecord;
}

export async function deleteDocument(documentId: string): Promise<void> {
  const res = await fetch(`/api/backend/admin/documents/${documentId}`, { method: "DELETE", cache: "no-store" });
  if (!res.ok && res.status !== 204) {
    throw new AdminApiError(res.status, res.statusText);
  }
}

// --- Offtake (api/routers/admin_offtake.py) ---

export function listBuyers() {
  return request<BuyersResponse>("/admin/offtake/buyers");
}
export function createBuyer(body: CreateBuyerInput) {
  return request<Buyer>("/admin/offtake/buyers", { method: "POST", body: JSON.stringify(body) });
}

export function listBatches(params?: { plant_id?: string; status?: string }) {
  const qs = new URLSearchParams();
  if (params?.plant_id) qs.set("plant_id", params.plant_id);
  if (params?.status) qs.set("status", params.status);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<BatchesResponse>(`/admin/offtake/batches${suffix}`);
}
export function createBatch(body: CreateBatchInput) {
  return request<ProductBatch>("/admin/offtake/batches", { method: "POST", body: JSON.stringify(body) });
}
export function recordBatchQc(
  batchId: string,
  body: { passed: boolean; inspector: string; result?: string | null; notes?: string | null },
) {
  return request<ProductBatch>(`/admin/offtake/batches/${batchId}/qc`, { method: "POST", body: JSON.stringify(body) });
}
export function allocateBatch(batchId: string, body: { buyer_id: string; rate_inr_per_kg?: number | null }) {
  return request<ProductBatch>(`/admin/offtake/batches/${batchId}/allocate`, { method: "POST", body: JSON.stringify(body) });
}
export function dispatchBatch(batchId: string) {
  return request<ProductBatch>(`/admin/offtake/batches/${batchId}/dispatch`, { method: "POST" });
}
export function generateCoa(batchId: string) {
  return request<ProductBatch>(`/admin/offtake/batches/${batchId}/coa`, { method: "POST" });
}

// --- CRM (api/routers/admin_crm.py) ---

export function listLeads(stage?: LeadStage) {
  const suffix = stage ? `?stage=${stage}` : "";
  return request<LeadsResponse>(`/admin/leads${suffix}`);
}
export function createLead(body: CreateLeadInput) {
  return request<Lead>("/admin/leads", { method: "POST", body: JSON.stringify(body) });
}
export function updateLeadStage(
  leadId: string,
  body: { stage: LeadStage; lost_reason?: string | null; converted_plant_id?: string | null },
) {
  return request<Lead>(`/admin/leads/${leadId}/stage`, { method: "PATCH", body: JSON.stringify(body) });
}
