# Response to the 6-point industrial IoT review

Date: 2026-08-17

The critique is correct in substance — these are the right six landmines, and it was worth raising. Point-by-point below, with file/line evidence for anything claimed as already-handled, and no claim of "done" where it isn't.

**Scorecard:** 2 of 6 were already built (one exceeding the spec), 2 were built but not to a standard that survives the reviewer's objection, 1 was a genuine gap now fixed, 1 remains open.

One architectural note up front: the review assumes an InfluxDB 1.8 + Telegraf + Node-RED stack. This platform is TimescaleDB (Postgres) + MQTT + FastAPI. Every *principle* below applies identically; the specific tooling differs, and where it does the rationale is given rather than glossed.

---

## 1. The "No Clock" trap — **was a real gap. Now fixed.**

The reviewer is right, and this was the most dangerous of the six. Prior to this change `datetime.now(timezone.utc)` was called completely unguarded throughout `edge/daemon.py`. Worse than the review anticipates: because this daemon **buffers to SQLite and backfills on reconnect** (see §2), timestamps minted with a wrong clock were *durable* — they survived the outage and replayed into `readings` when the link returned.

Fixed in [edge/clock.py](edge/clock.py), gating the daemon at [edge/daemon.py](edge/daemon.py). Three independent checks:

1. **Sanity floor** — system time must be ≥ the date the software was written. Time cannot legitimately precede the code reading it. Catches the 1970 reset outright.
2. **Monotonic watermark** — the newest timestamp ever emitted is persisted to disk (atomically, on the SSD next to the buffer). The clock may never jump backwards past it by more than 120s. *This is the check that actually protects existing history from being overwritten*, and it survives reboots.
3. **Sync source** — best-effort confirmation via NTP (`timedatectl`) or a kernel-visible hardware RTC. Where neither can be interrogated it reports `unverified` rather than silently assuming success; production images set `EDGE_REQUIRE_SYNC_SOURCE=1` to make that condition blocking.

On failure the daemon **waits with backoff rather than exiting**, so a unit self-heals when 4G returns instead of needing a site visit. Skipped cycles are counted separately (`dropped_bad_clock`) because "alive but deliberately not producing data" is a more urgent condition than "offline", and must not look the same on a dashboard.

Verified against all six cases: 1970 boot rejected; normal time accepted; watermark advances; a 1-hour backwards jump rejected with an explicit "would overwrite history" reason; a 30s NTP slew tolerated; watermark correctly reloaded by a fresh instance after restart.

**UTC**: already correct — the platform stores `timestamptz` throughout and never wrote IST. Local time appears only at render time in the browser.

**Hardware still required.** Software cannot invent the correct time. A **DS3231 I2C RTC + CR2032** must be fitted to each Pi. What this change guarantees is that a missing RTC is now *loud* — the unit refuses to fabricate data instead of writing plausible-looking rows at the wrong time.

---

## 2. Store-and-forward — **already built, exceeds the spec**

Implemented before this review, in [edge/daemon.py](edge/daemon.py) and `edge/buffer.py`:

- Readings publish to local Mosquitto at **QoS 1**.
- On broker loss, everything goes to a **local SQLite buffer on disk** (`edge/buffer.py`, `SqliteBuffer`).
- On reconnect, a sync task **drains oldest-first in chunks of 500** to a `backfill` topic; a failed chunk stays buffered and retries rather than being dropped.
- Setpoints are buffered on the same path.

Observed live during this session — the daemon logged `mqtt connection lost; buffering` and then `sync: drained 7 buffered item(s) to backfill (0 remaining)` on reconnect.

Difference from the reviewer's design: buffering is SQLite rather than a local InfluxDB, and sync is a purpose-built task rather than Telegraf. The guarantee asked for — zero data loss across a multi-hour outage — is met. What has **not** been proven is the 6-month-of-buffer claim: buffer growth under a genuinely long outage has not been load-tested, and disk-full behaviour is untested. That is a real open item.

---

## 3. `quality_flag` — **built, but the reviewer's objection stands**

The rule itself is enforced platform-wide and was a founding constraint: raw readings are immutable, bad data is flagged rather than dropped or nulled, and `imputed` is never written outside the ML feature path. The alarm engine has a dedicated frozen-sensor detector keyed on flag persistence.

**Where the reviewer is right:** the current vocabulary is `('good', 'bad', 'uncertain', 'estimated')` — four text values. The proposed taxonomy is more diagnostically useful because it separates *causes*:

