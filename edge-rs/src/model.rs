//! Readings, quality flags and the state shared between threads.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use time::{OffsetDateTime, UtcOffset};

/// Wire codes. Must stay identical to `shared/quality.py`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Quality {
    Good = 0,
    CommError = 1,
    OutOfRange = 2,
    Frozen = 3,
}

/// One entry of the sensor manifest. Same shape as the Python daemon's
/// `edge/cache/manifest_<plant>.json`, so that file can be used as-is.
#[derive(Clone, Debug, Deserialize)]
pub struct SensorSpec {
    pub sensor_id: String,
    #[serde(default)]
    pub unit: String,
    pub min_valid: Option<f64>,
    pub max_valid: Option<f64>,
    pub interface: Option<String>,
}

/// Why a read produced no value. `short` is what the touchscreen shows
/// (8 characters at most); `detail` goes to the log.
#[derive(Clone, Debug, PartialEq)]
pub struct Fault {
    pub short: &'static str,
    pub detail: String,
}

impl Fault {
    pub fn new(short: &'static str, detail: impl Into<String>) -> Self {
        Fault {
            short,
            detail: detail.into(),
        }
    }
}

pub type ReadResult = Result<f64, Fault>;

#[derive(Clone, Debug)]
pub struct Latest {
    pub value: Option<f64>,
    pub quality: Quality,
    pub fault: Option<Fault>,
    pub at: Instant,
}

/// The JSON published over MQTT. Field names are the cloud contract.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Reading {
    pub plant_id: String,
    pub sensor_id: String,
    pub ts: String,
    pub value: Option<f64>,
    pub quality_flag: u8,
    pub source: String,
}

#[derive(Default)]
pub struct State {
    pub latest: BTreeMap<String, Latest>,
    pub cloud_connected: bool,
    pub clock_ok: bool,
    pub unsent: u64,
}

pub type Shared = Arc<Mutex<State>>;

/// A panic in one thread must not freeze the screen for the others.
pub fn lock(shared: &Shared) -> MutexGuard<'_, State> {
    shared
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Applies the manifest's valid range to a raw read.
pub fn classify(spec: &SensorSpec, result: ReadResult) -> Latest {
    let at = Instant::now();
    match result {
        Ok(v) if v.is_finite() => {
            let low = spec.min_valid.is_some_and(|lo| v < lo);
            let high = spec.max_valid.is_some_and(|hi| v > hi);
            let quality = if low || high {
                Quality::OutOfRange
            } else {
                Quality::Good
            };
            Latest {
                value: Some(v),
                quality,
                fault: None,
                at,
            }
        }
        Ok(v) => Latest {
            value: None,
            quality: Quality::CommError,
            fault: Some(Fault::new("BAD DATA", format!("non-finite value {v}"))),
            at,
        },
        Err(fault) => Latest {
            value: None,
            quality: Quality::CommError,
            fault: Some(fault),
            at,
        },
    }
}

/// UTC timestamp in the Python daemon's format. Fixed width, so timestamps
/// also sort correctly as text.
pub fn rfc3339(t: OffsetDateTime) -> String {
    let t = t.to_offset(UtcOffset::UTC);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:06}+00:00",
        t.year(),
        u8::from(t.month()),
        t.day(),
        t.hour(),
        t.minute(),
        t.second(),
        t.microsecond()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec() -> SensorSpec {
        SensorSpec {
            sensor_id: "pH".into(),
            unit: "pH".into(),
            min_valid: Some(0.0),
            max_valid: Some(14.0),
            interface: Some("modbus".into()),
        }
    }

    #[test]
    fn range_and_fault_classification() {
        assert_eq!(classify(&spec(), Ok(7.0)).quality, Quality::Good);
        assert_eq!(classify(&spec(), Ok(15.0)).quality, Quality::OutOfRange);
        assert_eq!(classify(&spec(), Ok(f64::NAN)).value, None);
        let failed = classify(&spec(), Err(Fault::new("NO REPLY", "timeout")));
        assert_eq!(failed.quality, Quality::CommError);
        assert_eq!(failed.value, None);
    }
}
