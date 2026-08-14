// Typed client-side API wrapper.
//
// Every call here hits Next.js's own `/api/backend/*` route (same
// origin, so the httpOnly auth cookie is sent automatically by the
// browser) which then forwards to FastAPI with the JWT attached as an
// Authorization header. See app/api/backend/[...path]/route.ts for the
// proxy itself and lib/session.ts for why it's structured this way.
//
// Global rule this file exists partly to protect: NEVER compute KPIs,
// SO2 efficiency, resolution selection, or any other derived number in
// here or in a component - fetch and render only, all math already
// happened server-side (P2/P3).
import type {
  AlarmsResponse,
  CurrentReadingsResponse,
  EventCreateBody,
  EventOut,
  HistoryResponse,
  KpisResponse,
  LoginResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/backend${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? "login failed");
  }
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
}

export function getCurrentReadings(plantId: string) {
  return request<CurrentReadingsResponse>(`/api/v1/${plantId}/current`);
}

export function getHistory(
  plantId: string,
  params: { start: string; end: string; sensors?: string[]; resolution?: string },
) {
  const qs = new URLSearchParams({ start: params.start, end: params.end });
  if (params.sensors?.length) qs.set("sensors", params.sensors.join(","));
  if (params.resolution) qs.set("resolution", params.resolution);
  return request<HistoryResponse>(`/api/v1/${plantId}/history?${qs.toString()}`);
}

export function getKpis(plantId: string, params?: { start?: string; end?: string }) {
  const qs = new URLSearchParams();
  if (params?.start) qs.set("start", params.start);
  if (params?.end) qs.set("end", params.end);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<KpisResponse>(`/api/v1/${plantId}/kpis${suffix}`);
}

export function getAlarms(plantId: string, state?: string) {
  const qs = state ? `?state=${encodeURIComponent(state)}` : "";
  return request<AlarmsResponse>(`/api/v1/${plantId}/alarms${qs}`);
}

export function ackAlarm(plantId: string, alarmId: string) {
  return request(`/api/v1/${plantId}/alarms/${alarmId}/ack`, { method: "POST" });
}

export function postEvent(plantId: string, body: EventCreateBody) {
  return request<EventOut>(`/api/v1/${plantId}/event`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