| Proposed | Meaning | Current platform |
|---|---|---|
| 0 | Good | `good` |
| 1 | Hardware fault (<3.8 mA, DS18B20 CRC error) | collapsed into `bad` |
| 2 | Out-of-physical-range | collapsed into `bad` |
| 3 | Calibration / purge cycle active | **no equivalent exists** |

Two real losses. First, `bad` cannot distinguish "the wire fell off" from "the reading is implausible" — different work orders, same flag. Second, and more serious, there is **no calibration/purge state at all**: during a purge, readings are either wrongly marked `good` or wrongly marked `bad`, when the truth is "intentionally invalid, ignore, nothing is broken". That will generate false alarms and poison training data.

**Recommendation:** extend the CHECK constraint to add `sensor_fault`, `out_of_range`, and `calibration`, keeping `bad` as a deprecated alias during migration. Text over integers deliberately — a stray `2` in a config file is unreadable, `out_of_range` is self-documenting in queries and logs. Not yet done: it is a schema migration touching the alarm engine and the ML feature path, and needs sequencing.

---

## 4. Event logging — **built, but too weak to serve as ML ground truth**

An events form exists (`frontend/components/EventForm.tsx`, `/[plant_id]/events`) writing timestamped rows. But its shape is a **generic dropdown of four kinds** (`maintenance`, `lab_sample`, `note`, `alarm_ack`) plus a free-text note and optional quantity.

The reviewer's objection is correct and this is the gap I would rank second after the clock. Free text is not a label. "changed stator", "Stator swap P101", and "replaced pump stator" are three unparseable strings, and a model cannot learn from them. What is needed is exactly what was specified — **one-tap, structured, specific** events:

`[Added KOH]` `[Cleaned PHE]` `[Changed P-101 Stator]` `[Boiler Fuel Change]` `[Emergency Trip]`

each writing a typed event kind with structured fields (quantity + unit for KOH), not prose. The operator interaction must be a single tap on a control-room screen, because anything slower simply will not be recorded during an actual incident — which is precisely when the label matters most.

**Status: open.** Concrete, low-risk, no hardware dependency.

---

## 5. Zero-trust remote access — **open, reviewer's recommendation accepted**

No port forwarding exists anywhere, so the immediate hazard the reviewer names is not present. But the provisioning path is not real either: `scripts/provision_pi.py` generates a valid WireGuard keypair and then explicitly does not configure an interface, does not register the peer, and hardcodes both the server endpoint and a fixed `10.100.0.0` device IP. Already recorded in [SHIPPING.md](SHIPPING.md) §0.3.

**Tailscale is the better recommendation and I would take it over hand-rolled WireGuard**, for a reason specific to fleet scale: at 100 units the hard part is not the tunnel, it is key distribution, IP allocation, and *revocation* when a unit is stolen or decommissioned. Tailscale's ACLs and device expiry solve the operational half; raw WireGuard leaves it as homework.

---

## 6. Midnight blockchain cron — **built, exceeds spec on integrity; scheduling is open**

[workers/archive_worker.py](workers/archive_worker.py) already does Parquet → SHA-256 → **real OpenTimestamps** anchoring, with `archive_log` rows recording each run. It goes further than specified on durability: the upload is atomic via a staging key, and the object is **re-downloaded and re-hashed** after upload before the archive row is written, so a truncated or corrupted upload can never be recorded as success.

Two honest caveats:

1. **No scheduler exists.** There is no cron entry, no systemd timer, nothing invoking this at 00:05 UTC. It runs when run. That is a deployment gap, not a code gap, but the audit trail does not exist until it is scheduled.
2. **OTS falls back to a labelled stub proof** when the calendar submission fails (network outage). It is clearly marked and carries an `is_real` flag — never silently passed off as genuine — but downstream consumers must actually check that flag, and whether they do has not been verified.

---

## What I would do next, in order

1. **Event logging form (#4)** — cheap, no dependencies, and every day it is missing is a day of unlabelled data that can never be recovered retroactively.
2. **`quality_flag` taxonomy (#3)** — schema migration; do it before large volumes of real data exist, not after.
3. **Schedule the archive worker (#6)** — one systemd timer; the compliance trail is worthless unscheduled.
4. **Tailscale (#5)** — replaces the placeholder provisioning path.
5. **Buffer load test (#2)** — prove the long-outage and disk-full behaviour rather than assuming it.

Fitting the **DS3231 RTC modules** is a hardware purchase that should start now, in parallel — the software gate is in place and will refuse to produce data on units that lack both an RTC and NTP.
