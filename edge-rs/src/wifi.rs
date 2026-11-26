//! Wi-Fi control through NetworkManager's `nmcli`.

use std::process::Command;
use std::sync::mpsc::{channel, Receiver, RecvTimeoutError, Sender};
use std::time::Duration;

/// A password that never appears in debug output or logs.
#[derive(Clone, PartialEq, Eq)]
pub struct Secret(pub String);

impl std::fmt::Debug for Secret {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Secret(***)")
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Network {
    pub ssid: String,
    pub signal: u8,
    pub secured: bool,
    pub active: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Request {
    Scan,
    Connect {
        ssid: String,
        password: Option<Secret>,
    },
}

#[derive(Debug)]
pub enum Response {
    Scanned(Result<Vec<Network>, String>),
    Connected(Result<(), String>),
    Status { ssid: String, ip: String },
}

pub trait Backend: Send {
    fn scan(&mut self) -> Result<Vec<Network>, String>;
    fn connect(&mut self, ssid: &str, password: Option<&Secret>) -> Result<(), String>;
    /// (active network name, IPv4 address); empty strings when offline.
    fn status(&mut self) -> (String, String);
}

/// Runs the backend on its own thread so a 30 s join never freezes the screen.
pub fn spawn_worker(mut backend: Box<dyn Backend>) -> (Sender<Request>, Receiver<Response>) {
    let (request_tx, request_rx) = channel::<Request>();
    let (response_tx, response_rx) = channel();
    std::thread::spawn(move || loop {
        let (ssid, ip) = backend.status();
        if response_tx.send(Response::Status { ssid, ip }).is_err() {
            return;
        }
        let response = match request_rx.recv_timeout(Duration::from_secs(5)) {
            Ok(Request::Scan) => Response::Scanned(backend.scan()),
            Ok(Request::Connect { ssid, password }) => {
                Response::Connected(backend.connect(&ssid, password.as_ref()))
            }
            Err(RecvTimeoutError::Timeout) => continue,
            Err(RecvTimeoutError::Disconnected) => return,
        };
        if response_tx.send(response).is_err() {
            return;
        }
    });
    (request_tx, response_rx)
}

/// Splits one line of `nmcli -t` output, where ':' and '\' are backslash-escaped.
fn split_terse(line: &str) -> Vec<String> {
    let mut fields = vec![String::new()];
    let mut chars = line.chars();
    while let Some(c) = chars.next() {
        match c {
            ':' => fields.push(String::new()),
            '\\' => fields
                .last_mut()
                .into_iter()
                .for_each(|f| f.extend(chars.next())),
            other => fields.last_mut().into_iter().for_each(|f| f.push(other)),
        }
    }
    fields
}

/// Parses `IN-USE,SIGNAL,SECURITY,SSID` lines: strongest entry per name,
/// active network first, hidden networks dropped.
pub fn parse_scan(output: &str) -> Vec<Network> {
    let mut networks: Vec<Network> = Vec::new();
    for line in output.lines() {
        let fields = split_terse(line);
        let [in_use, signal, security, ssid] = fields.as_slice() else {
            continue;
        };
        if ssid.is_empty() {
            continue;
        }
        let network = Network {
            ssid: ssid.clone(),
            signal: signal.parse().unwrap_or(0),
            secured: !security.is_empty() && security != "--",
            active: in_use == "*",
        };
        match networks.iter_mut().find(|n| n.ssid == network.ssid) {
            Some(existing) => {
                existing.active |= network.active;
                existing.signal = existing.signal.max(network.signal);
            }
            None => networks.push(network),
        }
    }
    networks.sort_by_key(|n| std::cmp::Reverse((n.active, n.signal)));
    networks
}

pub struct NetworkManager;

/// Arguments are passed directly to the process, never through a shell.
fn nmcli(args: &[&str]) -> Result<String, String> {
    let output = Command::new("nmcli")
        .env("LC_ALL", "C.UTF-8")
        .args(args)
        .output()
        .map_err(|e| format!("could not run nmcli: {e}"))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).into_owned())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_string())
    }
}

