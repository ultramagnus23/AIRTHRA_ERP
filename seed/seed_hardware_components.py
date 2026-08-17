"""Seed the hardware_components register from the FEED Addendum A (Rev 2)
Full Instrument Schedule (Section 2) and DAQ Hardware BOM (Section 4.1) -
the authoritative, approved-for-construction instrumentation spec for
the 10 TPD biomass ZLD FGD pilot plant. Supersedes the earlier rougher
parts-list draft that fed the first version of this table.

Tag IDs, tiers, segments, and diagnostic purposes match the document
exactly so this register lines up with the fault decision trees (FEED
Section 3) and the segment map (FEED Section 1.1) for future work.

Idempotent: clears and re-inserts on every run (a small, mostly-static
reference table - a diff/upsert isn't worth the complexity here).

Usage: .venv/Scripts/python.exe seed/seed_hardware_components.py
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

# (tag_id | None, item, spec_function (diagnostic purpose), tier | None,
#  segment | None, cost_inr | None)
Row = tuple[str | None, str, str | None, int | None, str | None, float | None]

# (category, category_order, [Row, ...])
CATEGORIES: list[tuple[str, int, list[Row]]] = [
    (
        "Gas Path",
        1,
        [
            ("AT-01", "SO2 analyser", "Most important sensor in the plant. Inlet SO2 load - primary input to every ML model and the mass balance closure equation. Winsen ZE25-SO2 for pilot; certified unit before commercial BOO.", 1, "G-01a", 1800),
            ("TE-01B", "DS18B20 in SS thermowell", "Upstream gas temp reference. Delta with TE-01 proves E-101 is cooling.", 2, "G-01a", 200),
            ("PT-02", "0-500 Pa differential pressure", "B-101 suction draft. VFD shows spinning but PT-02 shows no draft -> duct disconnected or damper stuck.", 2, "G-01a", 400),
            ("VFD-B101", "Modbus RTU from B-101 VFD", "Free data: Hz, current, fault code, drive temp, run hours. Current at same Hz = duct back-pressure proxy.", 1, "B-101 motor", 250),
            ("PT-03", "0-500 Pa differential pressure", "Post-cooler duct pressure. Delta PT-02 to PT-03 = total system resistance; rising = ash blockage.", 2, "G-02a", 400),
            ("TE-01", "DS18B20 in SS thermowell", "TRIP SENSOR. Hard trip at 70C. FRP tower melts above 75C. Non-negotiable.", 1, "G-02b", 200),
            ("TE-trap", "DS18B20 clip-on", "Confirms steam tracing keeping trap above 80C. Below 80C -> SO3 passes through to solvent.", 2, "G-02a", 200),
        ],
    ),
    (
        "Absorber - T-101",
        2,
        [
            ("TE-mid", "DS18B20 in PTFE sleeve", "Absorption is exothermic. Rising TE-mid = absorption happening; flat = solvent not absorbing.", 2, "T-101 mid-packing", 200),
            ("DP-101", "0-500 Pa DP cell across packing bed", "Rising DP = flooding. Falling DP = packing collapse/bypassing.", 2, "T-101", 500),
            ("LE-01", "Submersible pressure level, 4-20mA", "TRIP SENSOR. Hard-trips P-101 at low-low level, 300mm above N4 suction. Also controls P-101 VFD speed.", 1, "T-101 sump", 900),
            ("AE-02", "SO2 CEMS", "TRIP SENSOR. >50 ppm trips gravity bypass damper. Pair with AT-01 for real-time removal efficiency.", 1, "Stack clean gas outlet", 1800),
        ],
    ),
    (
        "Solvent Loop",
        3,
        [
            ("TE-05", "DS18B20 in thermowell", "Rich solvent temp entering pump. Spike with no TE-01 change = exothermic event in sump.", 2, "S-01a", 200),
            ("PT-05", "0-6 bar, 4-20mA", "Discharge head. Rising pressure at normal current = downstream blockage; falling pressure at same Hz = stator slipping.", 2, "S-01b", 700),
            ("VFD-P101", "Modbus RTU from P-101 VFD", "Free data. 7-day rolling avg current trending up >8% = stator wearing - earliest possible warning.", 1, "P-101 motor", 0),
            ("DP-S101", "0-1 bar DP cell", "Rising DP = underflow blocked (ash accumulating). Falling DP = overflow blocked.", 2, "S-101 inlet vs overflow", 500),
            ("TE-06", "DS18B20 in thermowell", "PHE effectiveness numerator. Should reach ~90C; dropping = fouling starting.", 2, "S-01c", 200),
            ("TE-07", "DS18B20 in thermowell", "PHE effectiveness denominator. Should drop to ~65C.", 2, "S-02b", 200),
        ],
    ),
    (
        "E-102 Falling Film Evaporator",
        4,
        [
            ("TE-08", "PT100 + MAX31865 SPI board", "Use PT100, not DS18B20 - 110C continuous too close to DS18B20's 125C limit. Cold feed -> regeneration fails.", 1, "S-01d (N1)", 1150),
            ("PT-07", "0-5 bar, 4-20mA", "Steam pressure. Below 2.5 bar -> E-102 cannot reach 110C. Check first when PT-01 vacuum drops.", 1, "Steam supply (S1)", 700),
            ("TE-11", "DS18B20 clip-on", "Steam trap health. Hot condensate = trap passing live steam; cold + no flow = trap blocked.", 2, "E-102 condensate (S2)", 200),
            ("PT-01", "Vacuum transmitter, 0-1 bar absolute", "TRIP SENSOR. Poll at 1-second intervals. Core FFE interlock, first indicator of multiple fault modes.", 1, "E-102 vapour dome", 700),
            ("TE-09", "PT100 + MAX31865 SPI board", "Lean solvent outlet, 105-110C. If TE-08 and TE-09 converge -> E-102 heat transfer failed (coking or steam fault).", 1, "S-02a (N4)", 1150),
        ],
    ),
    (
        "KOH / Venturi Loop",
        5,
        [
            ("VFD-P103", "Modbus RTU - add VFD to P-103", "P-103 is DOL in base FEED. VFD adds flow proxy, fault codes, and vacuum tuning. Best single purchase in this addendum.", 2, "P-103 KOH motive pump", 4500),
            ("PT-08", "0-6 bar, 4-20mA", "Venturi motive pressure. PT-01 collapse + PT-08 low = P-103 fault; PT-08 normal = Venturi fouled or air ingress.", 2, "A-01a", 700),
            ("TE-12", "DS18B20 in SS thermowell", "Reaction temperature, 85-95C normal. Below 80C = SO2 not stripping or KOH depleted.", 2, "KOH tote / Venturi outlet", 200),
            ("AT-02", "pH-4502C module + BNC electrode", "KOH depletion. Below 7.5 = absorption fails within minutes; below 7.0 = immediate action required. Cooled side-stream sample point required (glass electrode dies at 90C).", 1, "Cooled side-stream", 600),
            ("TE-13", "DS18B20 in tank", "Exotherm monitoring during KOH addition. Alert if temperature rises faster than 5C/min.", 2, "KOH dissolution tank", 200),
            ("LE-03", "JSN-SR04T ultrasonic", "KOH inventory. Below 30% remaining -> alert operator to prepare next batch. Feeds KOH consumption predictor.", 2, "KOH dissolution tank", 350),
            ("TE-AT02-sample", "DS18B20 clip-on", "Confirms AT-02 side-stream sample is below 40C before reaching the pH electrode. Above 40C -> electrode damage imminent.", 2, "AT-02 cooling coil outlet", 200),
        ],
    ),
    (
        "Product Loop & Utilities",
        6,
        [
            ("TE-02", "DS18B20 in thermowell", "TRIP/DIVERT SENSOR. Product >50C -> divert to recirculation. Gate before IBC tote fill.", 1, "A-01b", 200),
            ("TE-E103cw", "DS18B20 x2 clip-on", "Cooling water delta across E-103. Collapsed delta = no coolant flow (P-104 fault); normal delta but TE-02 high = plates fouled.", 2, "E-103 cooling water in/out", 400),
            ("LE-02", "JSN-SR04T ultrasonic", "Tote overflow prevention. Triggers tote-switch alert.", 2, "IBC tote (product)", 350),
            ("SC-tote", "HX711 + 1000 kg load cell set", "Mass balance closure instrument. Tote mass accumulation rate = product bleed rate (kg/hr). Primary label for production ML models.", 2, "IBC tote platform", 1680),
            ("TE-03", "DS18B20 clip-on", "Radiator effectiveness.", 2, "Radiator water outlet (hot)", 200),
            ("TE-04", "DS18B20 clip-on", "Collapsed TE-03/TE-04 delta = radiator fan fault or coolant loss. Cascades to TE-01 high within minutes.", 2, "Radiator water inlet (cold return)", 200),
            ("PT-cool", "0-1 bar submersible", "Slow pressure drop over days = coolant leak before it affects E-101 performance.", 3, "Coolant expansion tank", 350),
        ],
    ),
    (
        "Revenue-Generating Additions",
        7,
        [
            ("AT-03", "Winsen ME2-O2 electrochemical O2", "Boiler efficiency SaaS input - combustion quality index (excess air %). Monthly recal against clean air.", 2, "Inlet gas sampling loop, next to AT-01", 1500),
            ("AT-04", "Winsen ZE25-CO electrochemical CO", "Boiler efficiency SaaS input - incomplete-combustion penalty term in combustion quality index.", 2, "Inlet gas sampling loop", 1800),
            ("EM-01", "PZEM-016 Modbus energy meter", "Skid main power feed. Carbon credit / ESG MRV data architecture input.", 2, "Skid main power feed, DIN rail", 1200),
            ("EM-02", "PZEM-016 Modbus energy meter", "Factory boiler main feed (negotiate access). Second MRV energy input.", 2, "Factory boiler main feed", 1200),
            ("PM-01", "Plantower PMS7003 particulate", "Pilot-grade trend signal only - not CPCB-certifiable. Detects gross violations (stack going black).", 2, "Clean stack exhaust, downstream of AE-02", 800),
            ("TE-enclosure", "DS18B20 inside IP65 DAQ enclosure", "Alert at 55C - fan failure warning before Pi thermally shuts down.", 2, "Inside panel, near Pi", 150),
        ],
    ),
    (
        "DAQ Hardware (Section 4.1)",
        8,
        [
            (None, "Raspberry Pi 4, 4GB", "Main edge compute node. 24/7 in DIN enclosure.", None, None, 5500),
            (None, "128GB USB SSD", "InfluxDB storage. Do not use SD card for DB writes - fails within months under continuous write load.", None, None, 1500),
            (None, "ADS1115 16-bit ADC x3", "4-channel I2C ADC each, 12 analog inputs total. Keep inside panel - never run I2C to the field.", None, None, 540),
            (None, "MAX31865 PT100 board x2", "SPI interface for TE-08 and TE-09. Keep inside panel; run 4-wire PT100 cable to field, not SPI.", None, None, 700),
            (None, "RS-485 to USB adapter x2", "One per VFD Modbus bus - do not share adapters between B-101 and P-101 VFDs.", None, None, 500),
            (None, "8-channel relay module", "Digital outputs: FFE steam solenoid, bypass damper electromagnet, P-101 hard-trip relay.", None, None, 280),
            (None, "Optocoupler input module 8-ch", "Reads VFD dry-contact alarm outputs.", None, None, 200),
            (None, "DIN rail 24V PSU, 5A", "Powers Pi (via DC-DC 5V), sensors, relay board.", None, None, 600),
            (None, "IP65 DIN enclosure, 300x200x150", "Weatherproof. Mount alongside MCC panel in shade.", None, None, 1200),
            (None, "Terminal blocks, DIN rail, cable glands", "Wiring infrastructure - buy a full set.", None, None, 2000),
            (None, "Shielded twisted pair cable, 100m", "For 4-20mA lines and PT100 runs.", None, None, 1500),
            (None, "Ferrite cores x10", "Snap onto cables near VFDs to suppress EMI.", None, None, 200),
            (None, "HX711 load cell amplifier", "For IBC tote scale.", None, None, 180),
            (None, "1000 kg platform load cell set", "Under IBC tote pallet, 4-wire to HX711.", None, None, 1500),
            (None, "250-Ohm precision resistors (pack of 10)", "One per 4-20mA channel - current-to-voltage conversion at panel.", None, None, 200),
            (None, "MAX6369 hardware watchdog IC", "GPIO heartbeat every 30s. Software watchdog cannot recover a kernel hang - this can.", None, None, 200),
            (None, "20VA isolation transformer + EMI filter", "Absorbs VFD harmonic distortion and voltage spikes on the 230V supply feeding the DIN PSU.", None, None, 800),
            (None, "Pi UPS hat / supercapacitor module", "Gives Pi 30-60s clean shutdown on power loss. Prevents InfluxDB filesystem corruption.", None, None, 500),
        ],
    ),
]


def main() -> None:
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM hardware_components"))
        total = 0
        for category, category_order, rows in CATEGORIES:
            for sort_order, (tag_id, item, spec, tier, segment, cost) in enumerate(rows, start=1):
                result = conn.execute(
                    text(
                        """
                        INSERT INTO hardware_components
                            (category, category_order, sort_order, item, spec_function,
                             tag_id, tier, segment, cost_inr)
                        VALUES (:category, :category_order, :sort_order, :item, :spec,
                                :tag_id, :tier, :segment, :cost)
                        """
                    ),
                    {
                        "category": category,
                        "category_order": category_order,
                        "sort_order": sort_order,
                        "item": item,
                        "spec": spec,
                        "tag_id": tag_id,
                        "tier": tier,
                        "segment": segment,
                        "cost": cost,
                    },
                )
                assert result.rowcount == 1, f"insert failed for {item!r}"
                total += 1
    print(f"Seed complete: {total} hardware components across {len(CATEGORIES)} categories")


if __name__ == "__main__":
    main()
