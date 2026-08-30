// Shared API types for the Airthra frontend.
//
// These mirror api/schemas.py + the raw row shapes returned by
// api/routers/plant.py and api/routers/alarms_list.py. Kept in one file
// so the admin/ERP/driver route groups other agents build on top of
// this scaffold can import the same types instead of re-declaring them.

/** The four JWT roles api/security.py issues (DB_ROLE_TO_JWT_ROLE). */
export type JwtRole = "tenant_read" | "global_admin" | "global_read" | "dept_user";

/** api/security.py's DEPARTMENTS - the business functions a dept_user can be scoped to. */
export type Department = "finance" | "procurement" | "engineering" | "sales" | "logistics";

export interface SessionUser {
  userId: string;
  role: JwtRole;
  plantIds: string[];
  /** Only set (and only meaningful) when role === "dept_user". */
  department: Department | null;
  /** Unix seconds, from the JWT `exp` claim. */
  exp: number;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: JwtRole;
  plant_ids: string[];
  department: Department | null;
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
export type Subsystem =
  | "gas_path"
  | "absorber_loop"
  | "product_loop"
  | "energy_recovery"
  | "mechanical_health";

export const SUBSYSTEM_LABELS: Record<Subsystem, string> = {
  gas_path: "Gas path, emissions & safety",
  absorber_loop: "Absorber & solvent loop",
  product_loop: "Product & reagent inventory",
  energy_recovery: "Waste-heat recovery loop",
  mechanical_health: "Pump, fan & duct condition monitoring",
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
  /** Sensor hardware + signal path, per the register. Placeholder tags (wired: false) say so plainly rather than inventing a part number. */
  hardware: string;
  /** Physical mounting location, per the register. */
  location: string;
  /** What this instrument is diagnostically for. */
  purpose: string;
  subsystem: Subsystem;
  /** Whether this tag has a real sensor feeding it today. false = catalogued
   * from the FEED register (tag code is real) but not yet wired to
   * hardware - the tile still renders, showing "--" instead of a value,
   * per the platform's own "never fake data" rule (never omitted, never
   * synthesized). */
  wired: boolean;
  /** Engineering min/max, mirrors sensors.min_valid/max_valid in seed/seed.py.
   * Presentational only (range-bar context), not a computed value.
   * Omitted for unwired tags where no authoritative register range has
   * been transcribed into this codebase yet, rather than guessing one. */
  min?: number;
  max?: number;
  /** Sub-range considered "normal" for the bar's fill, distinct from the hard min/max. */
  normal?: [number, number];
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
    wired: true,
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
    wired: true,
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
    wired: true,
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
    wired: true,
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
    wired: true,
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
    wired: true,
    unit: "%",
    min: 0,
    max: 100,
    normal: [25, 100],
    threshold: "<150 L — order more KOH",
    note: "Register specifies litres (200–1000 L); this platform stores percent. Alarm rule (koh_tank_low_level_v1) trips at 15%, assuming a 1000L tote — that capacity isn't independently confirmed, see AUDIT.md #1.2.",
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
    wired: true,
    unit: "%",
    min: 0,
    max: 100,
    normal: [0, 85],
    threshold: ">900 L — alert for tote changeout",
    note: "Register specifies litres (50–950 L); this platform stores percent. Alarm rule (k2so3_tank_full_v1) trips at 90%, based on this tote's own 1000L rated capacity (see location above).",
    accent: "moss",
  },

