// Quality-flag presentation helpers.
//
// HARD PLATFORM RULE (do not relax this anywhere it's used): a reading
// whose quality_flag isn't "good" must always render visibly
// grey/distinguished with its flag reason shown next to it - never
// hidden, never styled as if it were good data. This exists for
// billing/compliance raw-data-integrity reasons (see shared/quality.py),
// not as a style nicety.
import type { QualityFlagText, QualityFlagWire } from "./types";

export interface QualityInfo {
  isGood: boolean;
  label: string;
  /** Tailwind classes for the value text/badge when NOT good. */
  badgeClass: string;
}

// shared/quality.py wire codes, mirrored here (0 good .. 4 imputed).
const WIRE_LABELS: Record<QualityFlagWire, QualityFlagText> = {
  0: "good",
  1: "comm_error",
  2: "out_of_range",
  3: "frozen",
  4: "imputed",
};

const TEXT_LABELS: Record<QualityFlagText, string> = {
  good: "Good",
  comm_error: "Comm error",
  out_of_range: "Out of range",
  frozen: "Frozen value",
  imputed: "Imputed",
};

export function normalizeQualityFlag(
  flag: QualityFlagText | QualityFlagWire | number | string,
): QualityFlagText {
  if (typeof flag === "number") {
    return WIRE_LABELS[(flag as QualityFlagWire) ?? 0] ?? "comm_error";
  }
  if (typeof flag === "string" && /^[0-4]$/.test(flag)) {
    return WIRE_LABELS[Number(flag) as QualityFlagWire] ?? "comm_error";
  }
  if (flag in TEXT_LABELS) {
    return flag as QualityFlagText;
  }
  return "comm_error";
}

export function qualityInfo(
  flag: QualityFlagText | QualityFlagWire | number | string,
): QualityInfo {
  const norm = normalizeQualityFlag(flag);
  const isGood = norm === "good";
  return {
    isGood,
    label: TEXT_LABELS[norm],
    badgeClass: isGood
      ? "text-moss bg-transparent border-line"
      : "text-mist bg-panel border-line",
  };
}
