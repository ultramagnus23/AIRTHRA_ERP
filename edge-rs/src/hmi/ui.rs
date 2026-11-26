//! Screen behaviour with no I/O: touches go in, text field contents and
//! Wi-Fi requests come out.

use super::layout::{KEY_SLOTS, LIVE_ROWS, WIFI_ROWS};
use crate::model::{Quality, SensorSpec, State};
use crate::wifi::{Network, Request, Response, Secret};
use std::collections::HashMap;
use std::time::Duration;

/// A reading older than this is shown as old rather than current.
const STALE_AFTER: Duration = Duration::from_secs(30);
const MAX_PASSWORD: usize = 63;
const PASSWORD_VISIBLE: usize = 24;

/// Every printable ASCII character, in layers of `KEY_SLOTS`.
const LAYERS: [&str; 5] = [
    "abcdefghijklmnopqrst",
    "uvwxyz0123456789.-_@",
    "ABCDEFGHIJKLMNOPQRST",
    "UVWXYZ !\"#$%&'()*+,/",
    ":;<=>?[\\]^`{|}~",
];

pub struct Ui {
    sensors: Vec<SensorSpec>,
    live_page: usize,
    networks: Vec<Network>,
    wifi_page: usize,
    selected: Option<Network>,
    password: String,
    show_password: bool,
    layer: usize,
    message: String,
    busy: bool,
    ssid: String,
    ip: String,
}

impl Ui {
    pub fn new(sensors: Vec<SensorSpec>) -> Self {
        Ui {
            sensors,
            live_page: 0,
            networks: Vec::new(),
            wifi_page: 0,
            selected: None,
            password: String::new(),
            show_password: false,
            layer: 0,
            message: "TAP SCAN".into(),
            busy: false,
            ssid: String::new(),
            ip: String::new(),
        }
    }

    fn live_pages(&self) -> usize {
        self.sensors.len().div_ceil(LIVE_ROWS).max(1)
    }

    fn wifi_pages(&self) -> usize {
        self.networks.len().div_ceil(WIFI_ROWS).max(1)
    }

    /// Handles a press on the named widget.
    pub fn press(&mut self, name: &str) -> Option<Request> {
        let index = |prefix: &str| {
            name.strip_prefix(prefix)
                .and_then(|n| n.parse::<usize>().ok())
        };
        match name {
            "prev" => self.live_page = (self.live_page + self.live_pages() - 1) % self.live_pages(),
            "next" => self.live_page = (self.live_page + 1) % self.live_pages(),
            "scan" if !self.busy => {
                self.busy = true;
                self.message = "SCANNING...".into();
                return Some(Request::Scan);
            }
            "more" => self.wifi_page = (self.wifi_page + 1) % self.wifi_pages(),
            "layer" => self.layer = (self.layer + 1) % LAYERS.len(),
            "del" => {
                self.password.pop();
            }
            "clear" => self.password.clear(),
            "show" => self.show_password = !self.show_password,
            "join" => return self.join(),
            _ => {
                if let Some(row) = index("pick") {
                    self.pick(self.wifi_page * WIFI_ROWS + row);
                } else if let Some(slot) = index("tap") {
                    if let Some(c) = LAYERS[self.layer].chars().nth(slot) {
                        if self.password.len() < MAX_PASSWORD {
                            self.password.push(c);
                        }
                    }
                }
            }
        }
        None
    }

    fn pick(&mut self, at: usize) {
        let Some(network) = self.networks.get(at).cloned() else {
            return;
        };
        if self.selected.as_ref().map(|s| &s.ssid) != Some(&network.ssid) {
            self.password.clear();
        }
        self.show_password = false;
        self.layer = 0;
        self.message = if network.secured {
            "TAP PASSWORD"
        } else {
            "OPEN NETWORK"
        }
        .into();
        self.selected = Some(network);
    }

    fn join(&mut self) -> Option<Request> {
        if self.busy {
            return None;
        }
        let Some(network) = self.selected.clone() else {
            self.message = "PICK NETWORK".into();
            return None;
        };
        if network.secured && self.password.len() < 8 {
            self.message = "MIN 8 CHARS".into();
            return None;
        }
        let password = network.secured.then(|| Secret(self.password.clone()));
        self.busy = true;
        self.message = "CONNECTING..".into();
        Some(Request::Connect {
            ssid: network.ssid,
            password,
        })
    }

