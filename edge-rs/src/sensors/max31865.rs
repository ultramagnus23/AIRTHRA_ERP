//! PT100 probes on MAX31865 SPI amplifiers.

use super::Poller;
use crate::model::{Fault, ReadResult};
use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Clone, Debug, Deserialize)]
pub struct Probe {
    pub cs: u8,
    #[serde(default = "r_ref")]
    pub r_ref: f64,
    #[serde(default = "r0")]
    pub r0: f64,
}

fn r_ref() -> f64 {
    430.0
}
fn r0() -> f64 {
    100.0
}

/// Vbias on, automatic conversion, 3-wire, 50 Hz filter. Without the
/// automatic-conversion bit the chip never updates its result registers.
pub const CONFIG: u8 = 0b1101_0001;

/// Callendar-Van Dusen quadratic (IEC 60751), exact at and above 0 C.
pub fn celsius(ohms: f64, r0: f64) -> Option<f64> {
    const A: f64 = 3.9083e-3;
    const B: f64 = -5.775e-7;
    let discriminant = A * A - 4.0 * B * (1.0 - ohms / r0);
    (discriminant >= 0.0).then(|| (-A + discriminant.sqrt()) / (2.0 * B))
}

/// `raw` is the 16-bit RTD register, whose lowest bit flags a fault.
pub fn convert(raw: u16, fault_status: u8, probe: &Probe) -> ReadResult {
    if raw & 1 != 0 || fault_status != 0 {
        return Err(Fault::new(
            "FAULT",
            format!("MAX31865 fault status 0x{fault_status:02X}"),
        ));
    }
    if raw == 0 {
        return Err(Fault::new("NO REPLY", "amplifier returned all zeros"));
    }
    let ohms = f64::from(raw >> 1) * probe.r_ref / 32768.0;
    celsius(ohms, probe.r0)
        .ok_or_else(|| Fault::new("BAD DATA", format!("{ohms:.1} ohm is not a PT100 value")))
}

pub struct Max31865 {
    probes: BTreeMap<String, Probe>,
    #[cfg(target_os = "linux")]
    devices: BTreeMap<u8, spidev::Spidev>,
}

impl Max31865 {
    pub fn new(probes: BTreeMap<String, Probe>) -> Self {
        Max31865 {
            probes,
            #[cfg(target_os = "linux")]
            devices: BTreeMap::new(),
        }
    }

    /// Returns (RTD register, fault status).
    #[cfg(target_os = "linux")]
    fn transfer(&mut self, cs: u8) -> Result<(u16, u8), Fault> {
        use spidev::{SpiModeFlags, Spidev, SpidevOptions, SpidevTransfer};
        let path = format!("/dev/spidev0.{cs}");
        let fail = |e: std::io::Error| Fault::new("NO PORT", format!("{path}: {e}"));
        if !self.devices.contains_key(&cs) {
            let mut device = Spidev::open(&path).map_err(fail)?;
            let options = SpidevOptions::new()
                .bits_per_word(8)
                .max_speed_hz(500_000)
                .mode(SpiModeFlags::SPI_MODE_1)
                .build();
            device.configure(&options).map_err(fail)?;
            std::io::Write::write_all(&mut device, &[0x80, CONFIG]).map_err(fail)?;
            std::thread::sleep(std::time::Duration::from_millis(150));
            self.devices.insert(cs, device);
        }
        let Some(device) = self.devices.get(&cs) else {
            return Err(Fault::new("NO PORT", path));
        };
        let mut rtd = [0u8; 3];
        device
            .transfer(&mut SpidevTransfer::read_write(&[0x01, 0, 0], &mut rtd))
            .map_err(fail)?;
        let mut status = [0u8; 2];
        device
            .transfer(&mut SpidevTransfer::read_write(&[0x07, 0], &mut status))
            .map_err(fail)?;
        if status[1] != 0 {
            // Clear the latched fault and reconfigure on the next read.
            self.devices.remove(&cs);
        }
        Ok((u16::from_be_bytes([rtd[1], rtd[2]]), status[1]))
    }

    #[cfg(not(target_os = "linux"))]
    fn transfer(&mut self, _cs: u8) -> Result<(u16, u8), Fault> {
        Err(Fault::new("NO PORT", "SPI is only available on Linux"))
    }
}

impl Poller for Max31865 {
    fn name(&self) -> String {
        "max31865".into()
    }

    fn sensor_ids(&self) -> Vec<String> {
        self.probes.keys().cloned().collect()
    }

    fn read(&mut self, sensor_id: &str) -> ReadResult {
        let probe = self
            .probes
            .get(sensor_id)
            .cloned()
            .ok_or_else(|| Fault::new("NOT SET", "unknown sensor"))?;
        let (raw, status) = self.transfer(probe.cs)?;
        convert(raw, status, &probe)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converts_resistance_and_reports_faults() {
        assert!(celsius(100.0, 100.0).unwrap().abs() < 1e-9);
        assert!((celsius(138.5055, 100.0).unwrap() - 100.0).abs() < 0.01);
        let probe = Probe {
            cs: 0,
            r_ref: 430.0,
            r0: 100.0,
        };
        assert_eq!(convert(1, 0, &probe).unwrap_err().short, "FAULT");
        assert_eq!(convert(0, 0, &probe).unwrap_err().short, "NO REPLY");
        let raw = ((100.0 / 430.0 * 32768.0) as u16) << 1;
        assert!(convert(raw, 0, &probe).unwrap().abs() < 0.1);
    }
}
