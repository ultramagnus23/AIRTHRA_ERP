import { qualityInfo } from "@/lib/quality";
import type { QualityFlagText, QualityFlagWire } from "@/lib/types";

/**
 * HARD RULE: never hide a non-good flag, never render it as if it were
 * good data. Always visibly grey + the flag reason text. See
 * lib/quality.ts's module docstring.
 */
export default function FlagBadge({
  flag,
}: {
  flag: QualityFlagText | QualityFlagWire | number | string;
}) {
  const info = qualityInfo(flag);
  if (info.isGood) return null;
  return (
    <span
      className={`ml-2 inline-block rounded-md border px-1.5 py-0.5 font-mono text-[11px] font-medium ${info.badgeClass}`}
      title={`Flagged: ${info.label}`}
    >
      {info.label}
    </span>
  );
}
