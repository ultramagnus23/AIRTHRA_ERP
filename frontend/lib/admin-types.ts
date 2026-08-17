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

// DB roles (users.role's CHECK constraint) - not the JWT roles. The three
// plant_* roles all currently decode to the same JWT role (tenant_read,
// see api/security.py DB_ROLE_TO_JWT_ROLE) and so behave identically
// today; the distinct DB values are kept for when that changes, and
// exposed here for accuracy rather than collapsing them in the UI too.
export type DbRole = "global_admin" | "global_read" | "plant_admin" | "plant_operator" | "plant_viewer";

export interface AdminPlantSummary {
  plant_id: string;
  name: string;
  commissioning_date: string | null;
  sensor_count: number;
  user_count: number;
}

export interface AdminPlantsResponse {
  plants: AdminPlantSummary[];
}

export interface SensorInput {
  sensor_id: string;
  tag: string;
  kind: string;
  unit: string;
  min_valid?: number | null;
  max_valid?: number | null;
}

export interface CreatePlantInput {
  plant_id: string;
  name: string;
  lat?: number | null;
  lon?: number | null;
  ambient_climate?: string | null;
  boiler_capacity_tpd?: number | null;
  fuel_type_primary?: string | null;
  commissioning_date?: string | null;
  timezone_display?: string;
  sensors: SensorInput[];
}

export interface AdminUserSummary {
  user_id: string;
  email: string;
  role: DbRole;
  created_at: string;
  plant_ids: string[];
  invite_pending: boolean;
}

export interface AdminUsersResponse {
  users: AdminUserSummary[];
}

export interface CreateUserInput {
  email: string;
  role: DbRole;
  plant_ids: string[];
}

export interface CreateUserResult {
  user_id: string;
  email: string;
  role: DbRole;
  plant_ids: string[];
  invite_token: string;
  invite_expires_at: string;
}

export interface AuditLogEntry {
  log_id: string;
  action: string;
  target_type: string;
  target_id: string;
  detail: Record<string, unknown>;
  created_at: string;
  actor_email: string | null;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
}

// Mirrors migration 0009_documents's CHECK constraint - keep in sync.
export type DocumentEntityType =
  | "plant"
  | "contract"
  | "vendor"
  | "purchase_order"
  | "bom"
  | "invoice"
  | "fabrication_job"
  | "unit_serial"
  | "user"
  | "company";

export interface DocumentRecord {
  document_id: string;
  entity_type: DocumentEntityType;
  entity_id: string;
  filename: string;
  content_type: string;
  sha256: string;
  bytes: number;
  notes: string | null;
  uploaded_by: string | null;
  uploaded_by_email: string | null;
  uploaded_at: string;
  download_url: string;
}

export interface DocumentsResponse {
  documents: DocumentRecord[];
}

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

export interface InvoiceLineItems {
  contract_id: string;
  base_fee_inr: number;
  usage_rate_inr_per_kg: number;
  usage_fee_inr: number;
  performance_adjustment_inr: number;
  performance_note: string | null;
  total_inr: number;
}

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
  contract_id: string | null;
  line_items: InvoiceLineItems | Record<string, never>;
}

export interface Contract {
  contract_id: string;
  plant_id: string;
  status: "draft" | "active" | "ended";
  effective_from: string;
  effective_to: string | null;
  base_fee_inr: number;
  usage_rate_inr_per_kg: number;
  performance_bonus_threshold_pct: number | null;
  performance_bonus_inr: number;
  performance_penalty_threshold_pct: number | null;
  performance_penalty_inr: number;
  revenue_share_pct: number;
  notes: string | null;
  created_at: string;
}

export interface ContractsResponse {
  contracts: Contract[];
}

export interface CreateContractInput {
  plant_id: string;
  effective_from: string;
  base_fee_inr: number;
  usage_rate_inr_per_kg: number;
  performance_bonus_threshold_pct?: number | null;
  performance_bonus_inr?: number;
  performance_penalty_threshold_pct?: number | null;
  performance_penalty_inr?: number;
  revenue_share_pct?: number;
  notes?: string | null;
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
