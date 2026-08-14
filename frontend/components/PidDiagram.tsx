"use client";

import { qualityInfo } from "@/lib/quality";
import type { QualityFlagText, QualityFlagWire } from "@/lib/types";

export interface PidReading {
  value: number | null;
  flag: QualityFlagText | QualityFlagWire | number | string;
  unit: string;
}

/**
 * Simple, honest P&ID mimic - a basic flow diagram (inlet -> scrubber
 * vessel -> stack) with the live readings overlaid as labels. This is
 * NOT a real Piping & Instrumentation Diagram: it's a schematic
 * placeholder built for this scaffold. A real P&ID would come from
 * Airthra's actual engineering drawings (see the "P&ID SVG mimic" note
 * in the brief) and should replace this component wholesale rather
 * than be patched incrementally.
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
  const fill = (r?: PidReading) => (isGood(r) ? "#0f172a" : "#94a3b8");

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="mb-2 text-xs text-slate-400">
        Schematic placeholder — not a scale engineering P&ID. Replace with Airthra&apos;s
        real drawing when available.
      </p>
      <svg viewBox="0 0 780 260" className="w-full" role="img" aria-label="Simplified FGD process flow">
        {/* flue gas inlet duct */}
        <line x1="10" y1="60" x2="150" y2="60" stroke="#64748b" strokeWidth="6" />
        <text x="10" y="45" fontSize="12" fill="#475569">Flue gas in</text>
        <text x="10" y="80" fontSize="13" fontWeight="600" fill={fill(so2In)}>
          SO2: {fmt(so2In)}
        </text>

        {/* scrubber vessel */}
        <rect x="150" y="20" width="180" height="180" rx="10" fill="#eef2f7" stroke="#334155" strokeWidth="2" />
        <text x="240" y="15" fontSize="12" textAnchor="middle" fill="#334155">Scrubber vessel</text>
        <text x="240" y="100" fontSize="13" fontWeight="600" textAnchor="middle" fill={fill(ph)}>
          pH: {fmt(ph)}
        </text>
        <text x="240" y="120" fontSize="13" fontWeight="600" textAnchor="middle" fill={fill(temp)}>
          Temp: {fmt(temp)}
        </text>
        <text x="240" y="140" fontSize="13" fontWeight="600" textAnchor="middle" fill={fill(flow)}>
          Flow: {fmt(flow)}
        </text>

        {/* KOH tank */}
        <rect x="140" y="210" width="90" height="40" rx="6" fill="#e0f2fe" stroke="#0369a1" strokeWidth="1.5" />
        <text x="185" y="234" fontSize="11" textAnchor="middle" fill="#0369a1">
          KOH {fmt(kohLevel)}
        </text>
        <line x1="185" y1="200" x2="185" y2="210" stroke="#0369a1" strokeWidth="2" />

        {/* K2SO3 tank */}
        <rect x="260" y="210" width="90" height="40" rx="6" fill="#fef3c7" stroke="#a16207" strokeWidth="1.5" />
        <text x="305" y="234" fontSize="11" textAnchor="middle" fill="#a16207">
          K2SO3 {fmt(k2so3Level)}
        </text>
        <line x1="305" y1="200" x2="305" y2="210" stroke="#a16207" strokeWidth="2" />

        {/* stack outlet duct */}
        <line x1="330" y1="60" x2="470" y2="60" stroke="#64748b" strokeWidth="6" />
        <text x="470" y="45" fontSize="12" fill="#475569">Stack</text>
        <text x="345" y="80" fontSize="13" fontWeight="600" fill={fill(so2Out)}>
          SO2: {fmt(so2Out)}
        </text>

        {/* stack */}
        <rect x="470" y="10" width="30" height="150" fill="#cbd5e1" stroke="#334155" strokeWidth="2" />
        <polygon points="470,10 500,10 485,-10" fill="none" />
      </svg>
    </div>
  );
}
