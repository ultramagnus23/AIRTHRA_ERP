"""Quality-flag semantics shared between edge/ and ingest/.

Global rule (per P1 spec): quality_flag semantics are
    0 = good
    1 = comm error / timeout
    2 = out of range
    3 = frozen / stuck
    4 = imputed (NOT used in P1 - a later ML feature path)

The `readings.quality_flag` / `kpis.quality_flag` columns are `text` with
`CHECK (quality_flag IN ('good','comm_error','out_of_range','frozen',
'imputed'))` (widened in migrations/versions/0003_quality_flag_fidelity.py
from an earlier 4-value enum that collapsed comm_error/out_of_range into a
single 'bad' value - that lost exactly the distinction the alarm engine
needs to diagnose a fault correctly). The wire format (MQTT payloads, the
SQLite buffer, dead-letter raw_payload) uses the integer codes above; the
mapping to the DB text enum below is now lossless.
"""
from __future__ import annotations

GOOD = 0
COMM_ERROR = 1
OUT_OF_RANGE = 2
FROZEN = 3
IMPUTED = 4  # unused in P1

_LABELS = {
    GOOD: "good",
    COMM_ERROR: "comm_error",
    OUT_OF_RANGE: "out_of_range",
    FROZEN: "frozen",
    IMPUTED: "imputed",
}

# int wire code -> `readings`/`kpis` quality_flag text enum value (lossless)
_DB_MAP = {
    GOOD: "good",
    COMM_ERROR: "comm_error",
    OUT_OF_RANGE: "out_of_range",
    FROZEN: "frozen",
    IMPUTED: "imputed",
}


def label(code: int) -> str:
    return _LABELS.get(code, f"unknown({code})")


def to_db_enum(code: int) -> str:
    if code not in _DB_MAP:
        raise ValueError(f"unrecognized quality_flag code: {code!r}")
    return _DB_MAP[code]