    /// Applies the result of a Wi-Fi request.
    pub fn wifi_result(&mut self, response: Response) {
        match response {
            Response::Scanned(Ok(networks)) => {
                self.busy = false;
                self.message = if networks.is_empty() {
                    "NONE FOUND"
                } else {
                    "TAP NETWORK"
                }
                .into();
                self.networks = networks;
                self.wifi_page = 0;
            }
            Response::Scanned(Err(e)) => {
                self.busy = false;
                eprintln!("wifi: scan failed: {e}");
                self.message = "SCAN FAILED".into();
            }
            Response::Connected(Ok(())) => {
                self.busy = false;
                self.password.clear();
                self.show_password = false;
                self.message = "CONNECTED".into();
            }
            Response::Connected(Err(e)) => {
                self.busy = false;
                eprintln!("wifi: connect failed: {e}");
                self.message = "JOIN FAILED".into();
            }
            Response::Status { ssid, ip } => {
                self.ssid = ssid;
                self.ip = ip;
            }
        }
    }

    /// The text every field should currently show, keyed by widget name.
    pub fn render(&self, state: &State) -> HashMap<String, String> {
        let mut out = HashMap::new();
        let mut set = |name: String, value: String| {
            out.insert(name, value);
        };

        // Live page.
        set(
            "cloud".into(),
            if state.cloud_connected {
                "CLOUD OK"
            } else {
                "CLOUD DOWN"
            }
            .into(),
        );
        set(
            "pageno".into(),
            format!("{}/{}", self.live_page + 1, self.live_pages()),
        );
        set(
            "net".into(),
            if self.ssid.is_empty() {
                "NO WI-FI".into()
            } else {
                self.ssid.clone()
            },
        );
        let alert = if !state.clock_ok {
            "CLOCK BAD".to_string()
        } else {
            let good = state
                .latest
                .values()
                .filter(|l| l.quality == Quality::Good && l.at.elapsed() < STALE_AFTER)
                .count();
            format!("{good}/{} OK", self.sensors.len())
        };
        set("alert".into(), alert);
        for row in 0..LIVE_ROWS {
            let sensor = self.sensors.get(self.live_page * LIVE_ROWS + row);
            let (name, value, status) = match sensor {
                None => Default::default(),
                Some(s) => {
                    let (value, status) = reading_text(s, state);
                    (short_name(&s.sensor_id), value, status)
                }
            };
            set(format!("name{row}"), name);
            set(format!("value{row}"), value);
            set(format!("state{row}"), status);
        }

        // Network list.
        set("current".into(), self.ssid.clone());
        set("ip_a".into(), self.ip.chars().take(12).collect());
        set("ip_b".into(), self.ip.chars().skip(12).collect());
        set("wmsg".into(), self.message.clone());
        for row in 0..WIFI_ROWS {
            let network = self.networks.get(self.wifi_page * WIFI_ROWS + row);
            let (ssid, signal) = match network {
                None => Default::default(),
                Some(n) => {
                    let chosen = self.selected.as_ref().is_some_and(|s| s.ssid == n.ssid);
                    let ssid = if chosen {
                        format!(">{}", n.ssid)
                    } else {
                        n.ssid.clone()
                    };
                    let lock = if n.secured { "LOCK" } else { "OPEN" };
                    (ssid, format!("{:>3}% {lock}", n.signal))
                }
            };
            set(format!("ssid{row}"), ssid);
            set(format!("sig{row}"), signal);
        }

        // Keypad.
        let target = self.selected.as_ref().map_or("", |n| n.ssid.as_str());
        for i in 0..3 {
            set(
                format!("target{i}"),
                target.chars().skip(i * 12).take(12).collect(),
            );
        }
        let skip = self.password.len().saturating_sub(PASSWORD_VISIBLE);
        let visible: String = if self.show_password {
            self.password.chars().skip(skip).collect()
        } else {
            "*".repeat(self.password.len() - skip)
        };
        set("pass0".into(), visible.chars().take(12).collect());
        set("pass1".into(), visible.chars().skip(12).collect());
        set("kmsg".into(), self.message.clone());
        set("count".into(), format!("{} ch", self.password.len()));
        for slot in 0..KEY_SLOTS {
            let label = match LAYERS[self.layer].chars().nth(slot) {
                Some(' ') => "SPC".to_string(),
                Some(c) => format!(" {c}"),
                None => String::new(),
            };
            set(format!("key{slot}"), label);
        }
        out
    }
}

/// Value and unit-or-reason columns for one sensor.
fn reading_text(spec: &SensorSpec, state: &State) -> (String, String) {
    let Some(latest) = state.latest.get(&spec.sensor_id) else {
        return ("---".into(), "WAITING".into());
    };
    let value = latest.value.map_or_else(|| "---".into(), format_value);
    let status = if latest.at.elapsed() >= STALE_AFTER {
        "OLD".into()
    } else {
        match latest.quality {
            Quality::Good => spec.unit.clone(),
            Quality::OutOfRange => "RANGE!".into(),
            Quality::Frozen => "STUCK!".into(),
            Quality::CommError => latest
                .fault
                .as_ref()
                .map_or("ERROR", |f| f.short)
                .to_string(),
        }
    };
    (value, status)
}

