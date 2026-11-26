//! Settings from environment variables, using the same names as `.env.pi`.

use crate::hmi;
use anyhow::{bail, Context, Result};
use std::path::PathBuf;
use std::time::Duration;

#[derive(Clone)]
pub struct Mqtt {
    pub host: String,
    pub port: u16,
    pub username: String,
    pub password: String,
    /// Set when TLS is on.
    pub ca_cert: Option<PathBuf>,
}

pub struct Config {
    pub plant_id: String,
    pub mock: bool,
    pub maps_dir: PathBuf,
    pub sensors_file: PathBuf,
    pub data_dir: PathBuf,
    pub retention_days: i64,
    pub poll_interval: Duration,
    pub hmi: Option<hmi::Settings>,
    /// None when MQTT_HOST is unset: the screen and local log still work.
    pub mqtt: Option<Mqtt>,
}

fn var(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

fn flag(name: &str) -> bool {
    var(name)
        .is_some_and(|v| matches!(v.to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on"))
}

fn number<T: std::str::FromStr>(name: &str, default: T) -> Result<T>
where
    T::Err: std::error::Error + Send + Sync + 'static,
{
    match var(name) {
        Some(v) => v
            .parse()
            .with_context(|| format!("{name}={v} is not a number")),
        None => Ok(default),
    }
}

pub fn hmi_settings() -> Result<hmi::Settings> {
    let terminator = match var("HMI_TERMINATOR").as_deref() {
        None | Some("none") => Vec::new(),
        Some("lf") => b"\n".to_vec(),
        Some("crlf") => b"\r\n".to_vec(),
        Some(other) => bail!("HMI_TERMINATOR={other}: use none, lf or crlf"),
    };
    Ok(hmi::Settings {
        port: var("HMI_PORT").unwrap_or_else(|| "/dev/serial0".into()),
        baud: number("HMI_BAUD", 115_200)?,
        frame_gap: Duration::from_millis(number("HMI_FRAME_GAP_MS", 15)?),
        terminator,
    })
}

impl Config {
    pub fn load(mock_flag: bool) -> Result<Self> {
        let mode = var("HARDWARE_MODE").unwrap_or_else(|| "real".into());
        let mock = match mode.as_str() {
            "real" => mock_flag,
            "mock" => true,
            other => bail!("HARDWARE_MODE={other}: use real or mock"),
        };
        let plant_id = var("PLANT_ID").unwrap_or_else(|| "goa_pilot_01".into());
        if !plant_id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
        {
            bail!("PLANT_ID may contain only letters, digits, '_' and '-'");
        }
        let mqtt = match var("MQTT_HOST") {
            None => None,
            Some(host) => {
                let tls = flag("MQTT_USE_TLS");
                let ca_cert = var("MQTT_CA_CERT_PATH").map(PathBuf::from);
                if tls && ca_cert.is_none() {
                    bail!("MQTT_USE_TLS is on but MQTT_CA_CERT_PATH is not set");
                }
                let port = if tls {
                    number("MQTT_TLS_PORT", 8883)?
                } else {
                    number("MQTT_DEV_PORT", 1883)?
                };
                Some(Mqtt {
                    host,
                    port,
                    username: var("MQTT_EDGE_USERNAME").unwrap_or_default(),
                    password: var("MQTT_EDGE_PASSWORD").unwrap_or_default(),
                    ca_cert: if tls { ca_cert } else { None },
                })
            }
        };
        Ok(Config {
            plant_id,
            mock,
            maps_dir: var("MAPS_DIR").map_or_else(|| "edge".into(), PathBuf::from),
            sensors_file: var("SENSORS_FILE")
                .map_or_else(|| "edge-rs/sensors.json".into(), PathBuf::from),
            data_dir: var("DATA_DIR").map_or_else(|| "edge-rs/data".into(), PathBuf::from),
            retention_days: number("LOCAL_RETENTION_DAYS", 7)?,
            poll_interval: Duration::from_millis(number("POLL_INTERVAL_MS", 1000)?),
            hmi: if flag("HMI_ENABLED") {
                Some(hmi_settings()?)
            } else {
                None
            },
            mqtt,
        })
    }
}
