# Pi setup: flash, wire, run

Target: Raspberry Pi 4. Not yet tried on real hardware, including the Linux
build of this code. Do the stages in order; each one works without the next.

**Power off the Pi and the 24 V supply before changing any wiring.**

## 1. Flash the SD card (on the PC)

1. Raspberry Pi Imager → Raspberry Pi 4 → **Raspberry Pi OS Lite (64-bit)**,
   Bookworm or newer.
2. In the OS settings set a hostname (`airthra-pi`), your own username and
   password, Wi-Fi name, password and country, and enable SSH.
3. Write, insert in the Pi, power on, wait two minutes.

## 2. Copy the code (PowerShell, in the repo folder)

Until the changes are committed and pushed, `git clone` will not include them.
Copy them directly; replace `USER` with the username from step 1.

```powershell
tar -czf $env:TEMP\airthra-pi.tgz --exclude=target --exclude=data --exclude=cache --exclude=__pycache__ edge edge-rs
```

```powershell
scp $env:TEMP\airthra-pi.tgz USER@airthra-pi.local:
```

```powershell
ssh USER@airthra-pi.local
```

## 3. Prepare the Pi

```bash
mkdir -p airthra && tar -xzf airthra-pi.tgz -C airthra && cd airthra
sudo raspi-config nonint do_serial_cons 1    # no login shell on the UART
sudo raspi-config nonint do_serial_hw 0      # UART on (screen)
sudo raspi-config nonint do_spi 0            # SPI on (PT100 boards)
echo "dtoverlay=w1-gpio,gpiopin=2" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

## 4. Build and install (on the Pi, after reconnecting)

```bash
cd airthra
sudo apt update && sudo apt install -y build-essential curl
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
cargo build --release --locked --manifest-path edge-rs/Cargo.toml
```

```bash
sudo useradd --system --no-create-home -G dialout,spi airthra
sudo install -d /opt/airthra-edge/maps
sudo install edge-rs/target/release/airthra-edge /opt/airthra-edge/
sudo install -m 644 edge-rs/sensors.json /opt/airthra-edge/
sudo install -m 644 edge/*_map.json /opt/airthra-edge/maps/
sudo install -m 600 edge-rs/deploy/airthra-edge.env.example /etc/airthra-edge.env
sudo install -m 644 edge-rs/deploy/50-airthra-network.rules /etc/polkit-1/rules.d/
sudo install -m 644 edge-rs/deploy/airthra-edge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now airthra-edge
journalctl -u airthra-edge -f
```

With nothing wired, every sensor reports why it fails. That is expected.
If the old Python container is on this Pi, stop it first:
`docker compose -f docker-compose.pi.yml down`.

The check command, used after wiring each group (stop the service first so the
two do not share the serial ports):

```bash
sudo systemctl stop airthra-edge
sudo -u airthra env MAPS_DIR=/opt/airthra-edge/maps SENSORS_FILE=/opt/airthra-edge/sensors.json /opt/airthra-edge/airthra-edge check
sudo systemctl start airthra-edge
```

Edit wiring maps in `/opt/airthra-edge/maps/`, then restart the service.

## 5. Wiring

### Touchscreen (SmartElex 4.0")

| Screen | Pi pin |
|---|---|
| VCC | 2 (5V) |
| GND | 6 |
| TX | 10 (GPIO15, RXD) |
| RX | 8 (GPIO14, TXD) |

Measure the screen's TX voltage before connecting it. Near 5 V needs a level
shifter. Load the layout as in
[hmi/SCREEN_QUICKSTART.md](hmi/SCREEN_QUICKSTART.md).

### DS18B20 temperature probes (15)

| Probe wire | Pi pin |
|---|---|
| Data | 3 (GPIO2) |
| VDD | 1 (**3.3V**, not 5V) |
| GND | 9 |

All share the three wires. GPIO2 has a 1.8 kΩ pull-up on the board. Check the
wire colours on your probes' datasheet. Connect **one new probe at a time**:

```bash
ls /sys/bus/w1/devices
```

Each new `28-...` entry is that probe. Put it in `onewire_map.json` and label
the probe.

### PT100 probes on MAX31865 (TE_08, TE_09)

| Board | Pi pin |
|---|---|
| VIN | 17 (3.3V) |
| GND | 20 |
| CLK | 23 |
| SDO | 21 |
| SDI | 19 |
| CS, TE_08 board | 24 (CE0) |
| CS, TE_09 board | 26 (CE1) |

The software is set for **3-wire** PT100: set the board's solder jumpers to
match. The parts list mentions 4-wire cable, so confirm which you have; 4-wire
needs a one-bit change in `src/sensors/max31865.rs`. Read the reference
resistor on each board (`431` = 430 Ω) and set `r_ref` in `max31865_map.json`.

### RS-485 devices (two USB adapters)

Connect A to A, B to B, and signal ground. If a bus is silent, swap A and B.
All devices must use **9600 baud, 8N1**, and each address on a bus must be
unique.

| Adapter | Device | Address | Sensors |
|---|---|---|---|
| 1 | Waveshare 8-ch analog | 1 | IN1 `PT_01`, IN2 `PT_05`, IN3 `PT_08`, IN4 `LE_01`, IN7 `o2_pct` |
| 1 | SO2 inlet | 3 (confirm register) | `SO2_in` |
| 1 | SO2 outlet | 4 (confirm register) | `SO2_out` |
| 1 or 2 | not yet known | **set in the map** | `pH` |
| 2 | not yet known | **set in the map** | `temp_C`, `flow`, `level_KOH_tank`, `level_K2SO3_tank` |

Take each address, register, data type and scale from that device's datasheet.
The relay module (address 2) is not driven by the Rust daemon.

For the 4-20 mA transmitters, follow the Waveshare module's manual for loop
power and set the channels to 4-20 mA mode. The map expects raw microamps
(4000 to 20000).

USB port numbers can swap after a reboot. Use stable names in the maps:

```bash
ls -l /dev/serial/by-id/
```

Put the full `/dev/serial/by-id/...` path in `bus`. Identical adapters without
serial numbers need `/dev/serial/by-path/` instead.

### PMS7003 (its own USB-to-TTL adapter, 3.3 V logic)

Sensor VCC → 5V, GND → GND, sensor TXD → adapter RXD. Put the adapter's path in
all three entries of `pms7003_map.json`.

## 6. Post to the cloud

The Render broker is private, so the Pi cannot reach it. For a first test, run
the stack on a PC on the same network. Needs Docker Desktop running.

On the PC (replace `PC_IP`). Regenerating certificates replaces the old ones:

```powershell
$env:MQTT_CN="PC_IP"; $env:MSYS_NO_PATHCONV="1"; & "C:\Program Files\Git\bin\bash.exe" docker/mosquitto/gen_certs.sh
```

```powershell
docker compose up -d
```

```powershell
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
```

```powershell
.venv\Scripts\python -m alembic upgrade head
```

```powershell
.venv\Scripts\python seed/seed.py
```

```powershell
.venv\Scripts\python ingest/service.py
```

Allow inbound TCP 8883 on private networks in Windows Firewall. Change the
development MQTT passwords before using any network you do not control:

```powershell
docker compose exec mosquitto mosquitto_passwd /mosquitto/config/passwd goa_pilot_01_edge
```

```powershell
docker compose restart mosquitto
```

Copy the certificate (public file only, never `ca.key`):

```powershell
scp docker/mosquitto/certs/ca.crt USER@airthra-pi.local:
```

On the Pi:

```bash
sudo install -m 644 ~/ca.crt /etc/airthra-edge-ca.crt
sudo nano /etc/airthra-edge.env   # MQTT_HOST=PC_IP, username, password
sudo systemctl restart airthra-edge
```

The screen's status page should show `CLOUD OK` and `SENT` rising.
