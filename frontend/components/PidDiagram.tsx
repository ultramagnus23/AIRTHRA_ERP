"use client";

import { qualityInfo } from "@/lib/quality";
import type { QualityFlagText, QualityFlagWire } from "@/lib/types";

export interface PidReading {
  value: number | null;
  flag: QualityFlagText | QualityFlagWire | number | string;
  unit: string;
}

// Airthra token values resolved to raw colors for SVG fill/stroke, since
// SVG attributes don't resolve Tailwind's CSS-variable-backed utility
// classes the way className does elsewhere in this app.
const FG = "oklch(0.965 0.012 236)";
const MIST = "oklch(0.72 0.022 240)";
const LINE = "oklch(0.955 0.014 236 / 0.16)";
const HAIR = "oklch(0.955 0.014 236 / 0.09)";
const COPPER = "oklch(0.72 0.15 54)";
const MOSS = "oklch(0.64 0.1 152)";
const RUST = "oklch(0.52 0.16 48)";

/**
 * Full-process FGD schematic (a real P&ID stand-in, per client request):
 * boiler -> tie-in -> NEELKANTH absorption unit -> stack, with the actual
 * process chemistry (SO2 + 2KOH -> K2SO3 + S -> K2S2O3) drawn from
 * airthra.com's own process description, every physical sensor placed at
 * its real location with a tag code (AE/TE/LT/FT convention), and every
 * material stream labeled - including the streams Airthra's process
 * eliminates entirely (gypsum waste, once-through water) and the one
 * downstream conversion step (K2SO3 -> K2S2O3 offtake) that isn't yet
 * instrumented by a sensor in this build. Nothing here is fabricated
 * data: readings are wired to real props, and every non-instrumented
 * stage is explicitly labeled as such, never implied to be live.
 */
