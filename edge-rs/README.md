# airthra-edge (Rust)

Replaces the Python daemon in `edge/` on the Pi. It polls the sensors, shows
them on the SmartElex touchscreen, changes Wi-Fi from that screen, keeps a
local SQLite log and publishes to the same MQTT topics with the same JSON.
The cloud API, workers and frontend are unchanged and still Python/TypeScript.

**Not yet tried on real hardware.** Everything below is tested against
simulators on a development PC.

## The screen

The SmartElex Basic 4.0" is **not a Nextion**. It uses Robu's HMI Editor and
its own protocol ([manual](https://robu.in/wp-content/uploads/2025/01/Robus-HMI-Display-Editor-Guide.pdf)).
The Python `edge/hmi.py` sends Nextion commands, so it cannot drive this screen.

The layout is fixed on the screen, so you build it once in the editor from
[hmi/BUILD_SHEET.md](hmi/BUILD_SHEET.md) ([preview](hmi/preview.svg)), generate
the `.tft`, copy it to the root of the SD card and power the screen with the
card inserted.

### Wiring

| Screen | Pi |
|---|---|
| VCC | 5V (pin 2) |
| GND | GND (pin 6) |
| TX | GPIO15 / RXD (pin 10) |
| RX | GPIO14 / TXD (pin 8) |

> **Measure the screen's TX voltage first.** The Pi's pins accept 3.3 V only and
> the manual does not state the screen's logic level. If it idles near 5 V, use
> a level shifter or divider.

### Check the link before building all three pages

The manual leaves some behaviour unstated. Make a test project with, on page 0,
one RealTimeText (`txt_maxl`=12) and one SquareButton (`value1`=1, `value2`=1).
Flash it, stop the service, and run:

```bash
HMI_PORT=/dev/serial0 ./target/release/airthra-edge hmi-probe
```

| Question | What to look for |
|---|---|
| Does text appear? | The field counts `TEST 1`, `TEST 2`... If not, retry with `HMI_TERMINATOR=lf`, then `crlf` |
| What does a button send? | `got P000T004I000V...` followed by the decoded event |
| One event per tap? | A tap should give one event with a non-zero value |
| Does a page button (`page_switch`=1) also send? | Either is fine |

## Install on the Pi

1. `sudo raspi-config` → Interface Options: Serial Port (login shell **No**,
   hardware **Yes**) and SPI **Yes**. For 1-Wire add `dtoverlay=w1-gpio,gpiopin=2`
   to `/boot/firmware/config.txt`. Reboot. On a Pi 5, also check which device is
   on GPIO14/15 (`dtparam=uart0=on` gives `/dev/ttyAMA0`).
2. Stop the Python daemon so it releases the serial ports:
   `docker compose -f docker-compose.pi.yml down`
3. Build (from the repo root):
   ```bash
   sudo apt install -y build-essential
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   . "$HOME/.cargo/env"
   cargo build --release --manifest-path edge-rs/Cargo.toml
   ```
4. Install:
   ```bash
   sudo useradd --system --no-create-home -G dialout,spi airthra
   sudo install -d /opt/airthra-edge/maps
   sudo install edge-rs/target/release/airthra-edge /opt/airthra-edge/
   sudo install -m 644 edge-rs/sensors.json /opt/airthra-edge/
   sudo install -m 644 edge/*_map.json /opt/airthra-edge/maps/
   sudo install -m 600 edge-rs/deploy/airthra-edge.env.example /etc/airthra-edge.env
   sudo install -m 644 edge-rs/deploy/50-airthra-network.rules /etc/polkit-1/rules.d/
   sudo install -m 644 edge-rs/deploy/airthra-edge.service /etc/systemd/system/
   ```
5. Edit `/etc/airthra-edge.env`, then find wiring faults:
   ```bash
   sudo -u airthra env MAPS_DIR=/opt/airthra-edge/maps SENSORS_FILE=/opt/airthra-edge/sensors.json /opt/airthra-edge/airthra-edge check
   ```
6. Start: `sudo systemctl enable --now airthra-edge`, logs with
   `journalctl -u airthra-edge -f`.

## What the screen says when a sensor fails

| Text | Meaning |
|---|---|
| `NOT SET` | Wiring map still has a placeholder (slave 0, fake probe ID, or no entry) |
| `NO PORT` | Serial or SPI device missing |
| `NO REPLY` | Port opened, nothing answered |
| `NO PROBE` | That 1-Wire ID is not on the bus |
| `BAD REG` | Modbus device rejected the register; try `"register_type": "input"` |
| `BAD CRC` / `BAD DATA` | Garbled reply: check wiring, baud, termination |
| `FAULT` | PT100 amplifier fault |
| `RANGE!` / `STUCK!` | Value outside its range, or a temperature probe repeating itself |
| `OLD` | No update for 30 seconds |
| `CLOCK BAD` (top line) | Pi clock is wrong; readings are shown but not recorded |

## Wi-Fi from the screen

WI-FI → SCAN → tap a network → PASSWORD → type → JOIN. If joining fails the
previous network is restored. Joining a different network drops remote (SSH)
sessions. Anyone who can touch the screen can change the network, and the
password is briefly visible to local users in the process list while joining.

## Differences from the Python daemon

- The sensor list comes from `sensors.json`, not Postgres. The Pi no longer
  needs database access. Update the file when sensors change.
- No web dashboard yet, and no relay control (`edge/actuator.py`).
- MQTT TLS requires a broker certificate with a subjectAltName. Re-run
  `MQTT_CN=<broker host> bash docker/mosquitto/gen_certs.sh`, redeploy the
  broker certificate and copy the new `ca.crt` to the Pi.

## Develop

```bash
cargo test
cargo clippy --all-targets -- -D warnings
cargo run -- run --mock        # from the repo root
cargo run -- hmi-layout        # regenerate the build sheet and preview
```
