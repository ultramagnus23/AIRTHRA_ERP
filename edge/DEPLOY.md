# Deploying the edge daemon to the Raspberry Pi

This covers getting `edge/daemon.py` (Modbus RS-485, DS18B20 1-Wire,
PMS7003 UART pollers → local SQLite buffer → MQTT) running on the actual
Pi at the Goa pilot plant, containerized. See the root [README.md](../README.md)'s
"Go-live checklist" for the sensor-wiring side of this (filling in
`modbus_map.json` etc.) - this document is about the deployment mechanics:
getting code onto the Pi and running it reliably.

## Why a container, and why not a separate git repo

The Pi only ever needs `edge/` + `shared/` - not `api/`, `frontend/`,
`ingest/`, or `workers/`. A **separate git repo** for just that code was
considered and rejected: `edge/manifest.py` depends on the exact shape of
the `sensors` table (owned by `migrations/`), and `shared/quality.py`'s
quality-flag codes must stay identical to what `ingest/service.py` expects
on the cloud side. Splitting into two repos means those two things drift
out of sync silently. Instead, `edge/Dockerfile` builds a small, ARM
image straight from this monorepo, `COPY`ing in only `edge/` and
`shared/` - one source of truth, one deployable artifact scoped to what
the Pi actually runs.

## 0. MQTT connectivity for a REMOTE Pi

`docker-compose.yml` binds the plaintext MQTT listener (`MQTT_DEV_PORT`,
1883) to `127.0.0.1` on the VPS on purpose - only the TLS listener
(`MQTT_TLS_PORT`, 8883) is publicly reachable. `edge/daemon.py` now
supports TLS (`edge/config.py`'s `mqtt_use_tls` and related fields), so a
Pi anywhere on the internet can reach the broker once configured for it.

Set in `.env.pi` (see `.env.pi.example`, already defaults to this):

```bash
MQTT_USE_TLS=true
MQTT_TLS_PORT=8883
MQTT_CA_CERT_PATH=/app/certs/ca.crt   # the mount path docker-compose.pi.yml uses
```

`MQTT_CA_CERT_PATH` has to point at `docker/mosquitto/certs/ca.crt` -
whoever ran `docker/mosquitto/gen_certs.sh` for the VPS's broker generated
a self-signed dev/pilot CA, which isn't in any system trust store, so the
Pi needs that exact file to verify it's really talking to your broker and
not something else on port 8883. Copy **only** `ca.crt` to the Pi (never
`ca.key` - that's the CA's private key and must stay on whichever machine
generated it) as `./certs/ca.crt` next to `docker-compose.pi.yml`, which
bind-mounts it read-only into the container. `EdgeConfig` refuses to start
with `MQTT_USE_TLS=true` and no `MQTT_CA_CERT_PATH` set, so a missing/
wrong path fails immediately with a clear message instead of an endless,
unexplained reconnect loop.

This is server-side TLS (encrypts the connection, proves the Pi is
talking to the real broker) plus the existing username/password auth -
**not** full mutual TLS. `docker/mosquitto/mosquitto.conf` has
`require_certificate false`, so no client certificate is issued or
required yet. `MQTT_CLIENT_CERT_PATH`/`MQTT_CLIENT_KEY_PATH` exist in
`EdgeConfig` for when/if that's tightened to per-device client certs later
- until then, leave both blank.

**Bench-testing on the same LAN as the broker?** Leave `MQTT_USE_TLS=false`
and use `MQTT_DEV_PORT` (1883, plaintext) instead - no cert handling
needed, useful before certs are provisioned or when iterating quickly
during commissioning.

**Postgres is a separate matter**: `DATABASE_URL` still needs a private
network path to the VPS (VPN/WireGuard tunnel, or the same LAN) regardless
of the MQTT TLS setup above - Postgres isn't exposed publicly at all,
TLS or not.

Everything below builds and runs the container correctly either way; it's
what you put in `.env.pi`'s `MQTT_HOST`/`DATABASE_URL` that determines
whether the Pi can actually reach the broker/Postgres once it's running.

## 1. Raspberry Pi OS setup

- **64-bit Raspberry Pi OS (Bookworm), Lite is fine** - use Raspberry Pi
  Imager. 64-bit matters for Docker: Pi 4/5 should run `linux/arm64`
  images; an older Pi 3 / Zero 2 W on 32-bit OS needs `linux/arm/v7`
  instead (noted again in the build command below).
- **Enable the 1-Wire interface** for the DS18B20 probes. Edit
  `/boot/firmware/config.txt` (older OS versions: `/boot/config.txt`) and
  add:
  ```
  dtoverlay=w1-gpio
  ```
  This uses GPIO4 by default, matching the plant BOM. Reboot after adding
  it, then confirm probes are visible on the **host** (not yet in a
  container):
  ```bash
  ls /sys/bus/w1/devices
  ```
  You should see one `28-...` entry per DS18B20 currently wired up, plus a
  `w1_bus_master1` entry. If nothing but the bus master shows up, the
  probes aren't wired correctly yet (or the overlay didn't load) - fix
  this before going any further, since `edge/onewire_map.json` needs
  these exact ROM ids.
