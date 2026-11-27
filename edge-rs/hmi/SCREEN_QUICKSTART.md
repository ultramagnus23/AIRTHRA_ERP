# Get the SmartElex screen working

The layout is already built: `airthra.TFT` in this folder (four pages).

## 1. Load it onto the screen
1. Use a microSD card, FAT32, 32 GB or smaller.
2. Copy `airthra.TFT` to the **root** of the card: no folders, no other `.TFT`.
3. With the screen off, insert the card, then power it with 5 V (at least 1 A).
4. You should see `AIRTHRA` and four buttons: PREV, NEXT, WI-FI, STATUS.
   Values stay blank until the software is connected.

## 2. Wire to the PC (power off), no Pi needed
Needs a USB-to-serial adapter.

| Screen | Connect to |
|---|---|
| VCC | 5 V supply + |
| GND | supply − **and** adapter GND |
| TX | adapter RXD |
| RX | adapter TXD |

Do not connect the adapter's power pin. Measure the screen's TX voltage with
the screen powered, before attaching it to a 3.3 V adapter.

## 3. Probe (PowerShell, repo root)

```powershell
Get-CimInstance Win32_PnPEntity | Where-Object Name -match '\(COM\d+\)' | Select-Object Name
```

Replace `COM5`:

```powershell
$env:HMI_PORT="COM5"; .\edge-rs\target\release\airthra-edge.exe hmi-probe
```

The top line should count `TEST 1`, `TEST 2`... and tapping PREV should print a
`got ...` line decoded as `page: 0, kind: 4, id: 0`.

| Symptom | Try, one at a time (Ctrl-C first) |
|---|---|
| No text | swap TX/RX; `$env:HMI_TERMINATOR="lf"`, then `"crlf"`; `$env:HMI_BAUD="9600"` |
| No `got` line on tap | check screen TX → adapter RXD |
| Only every second tap works | note the printed values and report them |

## 4. Live screen

```powershell
$env:HMI_ENABLED="true"; .\edge-rs\target\release\airthra-edge.exe run --mock
```

Readings and Wi-Fi are **simulated** on the PC (password `airthra123`).

**Check on pages 2 and 3:** network names and key letters must be visible. The
editor draws touch areas as solid blocks over them. If the screen does the same,
report it; the layout needs changing.

## 5. Move to the Pi
Same card. Wire as in [../PI_SETUP.md](../PI_SETUP.md); put any changed baud
rate or terminator in `/etc/airthra-edge.env`.

## Changing the layout
Edit `src/hmi/layout.rs`, run
`cargo run --manifest-path edge-rs/Cargo.toml -- hmi-layout`, open
`airthra.hmi` in Robu's HMI Editor and choose **Generate Output**.
