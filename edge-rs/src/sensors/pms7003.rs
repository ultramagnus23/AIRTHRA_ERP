//! PMS7003 particulate sensor. It streams a 32-byte frame about once a second.

use super::Poller;
use crate::model::{Fault, ReadResult};
use serde::Deserialize;
use serialport::{ClearBuffer, SerialPort};
use std::collections::BTreeMap;
use std::io::Read;
use std::time::{Duration, Instant};

const FRAME: usize = 32;

#[derive(Clone, Debug, Deserialize)]
pub struct Channel {
    pub device: String,
    pub metric: String,
}

/// Atmospheric-environment concentrations: [PM1.0, PM2.5, PM10].
pub fn parse(frame: &[u8]) -> Option<[u16; 3]> {
    if frame.len() != FRAME || frame[..2] != [0x42, 0x4D] {
        return None;
    }
    let word = |at: usize| u16::from_be_bytes([frame[at], frame[at + 1]]);
    let sum: u16 = frame[..30]
        .iter()
        .fold(0, |s: u16, &b| s.wrapping_add(u16::from(b)));
    (sum == word(30)).then(|| [word(10), word(12), word(14)])
}

/// Scans the stream for the next valid frame.
fn next_frame(port: &mut impl Read, limit: Duration) -> std::io::Result<Option<[u16; 3]>> {
    let started = Instant::now();
    let mut frame = Vec::with_capacity(FRAME);
    let mut byte = [0u8; 1];
    while started.elapsed() < limit {
        port.read_exact(&mut byte)?;
        let expected = match frame.len() {
            0 => byte[0] == 0x42,
            1 => byte[0] == 0x4D,
            _ => true,
        };
        if !expected {
            frame.clear();
            continue;
        }
        frame.push(byte[0]);
        if frame.len() == FRAME {
            if let Some(values) = parse(&frame) {
                return Ok(Some(values));
            }
            frame.clear();
        }
    }
    Ok(None)
}

pub struct Pms {
    device: String,
    channels: BTreeMap<String, Channel>,
    port: Option<Box<dyn SerialPort>>,
    cache: Option<(Instant, [u16; 3])>,
}

impl Pms {
    pub fn new(device: String, channels: BTreeMap<String, Channel>) -> Self {
        Pms {
            device,
            channels,
            port: None,
            cache: None,
        }
    }

    fn fetch(&mut self) -> Result<[u16; 3], Fault> {
        // One frame serves all three metrics in the same cycle.
        if let Some((at, values)) = self.cache {
            if at.elapsed() < Duration::from_millis(800) {
                return Ok(values);
            }
        }
        if self.port.is_none() {
            let port = serialport::new(&self.device, 9600)
                .timeout(Duration::from_millis(2500))
                .open()
                .map_err(|e| Fault::new("NO PORT", format!("{}: {e}", self.device)))?;
            self.port = Some(port);
        }
        let Some(port) = self.port.as_mut() else {
            return Err(Fault::new("NO PORT", self.device.clone()));
        };
        let _ = port.clear(ClearBuffer::Input); // newest frame, not a backlog
        match next_frame(port, Duration::from_secs(3)) {
            Ok(Some(values)) => {
                self.cache = Some((Instant::now(), values));
                Ok(values)
            }
            Ok(None) => Err(Fault::new(
                "BAD DATA",
                format!("{}: no valid frame", self.device),
            )),
            Err(e) => {
                if e.kind() != std::io::ErrorKind::TimedOut {
                    self.port = None;
                }
                Err(Fault::new("NO REPLY", format!("{}: {e}", self.device)))
            }
        }
    }
}

impl Poller for Pms {
    fn name(&self) -> String {
        format!("pms7003 {}", self.device)
    }

    fn sensor_ids(&self) -> Vec<String> {
        self.channels.keys().cloned().collect()
    }

    fn read(&mut self, sensor_id: &str) -> ReadResult {
        let metric = self.channels.get(sensor_id).map(|c| c.metric.as_str());
        let index = match metric {
            Some("pm1_0") => 0,
            Some("pm2_5") => 1,
            Some("pm10") => 2,
            other => return Err(Fault::new("BAD MAP", format!("unknown metric {other:?}"))),
        };
        self.fetch().map(|values| f64::from(values[index]))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame() -> Vec<u8> {
        let mut f = vec![0u8; FRAME];
        f[..2].copy_from_slice(&[0x42, 0x4D]);
        f[11] = 5;
        f[13] = 12;
        f[15] = 30;
        let sum: u16 = f[..30].iter().map(|&b| u16::from(b)).sum();
        f[30..].copy_from_slice(&sum.to_be_bytes());
        f
    }

    #[test]
    fn resynchronises_and_checks_the_checksum() {
        let mut stream = vec![0x00, 0x42, 0x99];
        stream.extend(frame());
        let got = next_frame(&mut stream.as_slice(), Duration::from_secs(1)).unwrap();
        assert_eq!(got, Some([5, 12, 30]));
        let mut bad = frame();
        bad[13] = 99;
        assert_eq!(parse(&bad), None);
    }
}