  // ---------------------------------------------------------------------
  // Catalogued but NOT wired: real FEED register tag codes (cited in
  // AUDIT.md's fault-tree gap analysis and in the calculated-metrics
  // formulas this platform's KPI worker will eventually consume), no
  // hardware installed against them yet. hardware/location intentionally
  // say so rather than inventing a part number or mounting point this
  // codebase has no source for. These render as "--" tiles, never
  // fabricated readings - see the `wired` field's own doc comment.
  //
  // This is NOT the full 40-tag register: it's the ~16 additional tags
  // this codebase currently has an actual cited code and purpose for.
  // The remaining ~17 tags need the original FEED register document
  // (re-)supplied to transcribe honestly, the same way the 7 wired tags
  // and these 16 were sourced - not guessed to hit a round number.
  // ---------------------------------------------------------------------
  {
    sensor_id: "AT-03",
    label: "Combustion air O2",
    tag: "AT-03",
    hardware: "Not yet installed",
    location: "Boiler flue inlet, upstream of the gas cooler",
    purpose: "Excess-air ratio (lambda) and combustion quality index for the factory-side boiler health add-on.",
    subsystem: "gas_path",
    wired: false,
    unit: "%",
    threshold: null,
    accent: "copper",
  },
  {
    sensor_id: "AT-04",
    label: "Combustion CO",
    tag: "AT-04",
    hardware: "Not yet installed",
    location: "Boiler flue inlet, alongside AT-03",
    purpose: "Incomplete-combustion loss term for the combustion quality index; flags wet/poor-quality fuel batches.",
    subsystem: "gas_path",
    wired: false,
    unit: "ppm",
    threshold: null,
    accent: "copper",
  },
  {
    sensor_id: "TE-01B",
    label: "Gas temp (post-cooler)",
    tag: "TE-01B",
    hardware: "Not yet installed",
    location: "Gas duct, immediately after E-101, before absorber inlet",
    purpose: "Paired with TE-01 to compute waste-heat scavenged by the gas cooler (E-101).",
    subsystem: "energy_recovery",
    wired: false,
    unit: "C",
    threshold: null,
    accent: "copper",
  },
  {
    sensor_id: "PT-02",
    label: "Duct pressure (pre-cooler)",
    tag: "PT-02",
    hardware: "Not yet installed",
    location: "Gas duct, before E-101",
    purpose: "With PT-03, tracks duct resistance normalized by fan speed - rising trend flags ash fouling.",
    subsystem: "energy_recovery",
    wired: false,
    unit: "Pa",
    threshold: null,
    accent: "copper",
  },
  {
    sensor_id: "PT-03",
    label: "Duct pressure (post-cooler)",
    tag: "PT-03",
    hardware: "Not yet installed",
    location: "Gas duct, after E-101",
    purpose: "Paired with PT-02 for the duct ash-fouling factor.",
    subsystem: "energy_recovery",
    wired: false,
    unit: "Pa",
    threshold: null,
    accent: "copper",
  },
  {
    sensor_id: "TE-06",
    label: "PHE-101 hot-side outlet",
    tag: "TE-06",
    hardware: "Not yet installed",
    location: "Plate heat exchanger PHE-101, hot side",
    purpose: "With TE-09, PHE-101 thermal effectiveness - a slow drift down flags plate fouling.",
    subsystem: "energy_recovery",
    wired: false,
    unit: "C",
    threshold: null,
    accent: "copper",
  },
  {
    sensor_id: "TE-09",
    label: "PHE-101 cold-side inlet",
    tag: "TE-09",
    hardware: "Not yet installed",
    location: "Plate heat exchanger PHE-101, cold side",
    purpose: "Paired with TE-06 for PHE-101 effectiveness.",
    subsystem: "energy_recovery",
    wired: false,
    unit: "C",
    threshold: null,
    accent: "copper",
  },
  {
    sensor_id: "TE-12",
    label: "Venturi throat temp",
    tag: "TE-12",
    hardware: "Not yet installed",
    location: "Venturi (P-103) throat outlet",
    purpose: "Energy-balance cross-check on instantaneous SO2 -> K2SO3 neutralization, alongside AT-02 pH.",
    subsystem: "absorber_loop",
    wired: false,
    unit: "C",
    threshold: null,
    accent: "copper",
  },
  {
    sensor_id: "PT-05",
    label: "P-101 discharge pressure",
    tag: "PT-05",
    hardware: "Not yet installed",
    location: "Solvent circulation pump P-101, discharge line",
    purpose: "With the pump's motor current, a 7-day rolling ratio gives ~2 weeks' advance warning of stator wear.",
    subsystem: "mechanical_health",
    wired: false,
    unit: "bar",
    threshold: null,
    accent: "moss",
  },
  {
    sensor_id: "VFD-P101",
    label: "P-101 motor current",
    tag: "VFD-P101",
    hardware: "Not yet installed",
    location: "P-101 VFD drive",
    purpose: "Motor amps, denominator of the stator wear index alongside PT-05.",
    subsystem: "mechanical_health",
    wired: false,
    unit: "A",
    threshold: null,
    accent: "moss",
  },
  {
    sensor_id: "VFD-B101",
    label: "FD fan speed/power",
    tag: "VFD-B101",
    hardware: "Not yet installed",
    location: "Forced-draft fan B-101 drive",
    purpose: "SO2 mass capture rate normalization and the boiler-side excess-air diagnostics.",
    subsystem: "mechanical_health",
    wired: false,
    unit: "Hz",
    threshold: null,
    accent: "moss",
  },
  {
    sensor_id: "PT-08",
    label: "P-103 motive pressure",
    tag: "PT-08",
    hardware: "Not yet installed",
    location: "Venturi P-103, motive water/liquor supply",
    purpose: "With PT-01 (vacuum drawn), detects venturi nozzle wear or plugging.",
    subsystem: "mechanical_health",
    wired: false,
    unit: "bar",
    threshold: null,
    accent: "moss",
  },
  {
    sensor_id: "PT-01",
    label: "P-103 vacuum drawn",
    tag: "PT-01",
    hardware: "Not yet installed",
    location: "Venturi P-103, suction side",
    purpose: "Paired with PT-08 for venturi motive health.",
    subsystem: "mechanical_health",
    wired: false,
    unit: "bar",
    threshold: null,
    accent: "moss",
  },
  {
    sensor_id: "DP-101",
    label: "Absorber bed dP",
    tag: "DP-101",
    hardware: "Not yet installed",
    location: "Absorber packed bed, across the packing",
    purpose: "Column flooding margin - detects liquid holdup before solvent backs up into the gas duct.",
    subsystem: "mechanical_health",
    wired: false,
    unit: "Pa",
    threshold: null,
    accent: "moss",
  },
  {
    sensor_id: "DP-S101",
    label: "Hydrocyclone dP",
    tag: "DP-S101",
    hardware: "Not yet installed",
    location: "Hydrocyclone S-101, inlet to overflow",
    purpose: "Ash carryover / blockage severity - detects a plugged underflow orifice dumping ash into clean solvent.",
    subsystem: "mechanical_health",
    wired: false,
    unit: "Pa",
    threshold: null,
    accent: "moss",
  },
  {
    sensor_id: "EM-01",
    label: "Skid total power",
    tag: "EM-01",
    hardware: "Not yet installed",
    location: "Skid main incomer",
    purpose: "Specific energy consumption (kWh per kg SO2 captured) - the ESG/green-loan intensity metric.",
    subsystem: "mechanical_health",
    wired: false,
    unit: "kWh",
    threshold: null,
    accent: "moss",
  },
];

