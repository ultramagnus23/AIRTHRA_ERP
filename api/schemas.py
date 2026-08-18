from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # Bounded so an unauthenticated caller can't force arbitrarily large
    # request bodies (or arbitrarily expensive bcrypt input) through the
    # one endpoint that accepts traffic before any auth check. 254 is the
    # RFC 5321 maximum email length; the password cap is well above any
    # real passphrase but far below a useful abuse payload.
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    plant_ids: list[str]
    department: str | None = None


class ReadingOut(BaseModel):
    sensor_id: str
    ts: datetime
    value: float | None
    quality_flag: str


class RawHistoryPoint(BaseModel):
    sensor_id: str
    ts: datetime
    value: float | None
    quality_flag: str


class AggHistoryPoint(BaseModel):
    sensor_id: str
    bucket: datetime
    avg_value: float | None
    min_value: float | None
    max_value: float | None
    sample_count: int
    flagged_count: int


class HistoryResponse(BaseModel):
    plant_id: str
    resolution: str
    start: datetime
    end: datetime
    points: list[dict[str, Any]]


class KpiOut(BaseModel):
    ts: datetime
    kpi_name: str
    value: float | None
    quality_flag: str


class EventCreate(BaseModel):
    # Mirrors the operator_events_kind_check constraint (migration
    # 0006_ml_ground_truth). The specific kinds below exist because these
    # rows are ML ground truth: a model cannot learn that a step change in
    # solvent chemistry was a KOH top-up rather than an anomaly unless the
    # human action is a *label*, not prose in a note field. The original
    # four generic kinds are retained for historical rows.
    kind: Literal[
        "maintenance",
        "lab_sample",
        "note",
        "alarm_ack",
        "koh_added",
        "tote_changeout",
        "phe_cleaned",
        "stator_changed",
        "demister_cleaned",
        "fuel_change",
        "boiler_trip",
        "emergency_trip",
        "sensor_calibration",
        "purge_cycle",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class EventOut(BaseModel):
    event_id: str
    plant_id: str
    user_id: str | None
    ts: datetime
    kind: str
    payload: dict[str, Any]


class AlarmAckOut(BaseModel):
    alarm_id: str
    plant_id: str
    state: str
    acked_at: datetime | None
    acked_by: str | None