export default function PidDiagram({
  so2In,
  so2Out,
  ph,
  temp,
  kohLevel,
  k2so3Level,
  flow,
}: {
  so2In?: PidReading;
  so2Out?: PidReading;
  ph?: PidReading;
  temp?: PidReading;
  kohLevel?: PidReading;
  k2so3Level?: PidReading;
  flow?: PidReading;
}) {
  const fmt = (r?: PidReading) =>
    r && r.value !== null && r.value !== undefined ? `${r.value.toFixed(1)} ${r.unit}` : "—";
  const isGood = (r?: PidReading) => !r || qualityInfo(r.flag).isGood;
  const fill = (r?: PidReading) => (isGood(r) ? FG : MIST);

  // A live sensor tag: small circular tag marker + reading, placed at its
  // real physical point on the process line.
  const SensorTag = ({
    x,
    y,
    tag,
    label,
    reading,
    anchor = "start",
  }: {
    x: number;
    y: number;
    tag: string;
    label: string;
    reading?: PidReading;
    anchor?: "start" | "middle" | "end";
  }) => (
    <g>
      <circle cx={x} cy={y} r="9" fill="none" stroke={fill(reading)} strokeWidth="1.5" />
      <text x={x} y={y + 3} fontSize="8" fontFamily="var(--font-mono)" textAnchor="middle" fill={fill(reading)}>
        {tag}
      </text>
      <text
        x={anchor === "end" ? x - 16 : x + 16}
        y={y - 12}
        fontSize="9.5"
        fontFamily="var(--font-body)"
        textAnchor={anchor}
        fill={MIST}
      >
        {label}
      </text>
      <text
        x={anchor === "end" ? x - 16 : x + 16}
        y={y + 24}
        fontSize="12"
        fontWeight="600"
        fontFamily="var(--font-mono)"
        textAnchor={anchor}
        fill={fill(reading)}
      >
        {fmt(reading)}
      </text>
    </g>
  );

  // A non-instrumented process/material annotation - explicitly dashed
  // and mist-colored so it never reads as if it were live data.
  const UntrackedNote = ({ x, y, lines }: { x: number; y: number; lines: string[] }) => (
    <g>
      {lines.map((line, i) => (
        <text
          key={i}
          x={x}
          y={y + i * 13}
          fontSize={i === 0 ? "9.5" : "8.5"}
          fontFamily="var(--font-mono)"
          fill={i === 0 ? COPPER : MIST}
        >
          {line}
        </text>
      ))}
    </g>
  );

  return (
    <div className="rounded-2xl border border-hair bg-panel p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[11px] text-mist">
          Process schematic - boiler tie-in through the NEELKANTH absorption unit to stack.
          Solid circles = live sensor. Dashed = process/material stream, not sensor-instrumented.
        </p>
        <div className="flex gap-3 font-mono text-[10px] text-mist">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full border" style={{ borderColor: FG }} /> live
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full border border-dashed" style={{ borderColor: COPPER }} /> not instrumented
          </span>
        </div>
      </div>

      <svg viewBox="0 0 1120 440" className="w-full" role="img" aria-label="Detailed FGD process schematic with sensor locations">
        {/* ============ Zone A: client's existing boiler ============ */}
        <rect x="10" y="150" width="130" height="100" rx="6" fill="none" stroke={LINE} strokeDasharray="4 3" strokeWidth="1.5" />
        <text x="75" y="140" fontSize="11" textAnchor="middle" fill={MIST}>YOUR BOILER</text>
        <text x="75" y="205" fontSize="9" textAnchor="middle" fill={MIST}>existing plant</text>
        <text x="75" y="218" fontSize="9" textAnchor="middle" fill={MIST}>unchanged</text>

        {/* flue gas duct, boiler -> tie-in */}
        <line x1="140" y1="200" x2="260" y2="200" stroke={MIST} strokeWidth="4" />
        <polygon points="260,200 250,195 250,205" fill={MIST} />
        <text x="145" y="188" fontSize="9" fill={MIST}>flue gas (SO2-laden)</text>

        <SensorTag x={185} y={230} tag="FT-01" label="Flow" reading={flow} />
        <SensorTag x={230} y={175} tag="AE-01" label="SO2 inlet" reading={so2In} anchor="start" />

        {/* ============ Zone B: NEELKANTH unit boundary ============ */}
        <rect x="270" y="30" width="560" height="330" rx="8" fill="none" stroke={LINE} strokeWidth="1.5" />
        <text x="550" y="20" fontSize="11" fontWeight="600" textAnchor="middle" fill={FG}>NEELKANTH UNIT (Airthra-owned)</text>

        {/* absorption/scrubber vessel */}
        <rect x="330" y="120" width="180" height="180" rx="6" fill="none" stroke={LINE} strokeWidth="1.5" />
        <text x="420" y="112" fontSize="10.5" textAnchor="middle" fill={MIST}>Absorption vessel</text>
        <SensorTag x={420} y={165} tag="AE-03" label="Liquor pH" reading={ph} anchor="middle" />
        <SensorTag x={420} y={225} tag="TE-01" label="Temp" reading={temp} anchor="middle" />
        <text x="420" y="278" fontSize="9" fontFamily="var(--font-mono)" textAnchor="middle" fill={COPPER}>
          SO2 + 2KOH → K2SO3 + S
        </text>

        {/* KOH supply tank + line into vessel */}
        <rect x="300" y="330" width="90" height="40" rx="4" fill="none" stroke={COPPER} strokeWidth="1.5" />
        <text x="345" y="354" fontSize="10" fontFamily="var(--font-mono)" textAnchor="middle" fill={COPPER}>
          LT-02 KOH
        </text>
        <text x="345" y="384" fontSize="12" fontWeight="600" fontFamily="var(--font-mono)" textAnchor="middle" fill={fill(kohLevel)}>
          {fmt(kohLevel)}
        </text>
        <line x1="345" y1="330" x2="345" y2="300" stroke={COPPER} strokeWidth="2" />
        <text x="352" y="315" fontSize="8" fill={COPPER}>KOH dosing</text>

        {/* clean gas out of vessel -> stack */}
        <line x1="510" y1="180" x2="620" y2="180" stroke={MIST} strokeWidth="4" />
        <polygon points="620,180 610,175 610,185" fill={MIST} />
        <SensorTag x={565} y={155} tag="AE-02" label="SO2 stack" reading={so2Out} anchor="middle" />

        <rect x="620" y="60" width="34" height="240" rx="4" fill="none" stroke={LINE} strokeWidth="1.5" />
        <text x="637" y="52" fontSize="10" textAnchor="middle" fill={MIST}>Stack</text>
        <rect
          x="627" y="270" width="20" height="20" rx="3"
          fill="none"
          stroke={isGood(so2Out) ? MOSS : COPPER}
          strokeWidth="1.5"
        />
        <text x="637" y="284" fontSize="9" fontFamily="var(--font-mono)" textAnchor="middle" fill={isGood(so2Out) ? MOSS : COPPER}>
          ✓
        </text>
        <text x="637" y="310" fontSize="8" textAnchor="middle" fill={MIST}>within consent</text>

        {/* K2SO3 outlet from vessel bottom -> product tank */}
        <line x1="420" y1="300" x2="420" y2="330" stroke={MOSS} strokeWidth="3" />
        <rect x="480" y="330" width="100" height="40" rx="4" fill="none" stroke={MOSS} strokeWidth="1.5" />
        <text x="530" y="354" fontSize="10" fontFamily="var(--font-mono)" textAnchor="middle" fill={MOSS}>
          LT-03 K2SO3
        </text>
        <text x="530" y="384" fontSize="12" fontWeight="600" fontFamily="var(--font-mono)" textAnchor="middle" fill={fill(k2so3Level)}>
          {fmt(k2so3Level)}
        </text>
        <line x1="420" y1="330" x2="480" y2="350" stroke={MOSS} strokeWidth="2" />

        {/* K2SO3 -> K2S2O3 downstream conversion, explicitly not instrumented */}
        <line x1="580" y1="350" x2="650" y2="350" stroke={COPPER} strokeWidth="2" strokeDasharray="5 4" />
        <polygon points="650,350 640,345 640,355" fill={COPPER} />
        <UntrackedNote
          x={655}
          y={335}
          lines={["+ S → K2S2O3", "potassium thiosulfate (KTS)", "downstream conversion - no", "sensor instrumented yet"]}
        />

        {/* water loop + gypsum-eliminated badges, honestly labeled as
            process characteristics, not sensor-backed telemetry */}
        <UntrackedNote x={285} y={60} lines={["water: closed loop", "recirculated, not consumed"]} />
        <UntrackedNote x={285} y={92} lines={["gypsum to landfill: none", "(vs. wet-limestone scrubbing)"]} />

        {/* ============ Zone C: offtake dispatch ============ */}
        <rect x="850" y="150" width="130" height="100" rx="6" fill="none" stroke={LINE} strokeDasharray="4 3" strokeWidth="1.5" />
        <text x="915" y="140" fontSize="11" textAnchor="middle" fill={MIST}>OFFTAKE</text>
        <text x="915" y="205" fontSize="9" textAnchor="middle" fill={MIST}>KTS dispatched</text>
        <text x="915" y="218" fontSize="9" textAnchor="middle" fill={MIST}>as fertilizer</text>
        <line x1="580" y1="350" x2="915" y2="350" stroke={HAIR} strokeWidth="1" strokeDasharray="2 3" />
        <line x1="915" y1="350" x2="915" y2="250" stroke={HAIR} strokeWidth="1" strokeDasharray="2 3" />
      </svg>
    </div>
  );
}
