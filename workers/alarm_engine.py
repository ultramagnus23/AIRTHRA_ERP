#!/usr/bin/env python
"""P3 alarm engine worker.

Standalone scheduled process (every ALARM_ENGINE_INTERVAL_S seconds,
default 10) that evaluates `alarm_rules` against current `readings`/`kpis`
data and drives a state machine on `alarms`:

    (no active alarm) --condition true--> raised
    raised            --acked via API--> acked   (acked_at/acked_by set by
                                                   api/routers/plant.py's
                                                   POST .../alarms/{id}/ack -
                                                   this worker never acks)
    raised            --stays unacked past ESCALATE_AFTER_S--> escalated
    raised/acked/escalated --condition false--> cleared (cleared_at=now())

"Active" alarm = the most recent alarms row for a given (rule_id,
plant_id) whose state is one of raised/acked/escalated (i.e. not yet
cleared). At most one active alarm per (rule_id, plant_id) is kept open at
a time - alarms carries no sensor_id column (see migrations/versions/
0001_initial_schema.py), so per-rule-per-plant is the finest de-dup grain
the schema affords. Documented deviation, not a bug.

Per-rule cooldown (alarm_rules.cooldown_s): after an alarm for a given
(rule_id, plant_id) clears, the same rule will not re-raise at that plant
until cooldown_s seconds have elapsed since cleared_at. This is the
"don't re-raise within the cooldown window after it clears" requirement.

Supported alarm_rules.expression_type values (CHECK-constrained in the
DB to exactly these three - see 0001_initial_schema.py):

  threshold
    Two sub-modes, distinguished by params content:
      (a) value threshold - params: {"sensor_id": str, "min": number?,
          "max": number?}. Fires when the sensor's latest reading value
          is < min or > max (either bound optional).
      (b) quality-flag persistence - params: {"quality_flag": str,
          "min_duration_s": number, "sensor_id": str? (omit/null = check
          every sensor in the plant's manifest)}. Fires when a sensor has
          an unbroken run of readings all carrying the given quality_flag
          and all carrying the *same value* (the literal "frozen sensor"
          signature - value never moves) spanning at least min_duration_s
          up to the most recent reading. This is how the seeded
          frozen-sensor rule (workers/seed_alarm_rules.py) is expressed;
          reusing expression_type='threshold' rather than inventing a 4th
          DB-enum value, since the schema (owned by P0/P1, not editable
          here) only allows threshold/rolling_z/rate_of_change. Documented
          deviation from a literal "value crosses min/max" reading of the
          PRD's "threshold" description.

  rolling_z
    params: {"sensor_id": str, "window": int (>=2), "z_threshold": number}
    Simple rolling mean/stddev (population stddev) over the last `window`
    readings (most recent inclusive). Fires when
    |latest_value - mean| / stddev > z_threshold. Skipped (no-op) if
    stddev is 0 (no variance -> z is undefined) or fewer than `window`
    samples exist yet.

  rate_of_change
    params: {"sensor_id": str, "max_rate_per_s": number}
    Fires when |delta_value| / delta_t_seconds between the two most
    recent readings exceeds max_rate_per_s.

When a rule fires (and no active alarm already exists for it at that
plant, and cooldown has elapsed), INSERTs into `alarms` with severity,
diagnosis, suggested_part copied verbatim from the rule, state='raised',
raised_at=now().

Global rules (per the schema comment on `alarm_rules`): alarm_rules with
plant_id IS NULL apply to every plant in `plants`. Plant-scoped rules
apply only to their plant_id.

Guardrails (per the P3 task spec):
  - `readings` is read-only here, never mutated (raw ingest data is
    immutable per the platform's global rules).
  - This worker never writes quality_flag='imputed' anywhere - it doesn't
    write to readings/kpis at all, only to `alarms`.
  - No silent failures: each rule's evaluation is wrapped so one rule's
    error is logged loudly (stderr) and does not take down the loop or
    skip other rules, mirroring workers/kpi_worker.py's per-plant
    isolation - but nothing is ever swallowed without a printed error.

Usage:
    .venv/Scripts/python.exe workers/alarm_engine.py [--once]

Reads DATABASE_URL from .env (repo root), same convention as
workers/kpi_worker.py / seed/seed.py. Uses the plain superuser DSN (not
the RLS-scoped tenant/global API roles) - this is an internal, cross-plant
batch job, not a per-user request, exactly like kpi_worker.py.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL is not set (check .env)", file=sys.stderr)
    sys.exit(1)

POLL_INTERVAL_S = int(os.environ.get("ALARM_ENGINE_INTERVAL_S", "10"))

# How long a 'raised' (unacked) alarm stays open before this worker bumps
# it to 'escalated'. Not specified numerically by the PRD excerpt given to
# this phase; chosen as a conservative default and overridable via env for
# tests. Escalation only requires an unacked alarm to still be firing
# (condition still true) at re-evaluation time past this age.
ESCALATE_AFTER_S = int(os.environ.get("ALARM_ENGINE_ESCALATE_AFTER_S", "600"))

_ACTIVE_STATES = ("raised", "acked", "escalated")


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------

# Per-(plant, sensor) reading history pulled into the cycle snapshot.
# Bounds both memory and the frozen-detector's lookback: at a 1 Hz sample
# rate this is ~8 minutes of history per sensor, comfortably covering the
# rolling_z windows and the frozen rule's min_duration_s*3+60 lookback.
# A rule asking for more than this evaluates on what is available - the
# evaluators already report "only N/window samples so far" rather than
# firing on a short window.
SNAPSHOT_ROWS_PER_SENSOR = int(os.environ.get("ALARM_SNAPSHOT_ROWS", "500"))


class FleetSnapshot:
    """One cycle's worth of state for the whole fleet, loaded in a fixed
    number of queries instead of per (rule x plant x sensor).

    WHY THIS EXISTS
    ---------------
    The original shape issued its own queries inside every evaluator, for
    every rule, for every plant. At 7 rules x 100 plants that measured to
    roughly 2,600 round trips per 10-second cycle (~260 q/s) - and the
    frozen-sensor rule was the worst of it, doing one query per sensor per
    plant because it has no sensor_id and must scan the whole manifest.

    This loads the same data in 4 queries total, regardless of fleet size,
    and the evaluators read from memory. Round trips, not row volume, were
    the bottleneck: the data transferred is essentially unchanged.
    """

    def __init__(self, conn: Connection, plant_ids: list[str]):
        self.sensor_ids: dict[str, list[str]] = {p: [] for p in plant_ids}
        self.readings: dict[tuple[str, str], list] = {}
        self.active_alarms: dict[tuple[str, str], dict] = {}
        self.last_cleared: dict[tuple[str, str], datetime] = {}
        if plant_ids:
            self._load(conn, plant_ids)

    def _load(self, conn: Connection, plant_ids: list[str]) -> None:
        for row in conn.execute(
            text("SELECT plant_id, sensor_id FROM sensors WHERE plant_id = ANY(:p) ORDER BY plant_id, sensor_id"),
            {"p": plant_ids},
        ):
            self.sensor_ids.setdefault(row[0], []).append(row[1])

        # ROW_NUMBER over (plant, sensor) rather than N separate LIMIT
        # queries. Rows come back newest-first from the window and are
        # reversed per series below, so callers get oldest -> newest, the
        # order every evaluator already expects.
        for row in conn.execute(
            text(
                """
                SELECT plant_id, sensor_id, ts, value, quality_flag
                FROM (
                    SELECT plant_id, sensor_id, ts, value, quality_flag,
                           ROW_NUMBER() OVER (
                               PARTITION BY plant_id, sensor_id ORDER BY ts DESC
                           ) AS rn
                    FROM readings
                    WHERE plant_id = ANY(:p)
                ) ranked
                WHERE rn <= :lim
                ORDER BY plant_id, sensor_id, ts ASC
                """
            ),
            {"p": plant_ids, "lim": SNAPSHOT_ROWS_PER_SENSOR},
        ).mappings():
            self.readings.setdefault((row["plant_id"], row["sensor_id"]), []).append(row)

        for row in conn.execute(
            text(
                """
                SELECT DISTINCT ON (rule_id, plant_id)
                       rule_id, plant_id, alarm_id, state, raised_at, acked_at
                FROM alarms
                WHERE plant_id = ANY(:p) AND state = ANY(:states)
                ORDER BY rule_id, plant_id, raised_at DESC
                """
            ),
            {"p": plant_ids, "states": list(_ACTIVE_STATES)},
        ).mappings():
            self.active_alarms[(str(row["rule_id"]), row["plant_id"])] = dict(row)

        for row in conn.execute(
            text(
                """
                SELECT DISTINCT ON (rule_id, plant_id) rule_id, plant_id, cleared_at
                FROM alarms
                WHERE plant_id = ANY(:p) AND state = 'cleared'
                ORDER BY rule_id, plant_id, cleared_at DESC
                """
            ),
            {"p": plant_ids},
        ).mappings():
            self.last_cleared[(str(row["rule_id"]), row["plant_id"])] = row["cleared_at"]

    # -- accessors mirroring the old per-query helpers ----------------

    def plant_sensor_ids(self, plant_id: str) -> list[str]:
        return self.sensor_ids.get(plant_id, [])

    def latest_reading(self, plant_id: str, sensor_id: str):
        series = self.readings.get((plant_id, sensor_id))
        return series[-1] if series else None

    def recent_readings(self, plant_id: str, sensor_id: str, limit: int):
        series = self.readings.get((plant_id, sensor_id), [])
        return series[-limit:] if limit else []

    def readings_since(self, plant_id: str, sensor_id: str, since: datetime):
        return [r for r in self.readings.get((plant_id, sensor_id), []) if r["ts"] >= since]

    def active_alarm(self, rule_id, plant_id: str):
        return self.active_alarms.get((str(rule_id), plant_id))

    def cleared_at(self, rule_id, plant_id: str):
        return self.last_cleared.get((str(rule_id), plant_id))




# ---------------------------------------------------------------------------
# Condition evaluation - each returns (fired: bool, detail: str)
# ---------------------------------------------------------------------------

def _eval_value_threshold(snap: FleetSnapshot, plant_id: str, params: dict) -> tuple[bool, str]:
    sensor_id = params.get("sensor_id")
    if not sensor_id:
        return False, "threshold rule missing sensor_id"
    row = snap.latest_reading(plant_id, sensor_id)
    if row is None or row["value"] is None:
        return False, f"no readings yet for {sensor_id}"
    value = row["value"]
    lo = params.get("min")
    hi = params.get("max")
    if lo is not None and value < lo:
        return True, f"{sensor_id}={value} < min={lo}"
    if hi is not None and value > hi:
        return True, f"{sensor_id}={value} > max={hi}"
    return False, f"{sensor_id}={value} within [{lo}, {hi}]"


def _eval_quality_flag_persistence(snap: FleetSnapshot, plant_id: str, params: dict) -> tuple[bool, str]:
    target_flag = params.get("quality_flag")
    min_duration_s = params.get("min_duration_s")
    if not target_flag or not min_duration_s:
        return False, "quality_flag-persistence rule missing quality_flag/min_duration_s"

    sensor_id = params.get("sensor_id")
    sensor_ids = [sensor_id] if sensor_id else snap.plant_sensor_ids(plant_id)

    now = datetime.now(timezone.utc)
    # Widened lookback (well beyond min_duration_s) so the "contiguous run"
    # scan below is never truncated by the query window itself - the
    # actual duration requirement is enforced by the run-length check, not
    # by this window's edge. Avoids a fragile off-by-a-few-seconds failure
    # mode where evaluation-time jitter between "now" here and whenever the
    # fixture/rows were written trims the window right at the boundary.
    since = now - timedelta(seconds=float(min_duration_s) * 3 + 60)

    for sid in sensor_ids:
        rows = snap.readings_since(plant_id, sid, since)  # oldest -> newest
        if not rows:
            continue
        latest = rows[-1]
        if latest["quality_flag"] != target_flag:
            continue  # most recent reading isn't even flagged - not currently frozen

        # Walk backwards from the latest reading while quality_flag and
        # value stay identical, to find how far back the unbroken frozen
        # run extends.
        run_value = latest["value"]
        run_start_ts = latest["ts"]
        for row in reversed(rows):
            if row["quality_flag"] == target_flag and row["value"] == run_value:
                run_start_ts = row["ts"]
            else:
                break

        span_s = (latest["ts"] - run_start_ts).total_seconds()
        if span_s >= float(min_duration_s):
            return True, (
                f"{sid}: quality_flag='{target_flag}' with constant value={run_value} "
                f"for {span_s:.0f}s (>= {min_duration_s}s)"
            )
    return False, f"no sensor showed a sustained '{target_flag}' run >= {min_duration_s}s"


def _eval_threshold(snap: FleetSnapshot, plant_id: str, params: dict) -> tuple[bool, str]:
    if params.get("quality_flag"):
        return _eval_quality_flag_persistence(snap, plant_id, params)
    return _eval_value_threshold(snap, plant_id, params)


def _eval_rolling_z(snap: FleetSnapshot, plant_id: str, params: dict) -> tuple[bool, str]:
    sensor_id = params.get("sensor_id")
    window = int(params.get("window", 0) or 0)
    z_threshold = params.get("z_threshold")
    if not sensor_id or window < 2 or z_threshold is None:
        return False, "rolling_z rule missing sensor_id/window(>=2)/z_threshold"

    rows = snap.recent_readings(plant_id, sensor_id, window)
    values = [r["value"] for r in rows if r["value"] is not None]
    if len(values) < window:
        return False, f"{sensor_id}: only {len(values)}/{window} samples so far"

    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stddev = variance ** 0.5
    if stddev == 0:
        return False, f"{sensor_id}: stddev=0 over last {window} samples, z undefined"

    latest = values[-1]
    z = (latest - mean) / stddev
    if abs(z) > float(z_threshold):
        return True, f"{sensor_id}: z={z:.2f} exceeds threshold={z_threshold} (mean={mean:.3f}, stddev={stddev:.3f})"
    return False, f"{sensor_id}: z={z:.2f} within threshold={z_threshold}"


def _eval_rate_of_change(snap: FleetSnapshot, plant_id: str, params: dict) -> tuple[bool, str]:
    sensor_id = params.get("sensor_id")
    max_rate = params.get("max_rate_per_s")
    if not sensor_id or max_rate is None:
        return False, "rate_of_change rule missing sensor_id/max_rate_per_s"

    rows = snap.recent_readings(plant_id, sensor_id, 2)
    if len(rows) < 2 or rows[0]["value"] is None or rows[1]["value"] is None:
        return False, f"{sensor_id}: fewer than 2 samples yet"

    prev, latest = rows[0], rows[1]
    dt = (latest["ts"] - prev["ts"]).total_seconds()
    if dt <= 0:
        return False, f"{sensor_id}: non-positive dt between samples"

    rate = (latest["value"] - prev["value"]) / dt
    if abs(rate) > float(max_rate):
        return True, f"{sensor_id}: rate={rate:.4f}/s exceeds max={max_rate}/s"
    return False, f"{sensor_id}: rate={rate:.4f}/s within max={max_rate}/s"


_EVALUATORS = {
    "threshold": _eval_threshold,
    "rolling_z": _eval_rolling_z,
    "rate_of_change": _eval_rate_of_change,
}


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------



def _raise_alarm(conn: Connection, rule: dict, plant_id: str, now: datetime) -> str:
    row = conn.execute(
        text(
            """
            INSERT INTO alarms (plant_id, rule_id, severity, state, raised_at, diagnosis, suggested_part)
            VALUES (:plant_id, :rule_id, :severity, 'raised', :raised_at, :diagnosis, :suggested_part)
            RETURNING alarm_id
            """
        ),
        {
            "plant_id": plant_id,
            "rule_id": rule["rule_id"],
            "severity": rule["severity"],
            "raised_at": now,
            "diagnosis": rule["diagnosis"],
            "suggested_part": rule["suggested_part"],
        },
    ).first()
    return str(row[0])


def _clear_alarm(conn: Connection, alarm_id, now: datetime) -> None:
    conn.execute(
        text("UPDATE alarms SET state = 'cleared', cleared_at = :now WHERE alarm_id = :id"),
        {"now": now, "id": alarm_id},
    )


def _escalate_alarm(conn: Connection, alarm_id, now: datetime) -> None:
    conn.execute(
        text("UPDATE alarms SET state = 'escalated' WHERE alarm_id = :id"),
        {"id": alarm_id},
    )


def process_rule(conn: Connection, snap: FleetSnapshot, rule: dict, plant_ids: list[str], now: datetime) -> list[str]:
    """Evaluates one rule against every plant it applies to. Returns a list
    of short log lines describing any state transitions made."""
    evaluator = _EVALUATORS.get(rule["expression_type"])
    if evaluator is None:
        # Unreachable given the DB CHECK constraint, but never fail silently.
        raise ValueError(f"unsupported expression_type '{rule['expression_type']}' on rule {rule['rule_id']}")

    targets = [rule["plant_id"]] if rule["plant_id"] else plant_ids
    log_lines: list[str] = []

    for plant_id in targets:
        fired, detail = evaluator(snap, plant_id, rule["params"] or {})
        active = snap.active_alarm(rule["rule_id"], plant_id)

        if fired:
            if active is None:
                last_cleared = snap.cleared_at(rule["rule_id"], plant_id)
                cooldown_s = rule["cooldown_s"] or 0
                if last_cleared is not None and (now - last_cleared).total_seconds() < cooldown_s:
                    log_lines.append(
                        f"[{plant_id}] rule {rule['rule_id']} condition true but in cooldown "
                        f"({(now - last_cleared).total_seconds():.0f}s/{cooldown_s}s) - {detail}"
                    )
                    continue
                alarm_id = _raise_alarm(conn, rule, plant_id, now)
                log_lines.append(f"[{plant_id}] RAISED alarm {alarm_id} for rule {rule['rule_id']} - {detail}")
            else:
                if (
                    active["state"] == "raised"
                    and (now - active["raised_at"]).total_seconds() > ESCALATE_AFTER_S
                ):
                    _escalate_alarm(conn, active["alarm_id"], now)
                    log_lines.append(
                        f"[{plant_id}] ESCALATED alarm {active['alarm_id']} for rule {rule['rule_id']} "
                        f"(unacked > {ESCALATE_AFTER_S}s) - {detail}"
                    )
        else:
            if active is not None:
                _clear_alarm(conn, active["alarm_id"], now)
                log_lines.append(f"[{plant_id}] CLEARED alarm {active['alarm_id']} for rule {rule['rule_id']} - {detail}")

    return log_lines


def run_once(engine: Engine) -> None:
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        plant_ids = [r[0] for r in conn.execute(text("SELECT plant_id FROM plants ORDER BY plant_id")).fetchall()]
        rules = conn.execute(
            text(
                """
                SELECT rule_id, plant_id, expression_type, params, severity,
                       diagnosis, suggested_part, cooldown_s
                FROM alarm_rules
                ORDER BY rule_id
                """
            )
        ).mappings().all()

        # One fleet-wide read per cycle, inside the same transaction as the
        # rule/plant load so every rule is evaluated against a consistent
        # view. Previously each evaluator queried for itself, per rule, per
        # plant - see FleetSnapshot's docstring for the measured cost.
        snap = FleetSnapshot(conn, plant_ids)

    for rule in rules:
        try:
            with engine.begin() as conn:
                lines = process_rule(conn, snap, dict(rule), plant_ids, now)
            for line in lines:
                print(f"[alarm_engine] {line}")
        except Exception as exc:  # never let one rule's failure kill the loop; never swallow silently
            print(f"[alarm_engine] ERROR evaluating rule {rule['rule_id']}: {exc}", file=sys.stderr)


def main() -> None:
    once = "--once" in sys.argv
    engine = create_engine(DATABASE_URL, future=True)
    print(f"[alarm_engine] starting (interval={POLL_INTERVAL_S}s, once={once})")
    if once:
        run_once(engine)
        return
    while True:
        run_once(engine)
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
