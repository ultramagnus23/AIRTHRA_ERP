// Types for the (admin) route group, mirroring api/routers/admin_*.py's
// response shapes exactly (field-for-field) so the components below can
// render without ever recomputing anything - see admin-api.ts's header
// for the "never compute business logic in the frontend" rule this
// exists to support.
//
// Kept separate from lib/types.ts (shared/owned by the scaffold) per the
// admin-console build brief - avoids any chance of colliding with the
// concurrent ERP/driver agents editing that file.
import type { AlarmSeverity, AlarmState } from "./types";

export type FleetColor = "green" | "yellow" | "red" | "gray";

export interface FleetEntry {
  plant_id: string;
  name: string;
  color: FleetColor;
  reasons: string[];
  last_reading_ts: string | null;
  flagged_pct_last_hour: number | null;
}

export interface FleetResponse {
  generated_at: string;
  thresholds: {
    offline_threshold_s: number;
    degraded_window_s: number;
    degraded_flag_pct: number;
  };
  fleet: FleetEntry[];
}

export interface AdminAlarm {
  alarm_id: string;
  plant_id: string;
  plant_name: string;
  rule_id: string | null;
  severity: AlarmSeverity;
  state: AlarmState;
  raised_at: string;
  acked_at: string | null;
  acked_by: string | null;
  cleared_at: string | null;
  diagnosis: string | null;
  suggested_part: string | null;
}

export interface AdminAlarmsResponse {
  state_filter: string | null;
  alarms: AdminAlarm[];
}

export interface MetricResult {
  plant_id: string;
  avg: number | null;
  min: number | null;
  max: number | null;
  sample_count: number;
  non_good_pct: number | null;
}

export interface MetricsResponse {
  metric: string;
  source: "kpi" | "reading";
  group_by: string;
  period: string;
  start: string;
  end: string;
  results: MetricResult[];
}

export interface BurnRateEntry {
  plant_id: string;
  name: string;
  koh: {
    current_level_pct: number | null;
    trend_pct_per_day: number | null;
    days_remaining: number | null;
    reason: string | null;
    sample_count: number;
  };
  k2so3: {
    fill_pct: number | null;
    as_of: string | null;
  };
}

export interface BurnRatesResponse {
  generated_at: string;
  window_days: number;
  method: string;
  plants: BurnRateEntry[];
}

export interface RiskComponents {
  data_quality: number;
  ack_latency: number;
  maintenance: number;
  flag_pct: number;
  spike_freq: number;
}

export interface RiskEntry {
  plant_id: string;
  name: string;
  risk_score: number;
  components: RiskComponents;
  raw: {
    readings_total: number;
    readings_non_good: number;
    avg_ack_latency_min: number | null;
    maintenance_events: number;
    maintenance_expected: number;
  };
}

export interface RiskScoresResponse {
  generated_at: string;
  period_days: number;
  weights: RiskComponents;
  notes: string;
  plants: RiskEntry[];
}

export type InvoiceStatus = "draft" | "approved" | "sent";

export interface Invoice {
  invoice_id: string;
  plant_id: string;
  period: string;
  so2_kg: number | null;
  k2so3_kg: number | null;
  uptime_pct: number | null;
  amount: number | null;
  pdf_url: string | null;
  status: InvoiceStatus;
}

export interface InvoicesResponse {
  invoices: Invoice[];
}

export interface MrvExportResponse {
  plant_id: string;
  plant_name: string;
  period: string;
  zip_url: string;
  zip_sha256: string;
  day_count: number;
  manifest: Record<string, unknown>;
}
