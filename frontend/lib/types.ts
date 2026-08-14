// Shared API types for the Airthra frontend.
//
// These mirror api/schemas.py + the raw row shapes returned by
// api/routers/plant.py and api/routers/alarms_list.py. Kept in one file
// so the admin/ERP/driver route groups other agents build on top of
// this scaffold can import the same types instead of re-declaring them.

/** The three JWT roles api/security.py issues (DB_ROLE_TO_JWT_ROLE). */
export type JwtRole = "tenant_read" | "global_admin" | "global_read";

export interface SessionUser {
  userId: string;
  role: JwtRole;
  plantIds: string[];
  /** Unix seconds, from the JWT `exp` claim. */
  exp: number;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: JwtRole;
  plant_ids: string[];
}

/**
 * quality_flag as it appears over REST (api/routers/plant.py reads it
 * straight out of Postgres, post the 0003 migration's 5-value enum).
 */
export type QualityFlagText =
  | "good"
  | "comm_error"
  | "out_of_range"
  | "frozen"
  | "imputed";

/**
 * quality_flag as it appears on the raw WS fan-out (shared/quality.py
 * integer wire codes - api/mqtt_bridge.py relays the edge daemon's raw
 * MQTT payload verbatim, it does NOT go through the ingest text-enum
 * mapping). See lib/quality.ts for the code -> label bridge.
 */
export type QualityFlagWire = 0 | 1 | 2 | 3 | 4;

export interface CurrentReading {
  sensor_id: string;
  ts: string;
  value: number | null;
  quality_flag: QualityFlagText;
}

export interface CurrentReadingsResponse {
  plant_id: string;
  readings: CurrentReading[];
}

/** One reading in a plants/{plant_id}/readings WS message (wire format). */
export interface WsReading {
  plant_id: string;
  sensor_id: string;
  ts: string;
  value: number | null;
  quality_flag: QualityFlagWire;
}

export interface RawHistoryPoint {
  sensor_id: string;
  ts: string;
  value: number | null;
  quality_flag: QualityFlagText;
}

export interface AggHistoryPoint {
  sensor_id: string;
  bucket: string;
  avg_value: number | null;
  min_value: number | null;
  max_value: number | null;
  sample_count: number;
  flagged_count: number;
}

export type HistoryPoint = RawHistoryPoint | AggHistoryPoint;

export interface HistoryResponse {
  plant_id: string;
  resolution: "raw" | "1m" | "15m" | "1h";
  start: string;
  end: string;
  points: HistoryPoint[];
}

export interface KpiPoint {
  ts: string;
  kpi_name: string;
  value: number | null;
  quality_flag: QualityFlagText;
}

export interface KpisResponse {
  plant_id: string;
  kpis: KpiPoint[];
}

export type EventKind = "maintenance" | "lab_sample" | "note" | "alarm_ack";

export interface EventCreateBody {
  kind: EventKind;
  payload: Record<string, unknown>;
}

export interface EventOut {
  event_id: string;
  plant_id: string;
  user_id: string | null;
  ts: string;
  kind: EventKind;
  payload: Record<string, unknown>;
}

export type AlarmSeverity = "info" | "warning" | "critical";
export type AlarmState = "raised" | "acked" | "cleared" | "escalated";

export interface Alarm {
  alarm_id: string;
  plant_id: string;
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

export interface AlarmsResponse {
  plant_id: string;
  alarms: Alarm[];
}

/** Static sensor manifest - not exposed by any endpoint, mirrors seed/seed.py SENSORS. */
export interface SensorMeta {
  sensor_id: string;
  label: string;
  unit: string;
}

export const SENSOR_MANIFEST: SensorMeta[] = [
  { sensor_id: "SO2_in", label: "SO2 (inlet)", unit: "ppm" },
  { sensor_id: "SO2_out", label: "SO2 (stack/outlet)", unit: "ppm" },
  { sensor_id: "pH", label: "Scrubber pH", unit: "pH" },
  { sensor_id: "temp_C", label: "Temperature", unit: "C" },
  { sensor_id: "level_KOH_tank", label: "KOH tank level", unit: "%" },
  { sensor_id: "level_K2SO3_tank", label: "K2SO3 tank level", unit: "%" },
  { sensor_id: "flow", label: "Flue gas flow", unit: "m3/h" },
];
