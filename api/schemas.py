from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    plant_ids: list[str]


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
    kind: Literal["maintenance", "lab_sample", "note", "alarm_ack"]
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
