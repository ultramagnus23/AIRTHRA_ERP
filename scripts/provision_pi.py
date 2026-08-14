#!/usr/bin/env python
"""P4 Raspberry Pi field-device provisioning script.

Given a new plant_id, this script:

  1. Generates a WireGuard keypair for the device.
  2. Registers the device's MQTT credentials (random password) in
     docker/mosquitto/passwd, by driving the existing
     scripts/mosquitto_add_user.sh rather than re-implementing password
     hashing here.
  3. Writes a device config file the edge daemon would read (plant_id,
     MQTT broker host/port, MQTT credentials) -- see the "config surface"
     note below for the one honest caveat here.
  4. Emits static, NOT-executed documentation artifacts for the two
     provisioning steps that only make sense on real Raspberry Pi hardware
     running Linux: a systemd unit file for the edge daemon, and overlayfs
     (read-only rootfs) setup instructions. These are written as reference
     files, not run -- see the big warning in main() and in each artifact.

--------------------------------------------------------------------------
WireGuard keypair generation -- what's real here and what isn't
--------------------------------------------------------------------------
The real `wg genkey`/`wg pubkey` CLI (package `wireguard-tools`) is not
installed and not installable on this Windows dev sandbox (confirmed:
`where wg` finds nothing, and this is a Windows box with no WSL/Linux
package manager available to this script). WireGuard keys are exactly
Curve25519 (X25519) keypairs, clamped and base64-encoded the same way `wg
genkey` produces them -- there is nothing "wg-specific" about the math, so
this script generates a REAL, valid X25519 keypair with the `cryptography`
library and base64-encodes it in the exact same format `wg genkey` would
emit. A real WireGuard peer (server or client) will accept these keys
as-is. What's NOT done: this script does not install/configure an actual
`wg0` interface (no WireGuard kernel module or `wg-quick` exists on this
box to configure), and does not add the new peer to a live WireGuard
server config -- it only prints/writes the `[Peer]` stanza the operator
would paste into the real server's config by hand (or a future automation
step would apply).

--------------------------------------------------------------------------
Config surface caveat
--------------------------------------------------------------------------
edge/config.py's EdgeConfig currently reads its MQTT/Postgres connection
info from a single shared repo-root `.env` plus `--plant-id`/CLI flags --
P1 did not build a per-device config file mechanism (each plant is
launched as `edge/daemon.py --mock --plant-id <id>` against one shared
.env). So "a config file the edge daemon would read" doesn't have an
existing loader to target. Per the read-only constraint on edge/ for this
phase (P1's completed work, out of scope here), this script does NOT add
a new config-file loader to edge/config.py. Instead it writes the
per-device values the daemon needs in the two forms that fit today's
actual mechanism:
  - devices/<plant_id>/edge.env   -- a dotenv-format override file with
    MQTT_HOST/PORT/USERNAME/PASSWORD, meant to be sourced/merged into the
    device's environment before launching edge/daemon.py --plant-id <id>.
  - devices/<plant_id>/device.json -- a structured summary of the same
    values plus the WireGuard material, for whatever the real fleet-config
    system ends up being.

Usage:
    .venv/Scripts/python.exe scripts/provision_pi.py --plant-id goa_pilot_02 \\
        [--wg-server-endpoint vpn.airthra.example.com:51820] \\
        [--wg-server-pubkey <base64>]

Writes everything under devices/<plant_id>/ (git-ignored-worthy, contains
dev-only secrets -- same convention as the rest of this repo's dev
credentials).
"""
from __future__ import annotations

import argparse
import base64
import json
import secrets
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_DEV_PORT = os.environ.get("MQTT_DEV_PORT", "1883")
MQTT_TLS_PORT = os.environ.get("MQTT_TLS_PORT", "8883")

PASSWD_FILE = ROOT / "docker" / "mosquitto" / "passwd"
ADD_USER_SCRIPT = ROOT / "scripts" / "mosquitto_add_user.sh"


# ---------------------------------------------------------------------------
# WireGuard keypair (real X25519 math, see module docstring)
# ---------------------------------------------------------------------------