fn active_wifi_profile() -> Option<String> {
    let listing = nmcli(&["-t", "-f", "TYPE,NAME", "connection", "show", "--active"]).ok()?;
    listing
        .lines()
        .map(split_terse)
        .find_map(|f| match f.as_slice() {
            [kind, name] if kind == "802-11-wireless" => Some(name.clone()),
            _ => None,
        })
}

fn profile_exists(name: &str) -> bool {
    nmcli(&["-t", "-f", "NAME", "connection", "show"])
        .is_ok_and(|l| l.lines().map(split_terse).any(|f| f[0] == name))
}

impl Backend for NetworkManager {
    fn scan(&mut self) -> Result<Vec<Network>, String> {
        let output = nmcli(&[
            "-t",
            "-f",
            "IN-USE,SIGNAL,SECURITY,SSID",
            "device",
            "wifi",
            "list",
            "--rescan",
            "yes",
        ])?;
        Ok(parse_scan(&output))
    }

    /// Joins a network. On failure the previous connection is restored and any
    /// half-made profile removed, so a typo cannot strand the unit.
    fn connect(&mut self, ssid: &str, password: Option<&Secret>) -> Result<(), String> {
        if ssid.starts_with('-') {
            return Err("network names starting with '-' are not supported".into());
        }
        let previous = active_wifi_profile();
        let existed = profile_exists(ssid);
        let mut args = vec!["--wait", "30", "device", "wifi", "connect", ssid];
        if let Some(secret) = password {
            args.extend(["password", secret.0.as_str()]);
        }
        let result = nmcli(&args).map(|_| ());
        if result.is_err() {
            if !existed && profile_exists(ssid) {
                let _ = nmcli(&["connection", "delete", "id", ssid]);
            }
            if let Some(previous) = previous {
                let _ = nmcli(&["--wait", "30", "connection", "up", "id", &previous]);
            }
        }
        result
    }

    fn status(&mut self) -> (String, String) {
        let ssid = active_wifi_profile().unwrap_or_default();
        let ip = nmcli(&["-t", "-f", "IP4.ADDRESS", "device", "show", "wlan0"])
            .ok()
            .and_then(|out| {
                let line = out.lines().next()?.to_string();
                let address = split_terse(&line).get(1)?.split('/').next()?.to_string();
                Some(address)
            })
            .unwrap_or_default();
        (ssid, ip)
    }
}

/// Stand-in used by `--mock` and tests. Accepts the password "airthra123".
#[derive(Default)]
pub struct MockWifi {
    pub current: String,
}

impl Backend for MockWifi {
    fn scan(&mut self) -> Result<Vec<Network>, String> {
        Ok(parse_scan(
            " :82:WPA2:Plant-Floor\n :61:WPA2:Office\\:2G\n :40::Guest\n",
        ))
    }

    fn connect(&mut self, ssid: &str, password: Option<&Secret>) -> Result<(), String> {
        if password.is_some_and(|p| p.0 != "airthra123") {
            return Err("wrong password".into());
        }
        self.current = ssid.to_string();
        Ok(())
    }

    fn status(&mut self) -> (String, String) {
        let ip = if self.current.is_empty() {
            ""
        } else {
            "192.168.100.200"
        };
        (self.current.clone(), ip.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_escapes_merges_and_sorts() {
        let got = parse_scan(
            " :40:WPA2:Home\n :90:WPA2:Cafe\\:5G\\\\x\n*:55:WPA2:Home\n :80::Open Net\n :70:WPA2:\nbroken\n",
        );
        let names: Vec<_> = got.iter().map(|n| n.ssid.as_str()).collect();
        assert_eq!(names, ["Home", "Cafe:5G\\x", "Open Net"]);
        assert_eq!(got[0].signal, 55);
        assert!(got[0].active && got[0].secured);
        assert!(!got[2].secured);
    }

    #[test]
    fn passwords_never_reach_debug_output() {
        let request = Request::Connect {
            ssid: "a".into(),
            password: Some(Secret("hunter22".into())),
        };
        assert!(!format!("{request:?}").contains("hunter22"));
    }
}
