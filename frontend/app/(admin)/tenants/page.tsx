"use client";

import { Fragment, useEffect, useState } from "react";
import {
  listAdminPlants,
  createPlant,
  listAdminUsers,
  createUser,
  reinviteUser,
  patchUser,
  getAuditLog,
  AdminApiError,
} from "@/lib/admin-api";
import type {
  AdminPlantSummary,
  AdminUserSummary,
  AuditLogEntry,
  DbRole,
  SensorInput,
} from "@/lib/admin-types";
import type { Department } from "@/lib/types";
import DocumentsPanel from "@/components/admin/DocumentsPanel";

const DEPARTMENTS: Department[] = ["finance", "procurement", "engineering", "sales", "logistics"];

// Tenant onboarding: the real replacement for "run seed/seed.py by hand
// against production" (see SHIPPING.md 0.2). Every mutation here writes
// an audit_log row (api/routers/admin_tenants.py) - visible at the
// bottom of this page, not a separate hidden surface.
//
// The invite link is shown exactly once, inline, right after creating a
// user - the API never stores or re-exposes the raw token (only its
// hash), so this page is the only place it's ever visible. Copy it now
// or use "Re-invite" later, which issues a fresh one.

const DB_ROLES: { value: DbRole; label: string; isPlantRole: boolean; isDeptRole: boolean }[] = [
  { value: "plant_operator", label: "Plant operator", isPlantRole: true, isDeptRole: false },
  { value: "plant_viewer", label: "Plant viewer", isPlantRole: true, isDeptRole: false },
  { value: "plant_admin", label: "Plant admin", isPlantRole: true, isDeptRole: false },
  { value: "dept_user", label: "Department login", isPlantRole: false, isDeptRole: true },
  { value: "global_read", label: "Airthra staff (read-only)", isPlantRole: false, isDeptRole: false },
  { value: "global_admin", label: "Airthra staff (admin)", isPlantRole: false, isDeptRole: false },
];

function fmtTs(ts: string) {
  return new Date(ts).toLocaleString();
}

export default function TenantsPage() {
  const [plants, setPlants] = useState<AdminPlantSummary[]>([]);
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function refresh() {
    try {
      const [p, u, a] = await Promise.all([listAdminPlants(), listAdminUsers(), getAuditLog(30)]);
      setPlants(p.plants);
      setUsers(u.users);
      setAuditLog(a.entries);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof AdminApiError ? err.message : "failed to load tenant data");
    }
  }

  useEffect(() => {
    void (async () => {
      await refresh();
    })();
  }, []);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="font-display text-2xl font-light text-fg">Tenants</h1>
        <p className="text-sm text-mist">
          Add plants and users, and hand out invite links. Every action here is written to the
          audit log below.
        </p>
      </div>

      {loadError && (
        <p className="rounded-xl border border-rust/40 bg-rust/10 px-3 py-2 text-sm text-rust">
          {loadError}
        </p>
      )}

      <NewPlantSection plants={plants} onCreated={refresh} />
      <NewUserSection users={users} plants={plants} onCreated={refresh} />
      <AuditLogSection entries={auditLog} />
    </div>
  );
}

// --------------------------------------------------------------------
// Plants
// --------------------------------------------------------------------

function emptySensor(): SensorInput {
  return { sensor_id: "", tag: "", kind: "", unit: "" };
}

