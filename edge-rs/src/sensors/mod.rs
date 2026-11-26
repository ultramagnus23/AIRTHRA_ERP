//! Sensor polling. Every bus runs on its own thread and each result is
//! published as soon as it arrives, so one dead device cannot blank the rest.

pub mod max31865;
pub mod modbus;
pub mod onewire;
pub mod pms7003;

use crate::model::{Fault, ReadResult, SensorSpec};
use anyhow::{Context, Result};
use serde::de::DeserializeOwned;
use std::collections::{BTreeMap, HashSet};
use std::path::Path;

/// Something that reads a group of sensors one at a time.
pub trait Poller: Send {
    fn name(&self) -> String;
    fn sensor_ids(&self) -> Vec<String>;
    fn read(&mut self, sensor_id: &str) -> ReadResult;
}

/// Loads a wiring map, ignoring the `_comment` keys.
pub fn load_map<T: DeserializeOwned>(path: &Path) -> Result<BTreeMap<String, T>> {
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let text =
        std::fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
    let raw: BTreeMap<String, serde_json::Value> =
        serde_json::from_str(&text).with_context(|| format!("parsing {}", path.display()))?;
    raw.into_iter()
        .filter(|(key, _)| !key.starts_with('_'))
        .map(|(key, value)| {
            let entry = serde_json::from_value(value)
                .with_context(|| format!("{}: entry {key}", path.display()))?;
            Ok((key, entry))
        })
        .collect()
}

/// Reports a fixed reason for sensors that have no usable wiring entry. A
/// wiring gap shows on the screen instead of stopping the whole daemon.
struct Unwired(Vec<String>);

impl Poller for Unwired {
    fn name(&self) -> String {
        "unwired".into()
    }
    fn sensor_ids(&self) -> Vec<String> {
        self.0.clone()
    }
    fn read(&mut self, _: &str) -> ReadResult {
        Err(Fault::new("NOT SET", "no entry in any wiring map"))
    }
}

/// Builds the real pollers from the wiring maps in `maps`.
pub fn build(sensors: &[SensorSpec], maps: &Path) -> Result<Vec<Box<dyn Poller>>> {
    let known: HashSet<&str> = sensors.iter().map(|s| s.sensor_id.as_str()).collect();
    let mut claimed = HashSet::new();
    let mut claim = |id: &String| -> Result<bool> {
        if !known.contains(id.as_str()) {
            return Ok(false);
        }
        anyhow::ensure!(
            claimed.insert(id.clone()),
            "sensor {id} is in two wiring maps"
        );
        Ok(true)
    };
    let mut pollers: Vec<Box<dyn Poller>> = Vec::new();

    let mut buses: BTreeMap<String, BTreeMap<String, modbus::Register>> = BTreeMap::new();
    for (id, register) in load_map::<modbus::Register>(&maps.join("modbus_map.json"))? {
        if claim(&id)? {
            buses
                .entry(register.bus.clone())
                .or_default()
                .insert(id, register);
        }
    }
    for (bus, registers) in buses {
        pollers.push(Box::new(modbus::Bus::new(bus, registers)));
    }

    let mut probes = load_map::<onewire::Probe>(&maps.join("onewire_map.json"))?;
    probes = filter(probes, &mut claim)?;
    if !probes.is_empty() {
        pollers.push(Box::new(onewire::OneWire::new(
            probes,
            "/sys/bus/w1/devices".into(),
        )));
    }

    let mut channels = BTreeMap::<String, BTreeMap<String, pms7003::Channel>>::new();
    for (id, channel) in load_map::<pms7003::Channel>(&maps.join("pms7003_map.json"))? {
        if claim(&id)? {
            channels
                .entry(channel.device.clone())
                .or_default()
                .insert(id, channel);
        }
    }
    for (device, group) in channels {
        pollers.push(Box::new(pms7003::Pms::new(device, group)));
    }

    let mut rtds = load_map::<max31865::Probe>(&maps.join("max31865_map.json"))?;
    rtds = filter(rtds, &mut claim)?;
    if !rtds.is_empty() {
        pollers.push(Box::new(max31865::Max31865::new(rtds)));
    }

    let unwired: Vec<String> = sensors
        .iter()
        .filter(|s| !claimed.contains(&s.sensor_id))
        .map(|s| s.sensor_id.clone())
        .collect();
    if !unwired.is_empty() {
        pollers.push(Box::new(Unwired(unwired)));
    }
    Ok(pollers)
}

fn filter<T>(
    map: BTreeMap<String, T>,
    claim: &mut impl FnMut(&String) -> Result<bool>,
) -> Result<BTreeMap<String, T>> {
    let mut kept = BTreeMap::new();
    for (id, entry) in map {
        if claim(&id)? {
            kept.insert(id, entry);
        }
    }
    Ok(kept)
}

/// Simulated values for `--mock`.
pub struct Mock {
    sensors: Vec<SensorSpec>,
    started: std::time::Instant,
}

impl Mock {
    pub fn new(sensors: Vec<SensorSpec>) -> Self {
        Mock {
            sensors,
            started: std::time::Instant::now(),
        }
    }
}

impl Poller for Mock {
    fn name(&self) -> String {
        "mock".into()
    }
    fn sensor_ids(&self) -> Vec<String> {
        self.sensors.iter().map(|s| s.sensor_id.clone()).collect()
    }
    fn read(&mut self, sensor_id: &str) -> ReadResult {
        let index = self
            .sensors
            .iter()
            .position(|s| s.sensor_id == sensor_id)
            .ok_or_else(|| Fault::new("NOT SET", "unknown sensor"))?;
        let spec = &self.sensors[index];
        let low = spec.min_valid.unwrap_or(0.0);
        let high = spec.max_valid.unwrap_or(100.0);
        let wave = (self.started.elapsed().as_secs_f64() / 30.0 + index as f64).sin();
        Ok(low + (high - low) * (0.5 + 0.3 * wave))
    }
}