/** Instrument coverage: how much of the FEED register is actually wired up.
 * Denominator is the register's full tag count across all five subsystems;
 * the numerator is WIRED_TAG_COUNT below. Displayed honestly on the Live
 * page rather than presenting 7 sensors as if they were the whole plant. */
export const REGISTER_TAG_COUNT = 40;

/** Tags with a real sensor feeding them today. */
export const WIRED_TAG_COUNT = SENSOR_MANIFEST.filter((s) => s.wired).length;

/** Tags catalogued in this codebase at all (wired + known-but-unwired
 * placeholders) - always <= REGISTER_TAG_COUNT. The gap between this and
 * REGISTER_TAG_COUNT is register tags this codebase has no cited source
 * for yet, not tags deliberately left out. */
export const CATALOGUED_TAG_COUNT = SENSOR_MANIFEST.length;

/** A derived KPI (workers/kpi_worker.py), computed server-side from real
 * wired sensors - never in the frontend, per the platform's hard rule
 * that business logic is never computed client-side. `kpi_name` matches
 * exactly what the worker writes to `kpis.kpi_name`. */
export interface ComputableMetric {
  kpi_name: string;
  label: string;
  unit: string;
  formula: string;
  category: "process" | "energy" | "factory" | "maintenance" | "commercial";
}