function NewPlantSection({
  plants,
  onCreated,
}: {
  plants: AdminPlantSummary[];
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [plantId, setPlantId] = useState("");
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [boilerCapacity, setBoilerCapacity] = useState("");
  const [fuelType, setFuelType] = useState("");
  const [sensors, setSensors] = useState<SensorInput[]>([emptySensor()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [docsOpen, setDocsOpen] = useState<string | null>(null);

  function updateSensor(i: number, patch: Partial<SensorInput>) {
    setSensors((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const cleanSensors = sensors.filter((s) => s.sensor_id.trim() !== "");
      const res = await createPlant({
        plant_id: plantId.trim(),
        name: name.trim(),
        lat: lat.trim() ? Number(lat) : null,
        lon: lon.trim() ? Number(lon) : null,
        boiler_capacity_tpd: boilerCapacity.trim() ? Number(boilerCapacity) : null,
        fuel_type_primary: fuelType.trim() || null,
        sensors: cleanSensors,
      });
      setSuccess(`Created ${res.plant_id} with ${res.sensors_created} sensor(s).`);
      setPlantId("");
      setName("");
      setLat("");
      setLon("");
      setBoilerCapacity("");
      setFuelType("");
      setSensors([emptySensor()]);
      setOpen(false);
      onCreated();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to create plant");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="rounded-2xl border border-hair bg-panel p-4"
      style={{ boxShadow: "var(--shadow-sm)" }}
    >
      <div className="flex items-baseline justify-between">
        <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">
          Plants ({plants.length})
        </h2>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="air-track rounded-full border border-line px-3 py-1.5 text-sm text-fg hover:border-copper"
        >
          {open ? "Cancel" : "+ New plant"}
        </button>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
            <tr>
              <th className="px-2 py-2">Plant</th>
              <th className="px-2 py-2">Sensors</th>
              <th className="px-2 py-2">Users</th>
              <th className="px-2 py-2">Commissioned</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {plants.map((p) => (
              <Fragment key={p.plant_id}>
                <tr className="border-b border-hair last:border-0">
                  <td className="px-2 py-2">
                    <div className="font-medium text-fg">{p.name}</div>
                    <div className="font-mono text-xs text-mist">{p.plant_id}</div>
                  </td>
                  <td className="px-2 py-2 font-mono text-fg">{p.sensor_count}</td>
                  <td className="px-2 py-2 font-mono text-fg">{p.user_count}</td>
                  <td className="px-2 py-2 font-mono text-xs text-mist">
                    {p.commissioning_date ?? "—"}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => setDocsOpen((cur) => (cur === p.plant_id ? null : p.plant_id))}
                      className="text-xs text-copper hover:text-fg"
                    >
                      {docsOpen === p.plant_id ? "hide docs" : "docs"}
                    </button>
                  </td>
                </tr>
                {docsOpen === p.plant_id && (
                  <tr className="border-b border-hair last:border-0">
                    <td colSpan={5} className="px-2 py-3">
                      <DocumentsPanel entityType="plant" entityId={p.plant_id} title={`${p.plant_id} documents`} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {plants.length === 0 && (
              <tr>
                <td colSpan={5} className="px-2 py-6 text-center text-mist">
                  No plants yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <form
          onSubmit={handleSubmit}
          className="air-rise mt-4 flex flex-col gap-3 rounded-xl border border-line bg-midnight p-4"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Plant ID (slug)">
              <input
                required
                pattern="[a-z0-9_]+"
                title="lowercase letters, digits, underscore"
                value={plantId}
                onChange={(e) => setPlantId(e.target.value)}
                placeholder="pune_pilot_02"
                className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
              />
            </Field>
            <Field label="Name">
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Pune Pilot Plant 02"
                className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
              />
            </Field>
            <Field label="Latitude">
              <input value={lat} onChange={(e) => setLat(e.target.value)} className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none" />
            </Field>
            <Field label="Longitude">
              <input value={lon} onChange={(e) => setLon(e.target.value)} className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none" />
            </Field>
            <Field label="Boiler capacity (TPD)">
              <input
                value={boilerCapacity}
                onChange={(e) => setBoilerCapacity(e.target.value)}
                className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
              />
            </Field>
            <Field label="Primary fuel">
              <input value={fuelType} onChange={(e) => setFuelType(e.target.value)} className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none" />
            </Field>
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="font-mono text-xs text-mist uppercase">Sensor manifest</span>
              <button
                type="button"
                onClick={() => setSensors((prev) => [...prev, emptySensor()])}
                className="text-xs text-copper hover:text-fg"
              >
                + add sensor
              </button>
            </div>
            <div className="flex flex-col gap-2">
              {sensors.map((s, i) => (
                <div key={i} className="grid grid-cols-5 gap-2">
                  <input
                    placeholder="sensor_id"
                    value={s.sensor_id}
                    onChange={(e) => updateSensor(i, { sensor_id: e.target.value })}
                    className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
                  />
                  <input
                    placeholder="tag (AT-01)"
                    value={s.tag}
                    onChange={(e) => updateSensor(i, { tag: e.target.value })}
                    className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
                  />
                  <input
                    placeholder="kind"
                    value={s.kind}
                    onChange={(e) => updateSensor(i, { kind: e.target.value })}
                    className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
                  />
                  <input
                    placeholder="unit"
                    value={s.unit}
                    onChange={(e) => updateSensor(i, { unit: e.target.value })}
                    className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setSensors((prev) => prev.filter((_, idx) => idx !== i))}
                    className="text-xs text-mist hover:text-rust"
                  >
                    remove
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={busy}
              className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
            >
              {busy ? "Creating…" : "Create plant"}
            </button>
            {error && <span className="text-sm text-rust">{error}</span>}
          </div>
        </form>
      )}
      {success && <p className="mt-2 font-mono text-xs text-moss">{success}</p>}
    </section>
  );
}

// --------------------------------------------------------------------
// Users + invites
// --------------------------------------------------------------------

function NewUserSection({
  users,
  plants,
  onCreated,
}: {
  users: AdminUserSummary[];
  plants: AdminPlantSummary[];
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<DbRole>("plant_operator");
  const [plantIds, setPlantIds] = useState<string[]>([]);
  const [department, setDepartment] = useState<Department>("finance");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<{ email: string; url: string } | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  const isPlantRole = DB_ROLES.find((r) => r.value === role)?.isPlantRole ?? false;
  const isDeptRole = DB_ROLES.find((r) => r.value === role)?.isDeptRole ?? false;

  function toOrigin(token: string) {
    return `${window.location.origin}/invite/${token}`;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await createUser({
        email: email.trim(),
        role,
        plant_ids: isPlantRole ? plantIds : [],
        department: isDeptRole ? department : null,
      });
      setInviteLink({ email: res.email, url: toOrigin(res.invite_token) });
      setEmail("");
      setPlantIds([]);
      setOpen(false);
      onCreated();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to create user");
    } finally {
      setBusy(false);
    }
  }

  async function handleReinvite(userId: string, userEmail: string) {
    try {
      const res = await reinviteUser(userId);
      setInviteLink({ email: userEmail, url: toOrigin(res.invite_token) });
      onCreated();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to re-invite");
    }
  }

  const [editingId, setEditingId] = useState<string | null>(null);
  const [toggleBusyId, setToggleBusyId] = useState<string | null>(null);

  async function handleToggleActive(u: AdminUserSummary) {
    setToggleBusyId(u.user_id);
    try {
      await patchUser(u.user_id, { is_active: !u.is_active });
      onCreated();
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : "failed to update user");
    } finally {
      setToggleBusyId(null);
    }
  }

  async function copyLink() {
    if (!inviteLink) return;
    try {
      await navigator.clipboard.writeText(inviteLink.url);
      setCopyStatus("Copied.");
    } catch {
      setCopyStatus("Copy failed — select and copy the link manually.");
    }
    setTimeout(() => setCopyStatus(null), 3000);
  }

  return (
    <section
      className="rounded-2xl border border-hair bg-panel p-4"
      style={{ boxShadow: "var(--shadow-sm)" }}
    >
      <div className="flex items-baseline justify-between">
        <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">
          Users ({users.length})
        </h2>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="air-track rounded-full border border-line px-3 py-1.5 text-sm text-fg hover:border-copper"
        >
          {open ? "Cancel" : "+ New user"}
        </button>
      </div>

      {inviteLink && (
        <div className="air-rise mt-3 flex flex-col gap-2 rounded-xl border border-copper/40 bg-copper/10 p-3">
          <p className="text-sm text-fg">
            Invite link for <span className="font-mono text-copper">{inviteLink.email}</span> —
            shown once, share it now:
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="flex-1 truncate rounded-lg border border-line bg-midnight px-2 py-1.5 font-mono text-xs text-fg">
              {inviteLink.url}
            </code>
            <button
              type="button"
              onClick={copyLink}
              className="rounded-full border border-line px-3 py-1.5 text-xs text-fg hover:border-copper"
            >
              Copy
            </button>
          </div>
          {copyStatus && <span className="font-mono text-[11px] text-moss">{copyStatus}</span>}
        </div>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="border-b border-hair font-mono text-xs tracking-[0.1em] text-mist uppercase">
            <tr>
              <th className="px-2 py-2">Email</th>
              <th className="px-2 py-2">Role</th>
              <th className="px-2 py-2">Scope</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <Fragment key={u.user_id}>
                <tr className="border-b border-hair last:border-0">
                  <td className="px-2 py-2 font-mono text-xs text-fg">{u.email}</td>
                  <td className="px-2 py-2 text-fg">{u.role}</td>
                  <td className="px-2 py-2 font-mono text-xs text-mist">
                    {u.role === "dept_user"
                      ? (u.department ?? "—")
                      : u.plant_ids.length > 0
                        ? u.plant_ids.join(", ")
                        : "—"}
                  </td>
                  <td className="px-2 py-2">
                    {!u.is_active ? (
                      <span className="rounded-md border border-rust/40 bg-rust/10 px-2 py-0.5 font-mono text-xs text-rust">
                        deactivated
                      </span>
                    ) : u.invite_pending ? (
                      <span className="rounded-md border border-copper/40 bg-copper/10 px-2 py-0.5 font-mono text-xs text-copper">
                        invite pending
                      </span>
                    ) : (
                      <span className="rounded-md border border-moss/40 bg-moss/10 px-2 py-0.5 font-mono text-xs text-moss">
                        active
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-3">
                      {u.invite_pending && (
                        <button
                          type="button"
                          onClick={() => handleReinvite(u.user_id, u.email)}
                          className="text-xs text-copper hover:text-fg"
                        >
                          Re-invite
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setEditingId((id) => (id === u.user_id ? null : u.user_id))}
                        className="text-xs text-mist hover:text-fg"
                      >
                        {editingId === u.user_id ? "Cancel" : "Edit"}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleToggleActive(u)}
                        disabled={toggleBusyId === u.user_id}
                        className="text-xs text-mist hover:text-fg disabled:opacity-40"
                      >
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </div>
                  </td>
                </tr>
                {editingId === u.user_id && (
                  <tr className="border-b border-hair last:border-0">
                    <td colSpan={5} className="px-2 pb-3">
                      <EditUserRow
                        user={u}
                        plants={plants}
                        onDone={() => {
                          setEditingId(null);
                          onCreated();
                        }}
                        onCancel={() => setEditingId(null)}
                        onError={setError}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-2 py-6 text-center text-mist">
                  No users yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {open && (
        <form
          onSubmit={handleSubmit}
          className="air-rise mt-4 flex flex-col gap-3 rounded-xl border border-line bg-midnight p-4"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Email">
              <input
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operator@customer.example"
                className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
              />
            </Field>
            <Field label="Role">
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as DbRole)}
                className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
              >
                {DB_ROLES.map((r) => (
                  <option key={r.value} value={r.value} className="bg-panel">
                    {r.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          {isPlantRole && (
            <Field label="Plants this user can access">
              <div className="flex flex-wrap gap-2">
                {plants.map((p) => {
                  const checked = plantIds.includes(p.plant_id);
                  return (
                    <label
                      key={p.plant_id}
                      className={`cursor-pointer rounded-full border px-3 py-1 font-mono text-xs ${
                        checked ? "border-copper bg-copper/10 text-copper" : "border-line text-mist"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) =>
                          setPlantIds((prev) =>
                            e.target.checked
                              ? [...prev, p.plant_id]
                              : prev.filter((id) => id !== p.plant_id),
                          )
                        }
                        className="mr-1.5 hidden"
                      />
                      {p.plant_id}
                    </label>
                  );
                })}
                {plants.length === 0 && (
                  <span className="text-xs text-mist">No plants exist yet — create one first.</span>
                )}
              </div>
            </Field>
          )}

          {isDeptRole && (
            <Field label="Department — the only pages this login will see">
              <select
                value={department}
                onChange={(e) => setDepartment(e.target.value as Department)}
                className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
              >
                {DEPARTMENTS.map((d) => (
                  <option key={d} value={d} className="bg-panel">
                    {d}
                  </option>
                ))}
              </select>
            </Field>
          )}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={busy || (isPlantRole && plantIds.length === 0)}
              className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
            >
              {busy ? "Creating…" : "Create user"}
            </button>
            {error && <span className="text-sm text-rust">{error}</span>}
          </div>
        </form>
      )}
    </section>
  );
}

function EditUserRow({
  user,
  plants,
  onDone,
  onCancel,
  onError,
}: {
  user: AdminUserSummary;
  plants: AdminPlantSummary[];
  onDone: () => void;
  onCancel: () => void;
  onError: (msg: string) => void;
}) {
  const [role, setRole] = useState<DbRole>(user.role);
  const [plantIds, setPlantIds] = useState<string[]>(user.plant_ids);
  const [department, setDepartment] = useState<Department>(user.department ?? "finance");
  const [busy, setBusy] = useState(false);

  const isPlantRole = DB_ROLES.find((r) => r.value === role)?.isPlantRole ?? false;
  const isDeptRole = DB_ROLES.find((r) => r.value === role)?.isDeptRole ?? false;

  async function handleSave() {
    setBusy(true);
    try {
      await patchUser(user.user_id, {
        role,
        department: isDeptRole ? department : null,
        plant_ids: isPlantRole ? plantIds : [],
      });
      onDone();
    } catch (err) {
      onError(err instanceof AdminApiError ? err.message : "failed to update user");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="air-rise flex flex-col gap-3 rounded-xl border border-line bg-midnight p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Role">
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as DbRole)}
            className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
          >
            {DB_ROLES.map((r) => (
              <option key={r.value} value={r.value} className="bg-panel">
                {r.label}
              </option>
            ))}
          </select>
        </Field>
        {isDeptRole && (
          <Field label="Department">
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value as Department)}
              className="rounded-lg border border-line bg-transparent px-2.5 py-1.5 text-sm text-fg focus:border-copper focus:outline-none"
            >
              {DEPARTMENTS.map((d) => (
                <option key={d} value={d} className="bg-panel">
                  {d}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>

      {isPlantRole && (
        <Field label="Plants this user can access">
          <div className="flex flex-wrap gap-2">
            {plants.map((p) => {
              const checked = plantIds.includes(p.plant_id);
              return (
                <label
                  key={p.plant_id}
                  className={`cursor-pointer rounded-full border px-3 py-1 font-mono text-xs ${
                    checked ? "border-copper bg-copper/10 text-copper" : "border-line text-mist"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) =>
                      setPlantIds((prev) =>
                        e.target.checked
                          ? [...prev, p.plant_id]
                          : prev.filter((id) => id !== p.plant_id),
                      )
                    }
                    className="mr-1.5 hidden"
                  />
                  {p.plant_id}
                </label>
              );
            })}
          </div>
        </Field>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={busy || (isPlantRole && plantIds.length === 0)}
          className="rounded-full bg-copper px-4 py-2 text-sm font-medium text-bg disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onCancel} className="text-sm text-mist hover:text-fg">
          Cancel
        </button>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------
// Audit log
// --------------------------------------------------------------------

function AuditLogSection({ entries }: { entries: AuditLogEntry[] }) {
  return (
    <section
      className="rounded-2xl border border-hair bg-panel p-4"
      style={{ boxShadow: "var(--shadow-sm)" }}
    >
      <h2 className="font-mono text-xs tracking-[0.15em] text-mist uppercase">
        Audit log — who onboarded what
      </h2>
      <div className="mt-3 flex flex-col gap-1.5">
        {entries.map((e) => (
          <div
            key={e.log_id}
            className="grid grid-cols-[auto_1fr_auto] items-baseline gap-3 border-b border-hair py-1.5 text-sm last:border-0"
          >
            <span className="font-mono text-xs text-mist">{fmtTs(e.created_at)}</span>
            <span className="text-fg">
              <span className="font-mono text-copper">{e.actor_email ?? "system"}</span>{" "}
              {e.action.replace(".", " → ")}{" "}
              <span className="font-mono text-xs text-mist">
                {e.target_type}:{e.target_id.slice(0, 8)}
              </span>
            </span>
          </div>
        ))}
        {entries.length === 0 && <p className="py-4 text-center text-sm text-mist">No activity yet.</p>}
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="font-mono text-[11px] tracking-[0.08em] text-mist uppercase">{label}</span>
      {children}
    </label>
  );
}