fn format_value(v: f64) -> String {
    let magnitude = v.abs();
    if magnitude >= 100_000.0 {
        format!("{v:.2e}")
    } else if magnitude >= 100.0 {
        format!("{v:.1}")
    } else {
        format!("{v:.3}")
    }
}

/// Fits a sensor ID into 12 characters while keeping it distinguishable.
fn short_name(id: &str) -> String {
    let id = id
        .replace("temp_probe_", "TEMP ")
        .replace("level_", "LVL ")
        .replace("_tank", "");
    id.chars().take(12).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{classify, Fault};

    fn sensors(n: usize) -> Vec<SensorSpec> {
        (0..n)
            .map(|i| SensorSpec {
                sensor_id: format!("s{i:02}"),
                unit: "bar".into(),
                min_valid: Some(0.0),
                max_valid: Some(10.0),
                interface: None,
            })
            .collect()
    }

    fn network(ssid: &str, secured: bool) -> Network {
        Network {
            ssid: ssid.into(),
            signal: 70,
            secured,
            active: false,
        }
    }

    fn type_text(ui: &mut Ui, text: &str) {
        for c in text.chars() {
            let layer = LAYERS.iter().position(|l| l.contains(c)).unwrap();
            while ui.layer != layer {
                ui.press("layer");
            }
            let slot = LAYERS[layer].chars().position(|k| k == c).unwrap();
            ui.press(&format!("tap{slot}"));
        }
    }

    #[test]
    fn keypad_covers_all_printable_ascii_exactly_once() {
        let mut all: Vec<char> = LAYERS.concat().chars().collect();
        all.sort_unstable();
        assert_eq!(all, (' '..='~').collect::<Vec<_>>());
        assert!(LAYERS.iter().all(|l| l.len() <= KEY_SLOTS));
    }

    #[test]
    fn shows_values_faults_and_pages_through_all_sensors() {
        let list = sensors(10);
        let mut state = State {
            clock_ok: true,
            ..State::default()
        };
        state
            .latest
            .insert("s00".into(), classify(&list[0], Ok(4.5)));
        state.latest.insert(
            "s01".into(),
            classify(&list[1], Err(Fault::new("NO REPLY", "x"))),
        );
        let mut ui = Ui::new(list);
        let screen = ui.render(&state);
        assert_eq!(screen["value0"], "4.500");
        assert_eq!(screen["state0"], "bar");
        assert_eq!(screen["state1"], "NO REPLY");
        assert_eq!(screen["state2"], "WAITING");
        assert_eq!(screen["alert"], "1/10 OK");
        ui.press("next");
        let screen = ui.render(&state);
        assert_eq!(screen["name1"], "s09");
        assert_eq!(screen["name2"], "");
        ui.press("next");
        assert_eq!(ui.render(&state)["pageno"], "1/2");
    }

    #[test]
    fn scan_pick_type_and_join() {
        let mut ui = Ui::new(sensors(1));
        assert_eq!(ui.press("scan"), Some(Request::Scan));
        assert_eq!(ui.press("scan"), None, "no double scan while busy");
        ui.wifi_result(Response::Scanned(Ok(vec![network("Plant WiFi", true)])));
        ui.press("pick0");
        type_text(&mut ui, "Pa5s w!");
        assert_eq!(ui.press("join"), None);
        assert_eq!(ui.message, "MIN 8 CHARS");
        type_text(&mut ui, "~");
        let state = State::default();
        assert_eq!(ui.render(&state)["pass0"], "********");
        ui.press("show");
        assert_eq!(ui.render(&state)["pass0"], "Pa5s w!~");
        assert_eq!(
            ui.press("join"),
            Some(Request::Connect {
                ssid: "Plant WiFi".into(),
                password: Some(Secret("Pa5s w!~".into()))
            })
        );
        ui.wifi_result(Response::Connected(Ok(())));
        assert!(ui.password.is_empty());
    }

    #[test]
    fn open_network_joins_without_password_and_failures_are_shown() {
        let mut ui = Ui::new(sensors(1));
        ui.wifi_result(Response::Scanned(Ok(vec![network("Guest", false)])));
        ui.press("pick0");
        assert_eq!(
            ui.press("join"),
            Some(Request::Connect {
                ssid: "Guest".into(),
                password: None
            })
        );
        ui.wifi_result(Response::Connected(Err("bad".into())));
        assert_eq!(ui.render(&State::default())["kmsg"], "JOIN FAILED");
    }

    #[test]
    fn every_rendered_name_is_a_layout_field_and_vice_versa() {
        use super::super::layout::{Kind, Layout};
        let rendered = Ui::new(sensors(3)).render(&State::default());
        let layout = Layout::new();
        let fields: std::collections::HashSet<_> = layout
            .widgets
            .iter()
            .filter(|w| matches!(w.kind, Kind::Field { .. }))
            .map(|w| w.name.clone())
            .collect();
        assert_eq!(fields, rendered.keys().cloned().collect());
    }
}