/** A metric from the platform's calculated-data roadmap that is NOT yet
 * computable: at least one required tag has no real sensor
 * (SENSOR_MANIFEST wired: false, or not catalogued at all). Never
 * estimated or fabricated - the Live page shows these as "awaiting
 * instrumentation" with the exact tags still needed. */
export interface PendingMetric {
  label: string;
  unit: string;
  formula: string;
  /** Register tag codes this metric needs that aren't wired yet. */
  missingTags: string[];
  category: "process" | "energy" | "factory" | "maintenance" | "commercial";
}

export const COMPUTABLE_METRICS: ComputableMetric[] = [
  {
    kpi_name: "so2_removal_efficiency",
    label: "SO2 removal efficiency",
    unit: "%",
    formula: "(AT-01 - AE-02) / AT-01 x 100",
    category: "process",
  },
  {
    kpi_name: "mass_balance_closure",
    label: "Mass balance closure",
    unit: "%",
    formula: "workers/kpi_worker.py - see source for the exact reconciliation",
    category: "process",
  },
];

const CATEGORY_LABELS: Record<PendingMetric["category"], string> = {
  process: "Chemical & process performance",
  energy: "Thermodynamics & energy scavenging",
  factory: "Factory-side combustion intelligence",
  maintenance: "Predictive maintenance & asset health",
  commercial: "Commercial, ESG & carbon-credit MRV",
};
export { CATEGORY_LABELS };

/** The rest of the client's calculated-metrics roadmap. Every formula
 * here is real (transcribed from the spec as given); every one is marked
 * pending because at least one input tag isn't wired yet - see each
 * tag's own SENSOR_MANIFEST entry for what "wired" means. */
