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

export type EventKind =
  | "maintenance"
  | "lab_sample"
  | "note"
  | "alarm_ack"
  | "koh_added"
  | "tote_changeout"
  | "phe_cleaned"
  | "stator_changed"
  | "demister_cleaned"
  | "fuel_change"
  | "boiler_trip"
  | "emergency_trip"
  | "sensor_calibration"
  | "purge_cycle";

/** One-tap operator actions, in the order they appear on the events page.
 *
 * These rows are ML ground truth, which drives every design choice here:
 * a model cannot tell a KOH top-up from an anomaly unless the human action
 * is a discrete label rather than free text. Logging must be ONE TAP,
 * because anything slower will not happen during an actual incident -
 * which is exactly when the label matters most.
 *
 * `quantity` marks actions where the amount is itself a feature (how much
 * KOH went in), prompting for a number before submitting. Everything else
 * files immediately on tap.
 */
export interface QuickEvent {
  kind: EventKind;
  label: string;
  /** Equipment tag from the FEED register, where one applies. */
  tag?: string;
  /** Prompt for a quantity; unit shown next to the input. */
  quantity?: { unit: string; hint: string };
  /** Safety-critical actions render in rust rather than copper. */
  severity?: "critical";
}

export const QUICK_EVENTS: QuickEvent[] = [
  { kind: "koh_added", label: "Added KOH", tag: "LE-03", quantity: { unit: "L", hint: "Litres added" } },
  { kind: "tote_changeout", label: "Tote changeout", tag: "LE-02" },
  { kind: "phe_cleaned", label: "Cleaned PHE", tag: "PHE-101" },
  { kind: "stator_changed", label: "Changed stator", tag: "P-101" },
  { kind: "demister_cleaned", label: "Cleaned demister", tag: "T-101" },
  { kind: "fuel_change", label: "Boiler fuel change" },
  { kind: "sensor_calibration", label: "Sensor calibration" },
  { kind: "purge_cycle", label: "Purge cycle" },
  { kind: "boiler_trip", label: "Boiler trip", severity: "critical" },
  { kind: "emergency_trip", label: "Emergency trip", severity: "critical" },
];

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

/** Instrument subsystems, per the FEED instrument register's own grouping. */
export type Subsystem = "gas_path" | "absorber_loop" | "product_loop";

export const SUBSYSTEM_LABELS: Record<Subsystem, string> = {
  gas_path: "Gas path, emissions & safety",
  absorber_loop: "Absorber & solvent loop",
  product_loop: "Product & reagent inventory",
};

/** Static sensor manifest - not exposed by any endpoint, mirrors seed/seed.py SENSORS.
 *
 * Tag IDs, mounting locations, diagnostic purposes and normal/trip ranges are
 * transcribed from the FEED instrument register. Where the register and this
 * platform disagree, the register wins and the divergence is recorded in
 * `note` rather than silently reconciled - see AUDIT.md. All of this is
 * PRESENTATIONAL reference context only: nothing here decides whether a
 * reading is in alarm. That is the alarm engine's job (workers/alarm_engine.py,
 * surfaced via the alarms API), per the platform rule that business logic is
 * never computed in the frontend.
 */
export interface SensorMeta {
  sensor_id: string;
  label: string;
  unit: string;
  /** FEED register tag (AT-01, AE-02, ...). The identifier a field engineer reads. */
  tag: string;
  /** Sensor hardware + signal path, per the register. */
  hardware: string;
  /** Physical mounting location, per the register. */
  location: string;
  /** What this instrument is diagnostically for. */
  purpose: string;
  subsystem: Subsystem;
  /** Engineering min/max, mirrors sensors.min_valid/max_valid in seed/seed.py. Presentational only (range-bar context), not a computed value. */
  min: number;
  max: number;
  /** Sub-range considered "normal" for the bar's fill, distinct from the hard min/max. */
  normal: [number, number];
  /** Register's alert/trip threshold, verbatim. Displayed as reference text, never evaluated here. */
  threshold: string | null;
  /** Where this platform's sensor and the FEED register don't line up. */
  note?: string;
  /** Categorical color-coding (Airthra palette only): process/emission readings vs. tank/inventory levels. */
  accent: "copper" | "moss";
}