- **Enable the UART** for the PMS7003 if it's wired to the Pi's built-in
  serial pins (GPIO14/15) rather than a USB-serial adapter: in
  `raspi-config` → Interface Options → Serial Port, answer "No" to login
  shell over serial and "Yes" to enable the serial hardware. The port is
  then `/dev/serial0` (symlinked to `/dev/ttyAMA0` or `/dev/ttyS0`
  depending on Pi model - check with `ls -l /dev/serial0`).
- **Identify the RS-485 adapters**: plug in both SmartElex USB-to-RS485
  converters, then `ls /dev/ttyUSB*` - note which is which (they can swap
  order across reboots if unplugged/replugged; see the note in
  `docker-compose.pi.yml`).

## 2. Install Docker on the Pi

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# log out and back in for the group membership to take effect
```

Docker Compose v2 is included with recent versions of the convenience
script (`docker compose ...`, no separate install). Verify:

```bash
docker compose version
```

## 3. Get the code onto the Pi

Two options - **cross-building on a dev machine is strongly recommended**
over building directly on the Pi: compiling psycopg's C extension (if no
prebuilt wheel matches the Pi's exact architecture/Python version) on a Pi
Zero 2 W or Pi 3 can take many minutes and sometimes runs out of memory;
cross-building on a normal dev machine takes seconds and needs no special
Pi setup beyond Docker + pulling the finished image.

### Option A (recommended): cross-build elsewhere, push to a registry, pull on the Pi

On your dev machine, from the repo root:

```bash
# One-time: enable buildx's cross-platform emulation
docker buildx create --use

# Build for the Pi's actual architecture and push directly
# (linux/arm64 for 64-bit Pi OS / Pi 4+; linux/arm/v7 for 32-bit)
docker buildx build --platform linux/arm64 \
  -f edge/Dockerfile -t <your-registry>/airthra-edge:latest \
  --push .