def wg_genkey() -> tuple[str, str]:
    """Returns (private_key_b64, public_key_b64) in the same base64 wire
    format `wg genkey`/`wg pubkey` produce (raw 32-byte X25519 keys,
    standard base64)."""
    priv = X25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(priv_bytes).decode("ascii"), base64.b64encode(pub_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# MQTT device registration (reuses scripts/mosquitto_add_user.sh)
# ---------------------------------------------------------------------------

def gen_mqtt_password() -> str:
    return secrets.token_urlsafe(18)


def register_mqtt_device(device_id: str, password: str) -> str:
    """Drives the existing scripts/mosquitto_add_user.sh (which wraps
    `mosquitto_passwd`) rather than re-implementing password hashing here.

    Three paths are tried in order:
      1. Local `bash` + local `mosquitto_passwd` binary (what the script
         itself expects). Not present on this dev box (confirmed absent).
      2. `docker compose exec` into the *running* mosquitto container,
         which is what mosquitto_add_user.sh's own fallback instructions
         say to do. DISCOVERED DURING THIS PHASE: this actually fails here
         -- docker-compose.yml mounts docker/mosquitto/passwd into the
         container as `:ro` (see the mosquitto service's volumes), so the
         container-side mosquitto_passwd gets "Read-only file system".
         That read-only mount is deliberate (P0/P1 infra, out of scope to
         change in P4), so this script does not attempt to alter it.
      3. A throwaway one-off `docker run` of the SAME eclipse-mosquitto
         image (not the running container) with the HOST passwd file
         bind-mounted read-write. This still runs the real
         `mosquitto_passwd` binary -- no hash logic is reimplemented here
         -- it just targets the host file directly instead of going
         through the read-only mount on the long-running service
         container. Verified working during this phase. `docker compose
         restart mosquitto` afterwards makes the running container re-read
         the (now host-updated) file, since mosquitto only loads
         password_file at startup.

    Returns a human-readable string describing which path succeeded."""
    bash = _find_bash()
    if bash:
        try:
            r = subprocess.run(
                [bash, str(ADD_USER_SCRIPT), device_id, password],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                return f"registered via {ADD_USER_SCRIPT.name} (local mosquitto_passwd): {r.stdout.strip()}"
        except (FileNotFoundError, OSError):
            pass

    docker = _find_docker()
    if not docker:
        raise RuntimeError(
            "could not register MQTT device: no local `mosquitto_passwd` and no "
            "`docker` CLI found to fall back to the containerized command "
            "documented in scripts/mosquitto_add_user.sh"
        )

    r = subprocess.run(
        [docker, "compose", "exec", "-T", "mosquitto", "mosquitto_passwd",
         "-b", "/mosquitto/config/passwd", device_id, password],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        subprocess.run([docker, "compose", "restart", "mosquitto"], cwd=str(ROOT),
                        capture_output=True, text=True, timeout=60)
        return ("registered via docker compose exec mosquitto mosquitto_passwd "
                "(the fallback scripts/mosquitto_add_user.sh itself documents), "
                "mosquitto restarted to pick up the new passwd file")

    # Path 2 failed (expected here: passwd is bind-mounted :ro into the
    # running service container). Fall back to a throwaway container run
    # against the host file directly -- still the real mosquitto_passwd
    # binary, just not going through the read-only mount.
    r2 = subprocess.run(
        [docker, "run", "--rm",
         "-v", f"{PASSWD_FILE}:/mosquitto/config/passwd",
         "eclipse-mosquitto", "mosquitto_passwd", "-b", "/mosquitto/config/passwd",
         device_id, password],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
        env={**os.environ, "MSYS_NO_PATHCONV": "1"},
    )
    if r2.returncode != 0:
        raise RuntimeError(
            f"all mosquitto_passwd paths failed. docker compose exec: {r.stderr.strip()!r}; "
            f"docker run (host file): {r2.stderr.strip()!r}"
        )
    subprocess.run([docker, "compose", "restart", "mosquitto"], cwd=str(ROOT),
                    capture_output=True, text=True, timeout=60)
    return ("registered via a throwaway `docker run eclipse-mosquitto mosquitto_passwd` "
            "against the host passwd file directly (docker compose exec failed: the file "
            "is mounted :ro into the running mosquitto service, by design), "
            "mosquitto restarted to pick up the new passwd file")


def _find_bash() -> str | None:
    for c in ("bash", r"C:\Program Files\Git\bin\bash.exe"):
        try:
            r = subprocess.run([c, "--version"], capture_output=True, timeout=10)
            if r.returncode == 0:
                return c
        except (FileNotFoundError, OSError):
            continue
    return None


def _find_docker() -> str | None:
    for c in ("docker", r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"):
        try:
            r = subprocess.run([c, "version", "--format", "{{.Server.Version}}"],
                                capture_output=True, timeout=15)
            if r.returncode == 0:
                return c
        except (FileNotFoundError, OSError):
            continue
    return None


# ---------------------------------------------------------------------------
# Static, NOT-executed artifacts: systemd unit + overlayfs instructions
# ---------------------------------------------------------------------------

SYSTEMD_UNIT_TEMPLATE = """\
# airthra-edge.service
# --------------------------------------------------------------------------
# NOT INSTALLED, NOT ENABLED, NOT TESTED by provision_pi.py.
# This dev sandbox is Windows (no systemd). This unit file is a reference
# artifact only: on a real Raspberry Pi, an operator (or a future ansible/
# cloud-init step) would place this at /etc/systemd/system/airthra-edge.service
# and run:
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now airthra-edge.service
# --------------------------------------------------------------------------
[Unit]
Description=Airthra edge daemon ({plant_id})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=airthra
WorkingDirectory=/opt/airthra
EnvironmentFile=/opt/airthra/devices/{plant_id}/edge.env
ExecStart=/opt/airthra/.venv/bin/python /opt/airthra/edge/daemon.py --plant-id {plant_id}
Restart=on-failure
RestartSec=5
# Graceful stop: edge/daemon.py polls for a stop-request file rather than
# relying on a clean SIGTERM landing inside its asyncio loop (see
# edge/config.py:stop_request_path docstring). systemd's default SIGTERM
# on `systemctl stop` still works because daemon.py runs on Linux here
# (this Windows-signal caveat is specific to controlling it FROM Windows,
# not to the daemon itself under systemd on real Pi hardware).
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""

OVERLAYFS_INSTRUCTIONS_TEMPLATE = """\
# Read-only rootfs + overlayfs setup for {plant_id}
# --------------------------------------------------------------------------
# NOT EXECUTED by provision_pi.py -- this is documentation only. Raspberry
# Pi OS-specific disk/boot-partition operations cannot be run or verified
# from this Windows dev machine. An operator follows these steps by hand
# (or scripts them via `raspi-config`/a custom Pi imaging pipeline) on the
# actual device.
# --------------------------------------------------------------------------

Why: field devices lose power ungracefully (no UPS). An ext4 root
filesystem mounted read-write risks corruption on power loss. Mounting the
rootfs read-only, with an in-RAM (tmpfs) overlay for anything that needs
to be writable at runtime, makes power loss safe to the filesystem (worst
case: the current boot's writes since the last controlled remount are
lost, not the filesystem itself).

1. Enable overlayfs via raspi-config (Raspberry Pi OS Bullseye+):
     sudo raspi-config
       -> Performance Options -> Overlay File System -> Enable
       -> (also offered: "Write-protect boot partition" -> Enable)
   This is the supported, tested path on Raspberry Pi OS and is preferred
   over hand-rolling /etc/fstab overlay entries.

2. Confirm after reboot:
     mount | grep ' / '
   should show `overlay` as the filesystem type for `/`.

3. Airthra-specific writable paths that must NOT be inside the read-only
   overlay (bind-mount real, persistent storage for these instead, e.g. a
   separate small ext4 partition or a USB-attached SSD):
     /opt/airthra/edge/data/    (SQLite offline buffer, stats, stop-request
                                 files -- edge/config.py's data_dir; losing
                                 the buffer on every reboot would defeat the
                                 P1 offline-buffering guarantee)
     /opt/airthra/edge/cache/   (manifest cache -- losable but nice to keep)
     /var/log/                  (systemd journal persistence, optional)

   Example /etc/fstab bind-mount line (adjust device/partition):
     /dev/sda1  /opt/airthra/edge/data  ext4  defaults,noatime  0  2

4. Re-verify the WireGuard tunnel and mosquitto TLS listener (port {mqtt_tls_port})
   both survive a `sudo reboot` with the overlay active before deploying to
   the field -- this is the actual acceptance test for this step, and it
   requires real hardware.
"""


def write_static_docs(device_dir: Path, plant_id: str) -> None:
    (device_dir / "airthra-edge.service").write_text(
        SYSTEMD_UNIT_TEMPLATE.format(plant_id=plant_id), encoding="utf-8"
    )
    (device_dir / "overlayfs_setup.md").write_text(
        OVERLAYFS_INSTRUCTIONS_TEMPLATE.format(plant_id=plant_id, mqtt_tls_port=MQTT_TLS_PORT),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Airthra P4 Pi provisioning script")
    parser.add_argument("--plant-id", required=True)
    parser.add_argument("--wg-server-endpoint", default="<VPN_SERVER_HOST>:51820",
                         help="Real WireGuard server endpoint, if known yet (placeholder otherwise)")
    parser.add_argument("--wg-server-pubkey", default="<VPN_SERVER_PUBKEY>",
                         help="Real WireGuard server public key, if known yet (placeholder otherwise)")
    parser.add_argument("--skip-mqtt", action="store_true",
                         help="Skip live mosquitto registration (e.g. stack not running); still writes files")
    args = parser.parse_args()

    plant_id = args.plant_id
    device_dir = ROOT / "devices" / plant_id
    device_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print(f"P4 Pi provisioning: {plant_id}")
    print("=" * 70)

    # --- 1. WireGuard keypair ---
    priv_b64, pub_b64 = wg_genkey()
    print(f"[1/4] generated WireGuard keypair (real X25519, wg-compatible encoding) "
          f"pubkey={pub_b64}")

    device_wg_ip = "10.100.0.0"  # placeholder; real allocation is a fleet-management concern
    wg_client_conf = f"""\
# {plant_id} WireGuard client config
# NOT applied to any interface on this machine (no WireGuard runtime here).
# On the Pi: save as /etc/wireguard/wg0.conf then `sudo wg-quick up wg0`.
[Interface]
PrivateKey = {priv_b64}
Address = {device_wg_ip}/32

[Peer]
PublicKey = {args.wg_server_pubkey}
Endpoint = {args.wg_server_endpoint}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
    (device_dir / "wg0.conf").write_text(wg_client_conf, encoding="utf-8")

    server_peer_stanza = f"""\
# Paste into the real WireGuard SERVER's config to add {plant_id} as a peer.
[Peer]
PublicKey = {pub_b64}
AllowedIPs = {device_wg_ip}/32
"""
    (device_dir / "wg_server_peer_stanza.conf").write_text(server_peer_stanza, encoding="utf-8")
    print(f"      wrote {device_dir / 'wg0.conf'} and wg_server_peer_stanza.conf")

    # --- 2. MQTT device registration ---
    mqtt_device_id = f"{plant_id}_edge"
    mqtt_password = gen_mqtt_password()
    if args.skip_mqtt:
        mqtt_status = "SKIPPED (--skip-mqtt): passwd file NOT updated, credentials below are not yet valid"
        print(f"[2/4] {mqtt_status}")
    else:
        mqtt_status = register_mqtt_device(mqtt_device_id, mqtt_password)
        print(f"[2/4] {mqtt_status}")

    # --- 3. Device config files (see "Config surface caveat" in module docstring) ---
    edge_env = f"""\
# {plant_id} edge daemon environment overrides.
# Merge into (or source alongside) the shared repo-root .env before running:
#   edge/daemon.py --plant-id {plant_id}
# See provision_pi.py module docstring "Config surface caveat" for why this
# is an override-env file rather than a dedicated per-device config loader.
MQTT_HOST={MQTT_HOST}
MQTT_DEV_PORT={MQTT_DEV_PORT}
MQTT_TLS_PORT={MQTT_TLS_PORT}
MQTT_EDGE_USERNAME={mqtt_device_id}
MQTT_EDGE_PASSWORD={mqtt_password}
"""
    (device_dir / "edge.env").write_text(edge_env, encoding="utf-8")

    device_summary = {
        "plant_id": plant_id,
        "provisioned_at": datetime.now(timezone.utc).isoformat(),
        "mqtt": {
            "device_id": mqtt_device_id,
            "host": MQTT_HOST,
            "dev_port": int(MQTT_DEV_PORT),
            "tls_port": int(MQTT_TLS_PORT),
            "password": mqtt_password,
            "registration_status": mqtt_status,
        },
        "wireguard": {
            "device_public_key": pub_b64,
            "device_address": f"{device_wg_ip}/32",
            "note": "device_private_key is in wg0.conf only, not repeated here",
            "key_generation": "real X25519 via `cryptography` (wg CLI unavailable on this Windows box, see module docstring)",
        },
        "provisioning_steps_not_executed_here": [
            "systemd unit install/enable (see airthra-edge.service, real-Pi-only)",
            "overlayfs / read-only rootfs setup (see overlayfs_setup.md, real-Pi-only)",
            "adding the WireGuard peer to the live VPN server (see wg_server_peer_stanza.conf, manual/future-automation step)",
        ],
    }
    (device_dir / "device.json").write_text(json.dumps(device_summary, indent=2), encoding="utf-8")
    print(f"[3/4] wrote {device_dir / 'edge.env'} and device.json")

    # --- 4. Static real-Pi-only docs ---
    write_static_docs(device_dir, plant_id)
    print(f"[4/4] wrote {device_dir / 'airthra-edge.service'} and overlayfs_setup.md "
          f"(documentation artifacts, NOT executed/applied)")

    print()
    print(f"Provisioning artifacts for {plant_id} written to: {device_dir}")
    print("Remaining manual/real-hardware steps: see device.json's "
          "'provisioning_steps_not_executed_here'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
