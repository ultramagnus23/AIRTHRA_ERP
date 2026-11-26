//! Modbus RTU register reads (functions 0x03 and 0x04) over RS-485.

use super::Poller;
use crate::model::{Fault, ReadResult};
use serde::Deserialize;
use serialport::{ClearBuffer, SerialPort};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::time::Duration;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Register {
    pub bus: String,
    pub slave_id: u8,
    pub register: u16,
    #[serde(default = "holding")]
    pub register_type: String,
    #[serde(default = "one")]
    pub count: u16,
    #[serde(default = "int16")]
    pub datatype: String,
    #[serde(default = "unit_scale")]
    pub scale: f64,
    #[serde(default)]
    pub offset: f64,
    #[serde(default = "big")]
    pub word_order: String,
}

fn holding() -> String {
    "holding".into()
}
fn one() -> u16 {
    1
}
fn int16() -> String {
    "int16".into()
}
fn unit_scale() -> f64 {
    1.0
}
fn big() -> String {
    "big".into()
}

pub fn crc16(data: &[u8]) -> u16 {
    data.iter().fold(0xFFFF, |mut crc, &byte| {
        crc ^= u16::from(byte);
        for _ in 0..8 {
            crc = if crc & 1 != 0 {
                (crc >> 1) ^ 0xA001
            } else {
                crc >> 1
            };
        }
        crc
    })
}

pub fn request(slave: u8, function: u8, address: u16, count: u16) -> [u8; 8] {
    let [ah, al] = address.to_be_bytes();
    let [ch, cl] = count.to_be_bytes();
    let mut frame = [slave, function, ah, al, ch, cl, 0, 0];
    let [lo, hi] = crc16(&frame[..6]).to_le_bytes();
    frame[6] = lo;
    frame[7] = hi;
    frame
}

/// Reads one reply from the stream and returns the registers.
pub fn read_response(
    port: &mut impl Read,
    slave: u8,
    function: u8,
    count: u16,
) -> Result<Vec<u16>, Fault> {
    let silent = |e: std::io::Error| Fault::new("NO REPLY", format!("slave {slave}: {e}"));
    let mut frame = vec![0u8; 3];
    port.read_exact(&mut frame).map_err(silent)?;
    let exception = frame[1] == function | 0x80;
    let data_len = usize::from(count) * 2;
    if frame[0] != slave
        || (!exception && (frame[1] != function || usize::from(frame[2]) != data_len))
    {
        return Err(Fault::new(
            "BAD DATA",
            format!("unexpected reply header {frame:02X?}"),
        ));
    }
    // An exception reply is 5 bytes; a data reply is header + data + CRC.
    let rest = if exception { 2 } else { data_len + 2 };
    frame.resize(3 + rest, 0);
    port.read_exact(&mut frame[3..]).map_err(silent)?;
    let body = frame.len() - 2;
    if crc16(&frame[..body]).to_le_bytes() != frame[body..] {
        return Err(Fault::new(
            "BAD CRC",
            format!("slave {slave}: checksum mismatch"),
        ));
    }
    if exception {
        return Err(Fault::new(
            "BAD REG",
            format!(
                "slave {slave} rejected the request with exception {}",
                frame[2]
            ),
        ));
    }
    Ok(frame[3..body]
        .chunks(2)
        .map(|c| u16::from_be_bytes([c[0], c[1]]))
        .collect())
}

pub fn decode(registers: &[u16], map: &Register) -> ReadResult {
    let wide = || -> Option<u32> {
        let (&a, &b) = (registers.first()?, registers.get(1)?);
        let (high, low) = if map.word_order == "little" {
            (b, a)
        } else {
            (a, b)
        };
        Some(u32::from(high) << 16 | u32::from(low))
    };
    let raw = match (map.datatype.as_str(), map.count) {
        ("int16", 1) => registers.first().map(|&r| f64::from(r as i16)),
        ("uint16", 1) => registers.first().map(|&r| f64::from(r)),
        ("int32", 2) => wide().map(|v| f64::from(v as i32)),
        ("uint32", 2) => wide().map(f64::from),
        ("float32", 2) => wide().map(|v| f64::from(f32::from_bits(v))),
        _ => None,
    };
    raw.map(|r| r * map.scale + map.offset).ok_or_else(|| {
        Fault::new(
            "BAD MAP",
            format!("unsupported datatype {} x{}", map.datatype, map.count),
        )
    })
}

pub struct Bus {
    path: String,
    registers: BTreeMap<String, Register>,
    port: Option<Box<dyn SerialPort>>,
}