```

`<your-registry>` is wherever you're comfortable hosting this image -
Docker Hub, GitHub Container Registry (`ghcr.io/<org>/airthra-edge`), etc.
Then on the Pi:

```bash
docker pull <your-registry>/airthra-edge:latest
docker tag <your-registry>/airthra-edge:latest airthra-edge:latest
```

(the `tag` step just matches the image name `docker-compose.pi.yml`
expects, so you don't have to edit that file with a registry path).

### Option B: build directly on the Pi

Get the source onto the Pi first - `git clone` (needs the Pi to reach
GitHub/wherever this repo is hosted, plus credentials for a private repo)
or `scp`/`rsync` a working copy over from your dev machine. Then, on the
Pi, from the repo root:

```bash
docker build -f edge/Dockerfile -t airthra-edge:latest .
```

No `buildx`/`--platform` needed here since you're building natively on the
Pi's own architecture.

### Either way, you still need on the Pi:

- `docker-compose.pi.yml` (repo root)
- `edge/modbus_map.json`, `edge/onewire_map.json`, `edge/pms7003_map.json`
  (bind-mounted at runtime, not baked into the image - see the Dockerfile)
- `.env.pi` (copy from `.env.pi.example` and fill in real values - **never
  commit this file**, it's already in `.gitignore`)

If you went with Option A, `scp`/`rsync` just those files over rather than
the whole repo.

## 4. Fill in `.env.pi`

```bash
cp .env.pi.example .env.pi
# edit .env.pi: DATABASE_URL, MQTT_HOST, MQTT_EDGE_USERNAME/PASSWORD
```

Read Section 0 above first if the Pi isn't on the same network as the VPS
- these values won't connect otherwise, regardless of how correct they
look.

## 5. Smoke-test the container without real hardware

Before touching real sensors, confirm the image runs and can reach MQTT/
Postgres at all, using `--mock`:

```bash
docker run --rm -it \
  --env-file .env.pi \
  -v $(pwd)/certs/ca.crt:/app/certs/ca.crt:ro \
  airthra-edge:latest --plant-id goa_pilot_01 --mock
```

(drop the `-v .../ca.crt` mount if testing with `MQTT_USE_TLS=false` on
the same LAN as the broker - nothing reads it in that case anyway). You
should see a line like `publisher: connecting to mqtts://your-vps-host:
8883 ...` followed by `publisher: connected`. Ctrl-C to stop. If it loops
on `connection lost/failed`, check `MQTT_CA_CERT_PATH` actually resolves
inside the container (`docker exec ... ls /app/certs/`) before assuming
it's a network/firewall issue - a missing cert file at that path fails
differently (`EdgeConfig` raises immediately) but a *wrong* one (doesn't
match the broker's actual CA) shows up as this same connect-loop.

## 6. Sanity-check real wiring before the full daemon run

Once `modbus_map.json`/`onewire_map.json`/`pms7003_map.json` have real
values (see the root README's "Go-live checklist"), run the dry-run
poller check **inside the same container** so it sees the same device
mounts the real daemon will:

```bash
docker run --rm -it \
  --env-file .env.pi \
  -v $(pwd)/edge/modbus_map.json:/app/edge/modbus_map.json:ro \
  -v $(pwd)/edge/onewire_map.json:/app/edge/onewire_map.json:ro \
  -v $(pwd)/edge/pms7003_map.json:/app/edge/pms7003_map.json:ro \
  -v /sys/bus/w1/devices:/sys/bus/w1/devices:ro \
  --device=/dev/ttyUSB0 --device=/dev/ttyUSB1 --device=/dev/ttyAMA0 \
  --entrypoint python \
  airthra-edge:latest edge/test_real_pollers.py --plant-id goa_pilot_01
```

Fix anything reported as `EXCEPTION`/`COMM_ERROR` before proceeding -
that's a wiring mistake, not something the full daemon run will fix
itself.

## 7. Run for real

```bash
docker compose -f docker-compose.pi.yml up -d
docker compose -f docker-compose.pi.yml logs -f
```

`restart: unless-stopped` in `docker-compose.pi.yml` means it comes back
up automatically after a Pi reboot or crash. The daemon's own watchdog
task (10s health checks, heartbeat file in `edge/data/`) is a separate,
finer-grained mechanism from Docker's restart policy - see
`edge/daemon.py`'s `watchdog_task` - the two are complementary, not
redundant: Docker restarts a dead container; the watchdog surfaces a
container that's alive but stuck (bad clock, full disk, backed-up queue).

## 8. Updating the code later

Rebuild (Option A or B from step 3) with a new tag, then:

```bash
docker compose -f docker-compose.pi.yml pull   # if using a registry
docker compose -f docker-compose.pi.yml up -d  # recreates the container on the new image
```

`edge_cache`/`edge_data` are named volumes, not part of the image, so the
SQLite offline buffer and manifest cache survive this untouched.