export const SENSOR_MANIFEST: SensorMeta[] = [
  {
    sensor_id: "SO2_in",
    label: "SO2 (inlet)",
    tag: "AT-01",
    hardware: "Sangbay K-5S (0–5000 ppm), Modbus RS-485",
    location: "Gas inlet duct, before B-101 / E-101",
    purpose: "Raw boiler SO2 mass load entering the plant. Primary billing input.",
    subsystem: "gas_path",
    unit: "ppm",
    min: 0,
    max: 5000,
    normal: [200, 800],
    threshold: ">2000 ppm — high boiler sulfur alarm",
    accent: "copper",
  },
  {
    sensor_id: "SO2_out",
    label: "SO2 (stack/outlet)",
    tag: "AE-02",
    hardware: "Sangbay K-5S (0–100 ppm), Modbus RS-485",
    location: "Clean stack exhaust duct, after T-101",
    purpose: "Continuous stack emission compliance monitoring. Proves >95% removal.",
    subsystem: "gas_path",
    unit: "ppm",
    min: 0,
    max: 500,
    normal: [5, 25],
    threshold: ">50 ppm — TRIP, drops bypass damper",
    accent: "copper",
  },
  {
    sensor_id: "temp_C",
    label: "Absorber inlet temp",
    tag: "TE-01",
    hardware: "DS18B20 in SS316 thermowell, 1-Wire bus A",
    location: "Absorber inlet gas pipe, before N1",
    purpose: "Gas cooling before the FRP tower. Protects vinyl ester resin from thermal degradation.",
    subsystem: "gas_path",
    unit: "C",
    min: -10,
    max: 200,
    normal: [55, 65],
    threshold: "≥70°C — HARD TRIP, drops bypass damper",
    accent: "copper",
  },
  {
    sensor_id: "flow",
    label: "Flue gas flow",
    tag: "FT-01",
    hardware: "Flow transmitter",
    location: "Gas inlet duct",
    purpose: "Flue gas throughput, paired with AT-01 to derive SO2 mass load.",
    subsystem: "gas_path",
    unit: "m3/h",
    min: 0,
    max: 500,
    normal: [100, 350],
    threshold: null,
    note: "No entry in the FEED instrument register — ranges are the platform's own, pending spec.",
    accent: "copper",
  },
  {
    sensor_id: "pH",
    label: "Scrubber pH",
    tag: "AT-02",
    hardware: "pH-4502C + electrode, analog → ADS1115",
    location: "Cooled side-stream from the 200L MS drum",
    purpose: "Active neutralization & product quality. Guarantees stable K2SO3, prevents stack slippage.",
    subsystem: "absorber_loop",
    unit: "pH",
    min: 0,
    max: 14,
    normal: [8.5, 9.5],
    threshold: "<8.0 — dose more KOH · >10.5 — unreacted KOH",
    accent: "copper",
  },
  {
    sensor_id: "level_KOH_tank",
    label: "KOH tank level",
    tag: "LE-03",
    hardware: "JSN-SR04T ultrasonic, GPIO trigger/echo",
    location: "Top lid of the elevated KOH supply tote",
    purpose: "Raw KOH chemical inventory. Feeds automated bulk procurement.",
    subsystem: "product_loop",
    unit: "%",
    min: 0,
    max: 100,
    normal: [25, 100],
    threshold: "<150 L — order more KOH",
    note: "Register specifies litres (200–1000 L); this platform stores percent. Not converted — needs a decision.",
    accent: "moss",
  },
  {
    sensor_id: "level_K2SO3_tank",
    label: "K2SO3 tank level",
    tag: "LE-02",
    hardware: "JSN-SR04T ultrasonic, GPIO trigger/echo",
    location: "Top lid of the 1000L product IBC tote",
    purpose: "Fertilizer receiver level. Prevents overfill, triggers driver dispatch.",
    subsystem: "product_loop",
    unit: "%",
    min: 0,
    max: 100,
    normal: [0, 85],
    threshold: ">900 L — alert for tote changeout",
    note: "Register specifies litres (50–950 L); this platform stores percent. Not converted — needs a decision.",
    accent: "moss",
  },
];

/** Instrument coverage: how much of the FEED register is actually wired up.
 * Denominator is the register's full tag count across all five subsystems;
 * the numerator is SENSOR_MANIFEST. Displayed honestly on the Live page
 * rather than presenting 7 sensors as if they were the whole plant. */
export const REGISTER_TAG_COUNT = 40;