impl Bus {
    pub fn new(path: String, registers: BTreeMap<String, Register>) -> Self {
        Bus {
            path,
            registers,
            port: None,
        }
    }
}

impl Poller for Bus {
    fn name(&self) -> String {
        format!("modbus {}", self.path)
    }

    fn sensor_ids(&self) -> Vec<String> {
        self.registers.keys().cloned().collect()
    }

    fn read(&mut self, sensor_id: &str) -> ReadResult {
        let map = self
            .registers
            .get(sensor_id)
            .ok_or_else(|| Fault::new("NOT SET", "unknown sensor"))?;
        // Address 0 is broadcast: no device ever answers it.
        if map.slave_id == 0 || map.slave_id > 247 {
            return Err(Fault::new(
                "NOT SET",
                format!(
                    "slave_id {} is not a device address; set it in modbus_map.json",
                    map.slave_id
                ),
            ));
        }
        if !(1..=2).contains(&map.count) {
            return Err(Fault::new(
                "BAD MAP",
                format!("count {} is unsupported", map.count),
            ));
        }
        let function = match map.register_type.as_str() {
            "holding" => 0x03,
            "input" => 0x04,
            other => return Err(Fault::new("BAD MAP", format!("register_type {other}"))),
        };
        if self.port.is_none() {
            let port = serialport::new(&self.path, 9600)
                .timeout(Duration::from_millis(500))
                .open()
                .map_err(|e| Fault::new("NO PORT", format!("{}: {e}", self.path)))?;
            self.port = Some(port);
        }
        let Some(port) = self.port.as_mut() else {
            return Err(Fault::new("NO PORT", self.path.clone()));
        };
        // Silent interval between frames, then drop any late bytes.
        std::thread::sleep(Duration::from_millis(5));
        let sent = port
            .clear(ClearBuffer::Input)
            .map_err(std::io::Error::from)
            .and_then(|_| {
                port.write_all(&request(map.slave_id, function, map.register, map.count))
            });
        if let Err(e) = sent {
            self.port = None; // adapter unplugged: reopen next time
            return Err(Fault::new("NO PORT", format!("{}: {e}", self.path)));
        }
        let registers = read_response(port, map.slave_id, function, map.count)?;
        decode(&registers, map)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn map(datatype: &str, count: u16, scale: f64, offset: f64) -> Register {
        serde_json::from_value(serde_json::json!({
            "bus": "x", "slave_id": 1, "register": 0, "datatype": datatype,
            "count": count, "scale": scale, "offset": offset
        }))
        .unwrap()
    }

    fn reply(body: &[u8]) -> Vec<u8> {
        let mut frame = body.to_vec();
        frame.extend(crc16(body).to_le_bytes());
        frame
    }

    #[test]
    fn builds_the_standard_request_frame() {
        assert_eq!(
            request(1, 3, 0, 1),
            [0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A]
        );
    }

    #[test]
    fn reads_data_exception_and_corruption() {
        let ok = reply(&[1, 4, 2, 0x2E, 0xE0]);
        assert_eq!(
            read_response(&mut ok.as_slice(), 1, 4, 1).unwrap(),
            vec![12000]
        );
        let exception = reply(&[1, 0x83, 2]);
        assert_eq!(
            read_response(&mut exception.as_slice(), 1, 3, 1)
                .unwrap_err()
                .short,
            "BAD REG"
        );
        let mut bad = ok.clone();
        bad[4] ^= 1;
        assert_eq!(
            read_response(&mut bad.as_slice(), 1, 4, 1)
                .unwrap_err()
                .short,
            "BAD CRC"
        );
        assert_eq!(
            read_response(&mut [].as_slice(), 1, 4, 1)
                .unwrap_err()
                .short,
            "NO REPLY"
        );
        assert_eq!(
            read_response(&mut ok.as_slice(), 2, 4, 1)
                .unwrap_err()
                .short,
            "BAD DATA"
        );
    }

    #[test]
    fn decodes_types_and_scales_waveshare_microamps() {
        // 12 mA on a 1..25 % oxygen channel is mid-scale.
        let o2 = decode(&[12000], &map("int16", 1, 0.0015, -5.0)).unwrap();
        assert!((o2 - 13.0).abs() < 1e-9);
        assert_eq!(decode(&[0xFFFF], &map("int16", 1, 1.0, 0.0)).unwrap(), -1.0);
        assert_eq!(
            decode(&[0x3FC0, 0], &map("float32", 2, 1.0, 0.0)).unwrap(),
            1.5
        );
        assert!(decode(&[1], &map("float32", 2, 1.0, 0.0)).is_err());
    }
}
