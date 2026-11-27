//! Touchscreen driver: reads touches, writes text fields.

pub mod layout;
pub mod project;
pub mod protocol;
pub mod ui;

use crate::model::{lock, SensorSpec, Shared};
use crate::wifi::{self, Backend};
use layout::{Kind, Layout};
use protocol::{encode_text, Parser};
use std::collections::HashMap;
use std::io::{ErrorKind, Read, Write};
use std::sync::mpsc::TryRecvError;
use std::time::{Duration, Instant};
use ui::Ui;

#[derive(Clone, Debug)]
pub struct Settings {
    pub port: String,
    pub baud: u32,
    /// Pause between frames so the screen can keep up.
    pub frame_gap: Duration,
    /// Bytes appended to each frame. The manual specifies none.
    pub terminator: Vec<u8>,
}

/// Ignore a repeat of the same touch within this window (press + release, or
/// resistive-panel bounce).
const DEBOUNCE: Duration = Duration::from_millis(250);
/// Silence after which a partly received frame is treated as finished.
const IDLE: Duration = Duration::from_millis(50);

/// The screen session over any byte stream. Reads must time out quickly.
pub struct Screen<P: Read + Write> {
    port: P,
    layout: Layout,
    pub ui: Ui,
    parser: Parser,
    sent: HashMap<String, String>,
    cursor: usize,
    frames: usize,
    last_byte: Instant,
    visible: u16,
    last_touch: Option<(u16, u16, u16, Instant)>,
    terminator: Vec<u8>,
}

impl<P: Read + Write> Screen<P> {
    pub fn new(port: P, ui: Ui, terminator: Vec<u8>) -> Self {
        Screen {
            port,
            layout: Layout::new(),
            ui,
            parser: Parser::default(),
            sent: HashMap::new(),
            cursor: 0,
            frames: 0,
            last_byte: Instant::now(),
            visible: layout::PAGE_LIVE,
            last_touch: None,
            terminator,
        }
    }

    /// Reads any pending touches and returns the Wi-Fi requests they caused.
    pub fn poll_touches(&mut self) -> std::io::Result<Vec<wifi::Request>> {
        let mut chunk = [0u8; 128];
        let received = match self.port.read(&mut chunk) {
            Ok(n) => n,
            Err(e) if matches!(e.kind(), ErrorKind::TimedOut | ErrorKind::WouldBlock) => 0,
            Err(e) => return Err(e),
        };
        let events = if received > 0 {
            self.last_byte = Instant::now();
            self.parser.push(&chunk[..received])
        } else if self.last_byte.elapsed() >= IDLE {
            self.parser.flush()
        } else {
            Vec::new()
        };
        let mut requests = Vec::new();
        for event in events {
            if event.value == 0 {
                continue;
            }
            let Some(widget) = self.layout.touched(event.page, event.kind, event.id) else {
                eprintln!("hmi: ignoring touch from unknown widget {event:?}");
                continue;
            };
            let key = (event.page, event.kind, event.id);
            let now = Instant::now();
            let repeat = self
                .last_touch
                .is_some_and(|(p, t, i, at)| (p, t, i) == key && now.duration_since(at) < DEBOUNCE);
            self.last_touch = Some((key.0, key.1, key.2, now));
            // Any touch tells us which page the user is looking at.
            self.visible = match widget.kind {
                Kind::Nav { to, .. } => to,
                _ => widget.page,
            };
            if !repeat {
                let name = widget.name.clone();
                requests.extend(self.ui.press(&name));
            }
        }
        Ok(requests)
    }

    /// Writes one frame: a changed field if there is one (visible page first),
    /// otherwise the next field in a continuous refresh. The screen does not
    /// tell us when it changes page or restarts, so the refresh never stops.
    pub fn send_next(&mut self, values: &HashMap<String, String>) -> std::io::Result<()> {
        let fields: Vec<_> = self
            .layout
            .widgets
            .iter()
            .filter_map(|w| match w.kind {
                Kind::Field { maxl } => Some((w, maxl)),
                _ => None,
            })
            .collect();
        let changed = |name: &str| self.sent.get(name) != values.get(name);
        // Every third frame is always a refresh, so constantly changing
        // readings cannot starve the other pages.
        self.frames = self.frames.wrapping_add(1);
        let urgent = fields
            .iter()
            .find(|(w, _)| w.page == self.visible && changed(&w.name))
            .filter(|_| !self.frames.is_multiple_of(3));
        let (widget, maxl) = match urgent {
            Some(&found) => found,
            None => {
                // Refresh two frames of the visible page for each other one.
                let mut order: Vec<_> = fields
                    .iter()
                    .filter(|(w, _)| w.page == self.visible)
                    .collect();
                let on_page = order.clone();
                order.extend(on_page);
                order.extend(fields.iter().filter(|(w, _)| w.page != self.visible));
                let &found = order[self.cursor % order.len()];
                self.cursor = self.cursor.wrapping_add(1);
                found
            }
        };
        let text = values.get(&widget.name).cloned().unwrap_or_default();
        let mut frame = encode_text(widget.page, widget.id, &text, maxl);
        frame.extend_from_slice(&self.terminator);
        let name = widget.name.clone();
        self.port.write_all(&frame)?;
        self.sent.insert(name, text);
        Ok(())
    }
}

/// Wi-Fi outcomes worth showing on the status page. Never includes a password.
fn wifi_event(response: &wifi::Response) -> Option<&'static str> {
    match response {
        wifi::Response::Connected(Ok(())) => Some("wifi joined"),
        wifi::Response::Connected(Err(_)) => Some("wifi join failed"),
        wifi::Response::Scanned(Err(_)) => Some("wifi scan failed"),
        _ => None,
    }
}

/// Runs the screen forever, reopening the port after any error.
pub fn run(
    settings: Settings,
    sensors: Vec<SensorSpec>,
    shared: Shared,
    backend: Box<dyn Backend>,
) {
    let (requests, responses) = wifi::spawn_worker(backend);
    loop {
        let port = serialport::new(&settings.port, settings.baud)
            .timeout(Duration::from_millis(5))
            .open();
        let port = match port {
            Ok(port) => port,
            Err(e) => {
                eprintln!("hmi: cannot open {}: {e}; retrying", settings.port);
                std::thread::sleep(Duration::from_secs(3));
                continue;
            }
        };
        eprintln!(
            "hmi: driving screen on {} at {} baud",
            settings.port, settings.baud
        );
        let mut screen = Screen::new(port, Ui::new(sensors.clone()), settings.terminator.clone());
        let error = loop {
            match screen.poll_touches() {
                Ok(new) => new.into_iter().for_each(|r| {
                    let _ = requests.send(r);
                }),
                Err(e) => break e,
            }
            loop {
                match responses.try_recv() {
                    Ok(response) => {
                        if let Some(event) = wifi_event(&response) {
                            lock(&shared).note(event);
                        }
                        screen.ui.wifi_result(response);
                    }
                    Err(TryRecvError::Empty) => break,
                    Err(TryRecvError::Disconnected) => {
                        eprintln!("hmi: Wi-Fi worker stopped");
                        break;
                    }
                }
            }
            let values = screen.ui.render(&lock(&shared));
            if let Err(e) = screen.send_next(&values) {
                break e;
            }
            std::thread::sleep(settings.frame_gap);
        };
        eprintln!("hmi: serial error: {error}; reopening");
        std::thread::sleep(Duration::from_secs(1));
    }
}