export const PENDING_METRICS: PendingMetric[] = [
  {
    label: "SO2 mass capture rate",
    unit: "kg/hr",
    formula: "AT-01_ppm x (VFD-B101/50) x (flow/1e6) x (64.07/22.414) x (273.15/(273.15+TE-01B))",
    missingTags: ["VFD-B101", "TE-01B"],
    category: "process",
  },
  {
    label: "DES solvent specific loading",
    unit: "g SO2 / kg DES",
    formula: "Mass SO2 absorbed / solvent circulation rate (P-101)",
    missingTags: ["P-101 flow"],
    category: "process",
  },
  {
    label: "Venturi neutralization stoichiometry",
    unit: "%",
    formula: "Energy balance across venturi (dT = TE-12 - T_KOH) correlated with AT-02 pH",
    missingTags: ["TE-12", "T_KOH"],
    category: "process",
  },
  {
    label: "Product concentration estimator",
    unit: "wt% K2SO3",
    formula: "Cumulative SO2 mass in vs. cumulative KOH addition vs. delta LE-02",
    missingTags: ["cumulative dosing totals"],
    category: "process",
  },
  {
    label: "Flue gas waste heat scavenged",
    unit: "kW",
    formula: "m_gas x Cp_gas x (TE-01B - TE-01)",
    missingTags: ["TE-01B", "gas mass flow"],
    category: "energy",
  },
  {
    label: "Stripper thermal utilization",
    unit: "kW",
    formula: "m_oil x Cp_oil x (T_oil,in - T_oil,out)",
    missingTags: ["thermal oil loop instrumentation"],
    category: "energy",
  },
  {
    label: "PHE-101 exchanger effectiveness",
    unit: "%",
    formula: "(TE-06 - TE-05) / (TE-09 - TE-05) x 100",
    missingTags: ["TE-05", "TE-06", "TE-09"],
    category: "energy",
  },
  {
    label: "Parasitic energy avoidance",
    unit: "Rs/day",
    formula: "(Q_recovered x 24h x cost of steam) - oil pump power",
    missingTags: ["TE-01B", "oil pump power"],
    category: "energy",
  },
  {
    label: "Combustion quality index",
    unit: "0-100",
    formula: "100 - dry heat loss% - incomplete combustion loss%",
    missingTags: ["AT-03", "AT-04"],
    category: "factory",
  },
  {
    label: "Excess air ratio (lambda)",
    unit: "ratio",
    formula: "20.9 / (20.9 - AT-03)",
    missingTags: ["AT-03"],
    category: "factory",
  },
  {
    label: "Fuel moisture / quality anomaly",
    unit: "flag",
    formula: "Divergence between boiler steam output and inlet SO2/CO signature",
    missingTags: ["AT-04", "boiler steam output feed"],
    category: "factory",
  },
  {
    label: "Estimated factory biomass consumption",
    unit: "TPD",
    formula: "Integrated sulfur mass in flue gas / known biomass sulfur fraction (0.5% S)",
    missingTags: ["fuel sulfur fraction reference"],
    category: "factory",
  },
  {
    label: "Normalized stack emission intensity",
    unit: "mg/Nm3 @ 11% O2",
    formula: "AE-02 x ((20.9-11.0)/(20.9-AT-03)) x 2.86",
    missingTags: ["AT-03"],
    category: "factory",
  },
  {
    label: "P-101 stator wear index",
    unit: "0.0-1.0",
    formula: "7-day rolling ratio of PT-05 / VFD-P101",
    missingTags: ["PT-05", "VFD-P101"],
    category: "maintenance",
  },
  {
    label: "P-103 venturi motive health",
    unit: "ratio",
    formula: "PT-08 / PT-01",
    missingTags: ["PT-08", "PT-01"],
    category: "maintenance",
  },
  {
    label: "Absorber bed flooding margin",
    unit: "Pa",
    formula: "Measured DP-101 vs. theoretical Ergun-equation dry-bed pressure drop",
    missingTags: ["DP-101"],
    category: "maintenance",
  },
  {
    label: "Hydrocyclone ash blockage severity",
    unit: "Pa",
    formula: "DP-S101 differential, inlet to overflow",
    missingTags: ["DP-S101"],
    category: "maintenance",
  },
  {
    label: "Duct ash fouling factor",
    unit: "index",
    formula: "(PT-02 - PT-03) / VFD-B101^2",
    missingTags: ["PT-02", "PT-03", "VFD-B101"],
    category: "maintenance",
  },
  {
    label: "Monthly offtake billing total",
    unit: "Rs",
    formula: "integral(AT-01 - AE-02) dt x contracted rate - already the billing_worker's own path (workers/billing_worker.py), not this KPI pipeline",
    missingTags: [],
    category: "commercial",
  },
  {
    label: "Verified fertilizer production",
    unit: "kg",
    formula: "Continuous integration of d(LE-02)/dt x specific gravity, cross-checked with load cells",
    missingTags: ["load cell cross-check"],
    category: "commercial",
  },
  {
    label: "Specific energy consumption",
    unit: "kWh/kg SO2",
    formula: "Total skid kWh (EM-01) / total kg SO2 captured",
    missingTags: ["EM-01"],
    category: "commercial",
  },
  {
    label: "Avoided atmospheric acid deposition",
    unit: "kg H2SO4 eq",
    formula: "Mass SO2 x 1.53",
    missingTags: ["depends on SO2 mass capture rate above"],
    category: "commercial",
  },
];
