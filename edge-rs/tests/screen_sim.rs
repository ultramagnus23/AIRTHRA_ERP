//! End to end against a simulated screen that speaks the manual's protocol.

use airthra_edge::hmi::layout::{Kind, Layout};
use airthra_edge::hmi::ui::Ui;
use airthra_edge::hmi::Screen;
use airthra_edge::model::{classify, SensorSpec, State};
use airthra_edge::wifi::{spawn_worker, MockWifi, Request, Response};
use std::cell::RefCell;
use std::collections::HashMap;
use std::io::{ErrorKind, Read, Write};
use std::rc::Rc;
use std::sync::mpsc::{Receiver, Sender};
use std::time::{Duration, Instant};

#[derive(Default)]
struct Wire {
    to_pi: Vec<u8>,
    /// (page, id) -> the 12 value bytes last received.
    fields: HashMap<(u16, u16), String>,
}

#[derive(Clone, Default)]
struct Port(Rc<RefCell<Wire>>);

impl Read for Port {
    fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
        let mut wire = self.0.borrow_mut();
        if wire.to_pi.is_empty() {
            return Err(ErrorKind::TimedOut.into());
        }
        let n = wire.to_pi.len().min(out.len()).min(7); // arrive in pieces
        out[..n].copy_from_slice(&wire.to_pi[..n]);
        wire.to_pi.drain(..n);
        Ok(n)
    }
}

impl Write for Port {
    fn write(&mut self, frame: &[u8]) -> std::io::Result<usize> {
        let text = std::str::from_utf8(frame).expect("ASCII frame");
        assert_eq!(text.len(), 25, "frame {text:?}");
        assert_eq!(&text[4..8], "T001");
        let page = text[1..4].parse().expect("page");
        let id = text[9..12].parse().expect("id");
        self.0
            .borrow_mut()
            .fields
            .insert((page, id), text[13..].to_string());
        Ok(frame.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

struct Sim {
    screen: Screen<Port>,
    port: Port,
    layout: Layout,
    state: State,
    requests: Sender<Request>,
    responses: Receiver<Response>,
}

impl Sim {
    fn step(&mut self) {
        for request in self.screen.poll_touches().unwrap() {
            self.requests.send(request).unwrap();
        }
        while let Ok(response) = self.responses.try_recv() {
            self.screen.ui.wifi_result(response);
        }
        let values = self.screen.ui.render(&self.state);
        self.screen.send_next(&values).unwrap();
    }

    /// The text the screen would be displaying in a field.
    fn shown(&self, name: &str) -> String {
        let widget = self.layout.get(name).unwrap();
        let Kind::Field { maxl } = widget.kind else {
            panic!("{name} is not a field")
        };
        let wire = self.port.0.borrow();
        wire.fields
            .get(&(widget.page, widget.id))
            .map(|v| v[..maxl].trim_end().to_string())
            .unwrap_or_default()
    }

    fn wait_for(&mut self, name: &str, want: &str) {
        let deadline = Instant::now() + Duration::from_secs(5);
        while self.shown(name) != want {
            assert!(
                Instant::now() < deadline,
                "{name} shows {:?}, wanted {want:?}",
                self.shown(name)
            );
            self.step();
            std::thread::sleep(Duration::from_millis(1));
        }
    }

    fn touch(&mut self, name: &str) {
        let w = self.layout.get(name).unwrap();
        let frame = format!(
            "P{:03}T{:03}I{:03}V001000000000",
            w.page,
            w.type_code(),
            w.id
        );
        self.port.0.borrow_mut().to_pi.extend(frame.bytes());
        for _ in 0..8 {
            self.step();
        }
        std::thread::sleep(Duration::from_millis(260)); // past the debounce
    }
}

#[test]
fn live_values_then_wifi_change_entirely_from_the_screen() {
    let sensors: Vec<SensorSpec> = serde_json::from_str(include_str!("../sensors.json")).unwrap();
    let mut state = State {
        clock_ok: true,
        ..State::default()
    };
    let first = &sensors[0];
    state
        .latest
        .insert(first.sensor_id.clone(), classify(first, Ok(1234.5)));
    let port = Port::default();
    let (requests, responses) = spawn_worker(Box::new(MockWifi::default()));
    let mut sim = Sim {
        screen: Screen::new(port.clone(), Ui::new(sensors), Vec::new()),
        port,
        layout: Layout::new(),
        state,
        requests,
        responses,
    };

    sim.wait_for("name0", "SO2_in");
    sim.wait_for("value0", "1234.5");
    sim.wait_for("state0", "ppm");
    sim.wait_for("pageno", "1/4");
    sim.touch("next");
    sim.wait_for("pageno", "2/4");

    sim.touch("to_wifi");
    sim.touch("scan");
    sim.wait_for("ssid0", "Plant-Floor");
    sim.wait_for("sig0", " 82% LOCK");
    sim.touch("pick0");
    sim.wait_for("target0", "Plant-Floor");
    // Type "airthra123": layer 0 holds a-t, layer 1 holds u-z and digits.
    for slot in ["tap0", "tap8", "tap17", "tap19", "tap7", "tap17", "tap0"] {
        sim.touch(slot);
    }
    sim.touch("layer");
    for slot in ["tap7", "tap8", "tap9"] {
        sim.touch(slot);
    }
    sim.wait_for("count", "10 ch");
    sim.wait_for("pass0", "**********");
    sim.touch("show");
    sim.wait_for("pass0", "airthra123");
    sim.touch("join");
    sim.wait_for("kmsg", "CONNECTED");
    sim.wait_for("current", "Plant-Floor");
    sim.wait_for("ip_a", "192.168.100.");
    sim.wait_for("ip_b", "200");
}
