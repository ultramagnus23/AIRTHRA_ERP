#!/usr/bin/env python
"""P3: seed the frozen-sensor alarm rule.

Deliberately NOT part of seed/seed.py (that file is owned by an earlier
phase and other phases are concurrently building against it - this task's
instructions say not to touch it). Instead, this is a small standalone,
idempotent script that inserts exactly one global alarm_rules row: a
"frozen sensor" fault detector, expressed as a quality_flag-persistence
variant of expression_type='threshold' (see the module docstring in
workers/alarm_engine.py for why this reuses 'threshold' rather than a
new DB enum value the schema doesn't have).

The rule is global (plant_id = NULL), so it applies to every plant,
including whichever ones other phases create. sensor_id is omitted from
params on purpose, meaning the alarm engine checks *every* sensor in each
plant's manifest for a sustained frozen run - a single sensor is enough to
fire it (see workers/alarm_engine.py:_eval_quality_flag_persistence).

Idempotent: keyed off a stable, deterministic UUID (uuid5 of a fixed
namespace + rule name) so re-running this script is a no-op
(`INSERT ... ON CONFLICT (rule_id) DO NOTHING`) rather than creating
duplicate rules on every run.

Usage:
    .venv/Scripts/python.exe workers/seed_alarm_rules.py

Reads DATABASE_URL from .env (repo root), same convention as
workers/kpi_worker.py / seed/seed.py.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
    sys.exit(1)

# Fixed namespace so the derived rule_id is stable across runs/machines.
_NAMESPACE = uuid.UUID("6f0e6f5a-0b1a-4c2a-9c3d-000000000001")

FROZEN_SENSOR_RULE = {
    "rule_id": str(uuid.uuid5(_NAMESPACE, "frozen_sensor_fault_v1")),
    "plant_id": None,  # global: applies to every plant
    "expression_type": "threshold",
    "params": {
        "quality_flag": "frozen",
        "min_duration_s": 120,
        # sensor_id intentionally omitted -> checked across every sensor
        # in the plant's manifest, see workers/alarm_engine.py.
    },
    "severity": "critical",
    "diagnosis": "Sensor reading frozen - likely wiring fault or transducer failure",
    "suggested_part": "Signal transducer / sensor wiring harness",
    "cooldown_s": 300,
}


def main() -> None:
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO alarm_rules
                    (rule_id, plant_id, expression_type, params, severity,
                     diagnosis, suggested_part, cooldown_s)
                VALUES
                    (:rule_id, :plant_id, :expression_type, CAST(:params AS jsonb), :severity,
                     :diagnosis, :suggested_part, :cooldown_s)
                ON CONFLICT (rule_id) DO NOTHING
                RETURNING rule_id
                """
            ),
            {
                **FROZEN_SENSOR_RULE,
                "params": json.dumps(FROZEN_SENSOR_RULE["params"]),
            },
        )
        inserted = result.first() is not None

    if inserted:
        print(f"[seed_alarm_rules] inserted frozen-sensor rule {FROZEN_SENSOR_RULE['rule_id']}")
    else:
        print(f"[seed_alarm_rules] frozen-sensor rule {FROZEN_SENSOR_RULE['rule_id']} already present (no-op)")


if __name__ == "__main__":
    main()
