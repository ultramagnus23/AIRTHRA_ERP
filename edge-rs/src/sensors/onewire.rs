//! DS18B20 probes through the kernel's w1 sysfs interface.

use super::Poller;
use crate::model::{Fault, ReadResult};
use serde::Deserialize;
use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Clone, Debug, Deserialize)]
pub struct Probe {
    pub device_id: String,
}

const PLACEHOLDER: &str = "28-000000000000";

/// `w1_slave` is two lines: a CRC verdict, then `t=<millidegrees>`.
pub fn parse(text: &str) -> ReadResult {
    let mut lines = text.trim().lines();
    let crc = lines.next().unwrap_or_default();
    if !crc.trim_end().ends_with("YES") {
        return Err(Fault::new("BAD CRC", "probe reply failed its checksum"));
    }
    let value = lines
        .next()
        .and_then(|l| l.split_once("t="))
        .and_then(|(_, t)| t.trim().parse::<i32>().ok())
        .ok_or_else(|| Fault::new("BAD DATA", "no temperature in w1_slave"))?;
    // 85.000 is the DS18B20 power-on value: no conversion has completed.
    if value == 85_000 {
        return Err(Fault::new(
            "BAD DATA",
            "probe returned its 85 C power-on value",
        ));
    }
    Ok(f64::from(value) / 1000.0)
}

pub struct OneWire {
    probes: BTreeMap<String, Probe>,
    base: PathBuf,
}

impl OneWire {
    pub fn new(probes: BTreeMap<String, Probe>, base: PathBuf) -> Self {
        OneWire { probes, base }
    }
}

impl Poller for OneWire {
    fn name(&self) -> String {
        "1-wire".into()
    }

    fn sensor_ids(&self) -> Vec<String> {
        self.probes.keys().cloned().collect()
    }

    fn read(&mut self, sensor_id: &str) -> ReadResult {
        let id = &self
            .probes
            .get(sensor_id)
            .ok_or_else(|| Fault::new("NOT SET", "unknown sensor"))?
            .device_id;
        let valid = id.len() <= 20 && id.chars().all(|c| c.is_ascii_hexdigit() || c == '-');
        if id == PLACEHOLDER || !valid {
            return Err(Fault::new(
                "NOT SET",
                format!("put this probe's ROM id in onewire_map.json (now '{id}')"),
            ));
        }
        let text = std::fs::read_to_string(self.base.join(id).join("w1_slave"))
            .map_err(|e| Fault::new("NO PROBE", format!("{id}: {e}")))?;
        parse(&text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_good_bad_and_power_on_replies() {
        let good = "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n72 01 4b 46 7f ff 0e 10 57 t=23125\n";
        assert_eq!(parse(good).unwrap(), 23.125);
        assert_eq!(
            parse("x : crc=00 NO\nx t=1\n").unwrap_err().short,
            "BAD CRC"
        );
        assert_eq!(
            parse("x : crc=1c YES\nx t=85000\n").unwrap_err().short,
            "BAD DATA"
        );
    }

    #[test]
    fn placeholder_ids_are_reported_as_not_set() {
        let probes = BTreeMap::from([(
            "t".to_string(),
            Probe {
                device_id: PLACEHOLDER.into(),
            },
        )]);
        let mut bus = OneWire::new(probes, "/nowhere".into());
        assert_eq!(bus.read("t").unwrap_err().short, "NOT SET");
    }
}
