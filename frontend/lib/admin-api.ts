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
  BurnRatesResponse,
  FleetResponse,
  InvoicesResponse,
  Invoice,
  MetricsResponse,
  MrvExportResponse,
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
