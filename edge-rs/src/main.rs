use airthra_edge::config::{self, Config};
use airthra_edge::hmi::{self, layout::Layout, protocol::Parser, ui::Ui};
use airthra_edge::model::{
    classify, lock, rfc3339, Latest, Quality, Reading, SensorSpec, Shared, State,
};
use airthra_edge::sensors::{self, Poller};
use airthra_edge::store::Store;
use airthra_edge::{uplink, wifi};
use anyhow::{bail, Context, Result};
use std::collections::{HashMap, VecDeque};
use std::io::{Read, Write};
use std::path::Path;
use std::sync::mpsc::{channel, RecvTimeoutError, Sender};
use std::time::{Duration, Instant};
use time::OffsetDateTime;

const USAGE: &str = "usage: airthra-edge <command>
  run [--mock]       poll sensors, drive the screen, publish to the cloud
  check [--mock]     read every sensor once and print why any of them fail
  hmi-probe          test the screen link: send a value, print what comes back
  hmi-layout [DIR]   write the screen build sheet and preview image";

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mock = args.iter().any(|a| a == "--mock");
    match args.first().map(String::as_str) {
        Some("run") => run(Config::load(mock)?),
        Some("check") => check(&Config::load(mock)?),
        Some("hmi-probe") => probe(),
        Some("hmi-layout") => {
            let dir = args.get(1).map_or("edge-rs/hmi", String::as_str);
            write_layout(Path::new(dir), &Config::load(true)?)
        }
        _ => {
            eprintln!("{USAGE}");
            std::process::exit(2)
        }
    }
}

fn load_sensors(path: &Path) -> Result<Vec<SensorSpec>> {
    let text = std::fs::read_to_string(path)
        .with_context(|| format!("reading the sensor list {}", path.display()))?;
    let sensors: Vec<SensorSpec> =
        serde_json::from_str(&text).with_context(|| format!("parsing {}", path.display()))?;
    if sensors.is_empty() {
        bail!("{} lists no sensors", path.display());
    }
    Ok(sensors)
}

fn pollers(config: &Config, sensors: &[SensorSpec]) -> Result<Vec<Box<dyn Poller>>> {
    if config.mock {
        Ok(vec![Box::new(sensors::Mock::new(sensors.to_vec()))])
    } else {
        sensors::build(sensors, &config.maps_dir)
    }
}

/// Reads one poller forever. A DS18B20-style probe that repeats the exact same
/// value five times running is flagged as stuck.
fn poll_loop(
    mut poller: Box<dyn Poller>,
    specs: HashMap<String, SensorSpec>,
    interval: Duration,
    results: Sender<(String, Latest)>,
    shared: Shared,
) {
    let mut history: HashMap<String, VecDeque<u64>> = HashMap::new();
    let mut faults: HashMap<String, &'static str> = HashMap::new();
    loop {
        let started = Instant::now();
        for id in poller.sensor_ids() {
            let Some(spec) = specs.get(&id) else { continue };
            let mut latest = classify(spec, poller.read(&id));
            if let (Some(value), Some("onewire")) = (latest.value, spec.interface.as_deref()) {
                let seen = history.entry(id.clone()).or_default();
                seen.push_back(value.to_bits());
                if seen.len() > 5 {
                    seen.pop_front();
                }
                let stuck = seen.len() == 5 && seen.iter().all(|&v| v == value.to_bits());
                if stuck && latest.quality == Quality::Good {
                    latest.quality = Quality::Frozen;
                }
            }
            // Log a fault when it appears or changes, not on every cycle.
            match &latest.fault {
                Some(f) if faults.insert(id.clone(), f.short) != Some(f.short) => {
                    eprintln!("{}: {id}: {} ({})", poller.name(), f.short, f.detail);
                    lock(&shared).note(format!("{id} {}", f.short));
                }
                None if faults.remove(&id).is_some() => {
                    eprintln!("{}: {id}: recovered", poller.name());
                    lock(&shared).note(format!("{id} recovered"));
                }
                _ => {}
            }
            if results.send((id, latest)).is_err() {
                return;
            }
        }
        std::thread::sleep(interval.saturating_sub(started.elapsed()));
    }
}

/// Earliest time the clock can legitimately show (2026-08-01 UTC). A Pi with
/// no clock battery can boot far in the past.
const BUILD_EPOCH: i64 = 1_785_542_400;

/// True if `now` is plausible given the newest time already recorded.
fn clock_trusted(now: i64, watermark: i64) -> bool {
    now >= BUILD_EPOCH && now >= watermark - 120
}

fn run(config: Config) -> Result<()> {
    let sensors = load_sensors(&config.sensors_file)?;
    let specs: HashMap<_, _> = sensors
        .iter()
        .map(|s| (s.sensor_id.clone(), s.clone()))
        .collect();
    let shared: Shared = std::sync::Arc::new(std::sync::Mutex::new(State::default()));
    let database = config.data_dir.join(format!("{}.db", config.plant_id));
    let mut store = Store::open(&database)?;
    let watermark_path = config.data_dir.join(format!("{}.clock", config.plant_id));
    let mut watermark: i64 = std::fs::read_to_string(&watermark_path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);
    {
        let mut state = lock(&shared);
        state.clock_ok = clock_trusted(OffsetDateTime::now_utc().unix_timestamp(), watermark);
        state.cloud_enabled = config.mqtt.is_some();
        state.started = Some(Instant::now());
        state.note(format!("started, {} sensors", sensors.len()));
        if !state.clock_ok {
            state.note("clock bad: not recording");
        }
        if !state.cloud_enabled {
            state.note("MQTT_HOST unset: no cloud");
        }
    }
    eprintln!(
        "airthra-edge: plant {} with {} sensors, {} data",
        config.plant_id,
        sensors.len(),
        if config.mock { "SIMULATED" } else { "hardware" }
    );

    if let Some(settings) = config.hmi.clone() {
        let backend: Box<dyn wifi::Backend> = if config.mock {
            Box::new(wifi::MockWifi::default())
        } else {
            Box::new(wifi::NetworkManager)
        };
        let (sensors, shared) = (sensors.clone(), shared.clone());
        std::thread::spawn(move || hmi::run(settings, sensors, shared, backend));
    } else {
        eprintln!("hmi: off (set HMI_ENABLED=true)");
    }

    match config.mqtt.clone() {
        Some(mqtt) => {
            let (plant, database, shared) =
                (config.plant_id.clone(), database.clone(), shared.clone());
            std::thread::spawn(move || {
                // The screen and local log keep working if this fails.
                if let Err(e) = uplink::run(mqtt, plant, database, shared) {
                    eprintln!("mqtt: publishing stopped: {e:#}");
                    std::process::exit(1); // systemd restarts us
                }
            });
        }
        None => eprintln!("mqtt: off (set MQTT_HOST)"),
    }

    let (results_tx, results) = channel();
    for poller in pollers(&config, &sensors)? {
        let (specs, tx, interval) = (specs.clone(), results_tx.clone(), config.poll_interval);
        let shared = shared.clone();
        std::thread::spawn(move || poll_loop(poller, specs, interval, tx, shared));
    }
    drop(results_tx);

    let source = if config.mock { "mock" } else { "hardware" };
    let mut batch = Vec::new();
    let mut last_flush = Instant::now();
    let mut last_prune: Option<Instant> = None;
    loop {
        match results.recv_timeout(Duration::from_millis(200)) {
            Ok((sensor_id, latest)) => {
                let now = OffsetDateTime::now_utc();
                let trusted = clock_trusted(now.unix_timestamp(), watermark);
                let mut state = lock(&shared);
                if state.clock_ok != trusted {
                    state.note(if trusted {
                        "clock ok: recording"
                    } else {
                        "clock bad: not recording"
                    });
                }
                state.clock_ok = trusted;
                if trusted {
                    watermark = watermark.max(now.unix_timestamp());
                    batch.push(Reading {
                        plant_id: config.plant_id.clone(),
                        sensor_id: sensor_id.clone(),
                        ts: rfc3339(now),
                        value: latest.value,
                        quality_flag: latest.quality as u8,
                        source: source.into(),
                    });
                }
                state.latest.insert(sensor_id, latest);
            }
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => bail!("all sensor threads stopped"),
        }
        if last_flush.elapsed() >= Duration::from_secs(1) && !batch.is_empty() {
            store.insert(&batch)?;
            lock(&shared).recorded += batch.len() as u64;
            batch.clear();
            std::fs::write(&watermark_path, watermark.to_string())?;
            if last_prune.is_none_or(|t| t.elapsed() >= Duration::from_secs(3600)) {
                store.prune(OffsetDateTime::now_utc(), config.retention_days)?;
                last_prune = Some(Instant::now());
            }
            last_flush = Instant::now();
        }
    }
}

fn check(config: &Config) -> Result<()> {
    let sensors = load_sensors(&config.sensors_file)?;
    let specs: HashMap<_, _> = sensors.iter().map(|s| (s.sensor_id.as_str(), s)).collect();
    let mut good = 0;
    for mut poller in pollers(config, &sensors)? {
        println!("[{}]", poller.name());
        for id in poller.sensor_ids() {
            let Some(spec) = specs.get(id.as_str()) else {
                continue;
            };
            let latest = classify(spec, poller.read(&id));
            match (latest.value, latest.fault) {
                (Some(v), _) => {
                    good += 1;
                    println!("  {id:<18} {v:>12.3} {:<6} {:?}", spec.unit, latest.quality);
                }
                (None, fault) => {
                    let f = fault
                        .map(|f| format!("{:<9} {}", f.short, f.detail))
                        .unwrap_or_default();
                    println!("  {id:<18} {f}");
                }
            }
        }
    }
    println!("{good} of {} sensors returned a value", sensors.len());
    Ok(())
}

/// Commissioning tool for the parts of the protocol the manual leaves open.
fn probe() -> Result<()> {
    let settings = config::hmi_settings()?;
    let mut port = serialport::new(&settings.port, settings.baud)
        .timeout(Duration::from_millis(100))
        .open()
        .with_context(|| format!("opening {}", settings.port))?;
    let layout = Layout::new();
    let mut parser = Parser::default();
    println!(
        "Probing {} at {} baud. RealTimeText id 000 on page 0 should count up.\n\
         Touch buttons on the screen; raw bytes and their meaning print below. Ctrl-C stops.",
        settings.port, settings.baud
    );
    // The first field on page 0, so a one-widget test project is enough.
    let field = layout.get("cloud").context("layout has no cloud field")?;
    let mut count = 0u32;
    let mut last_send = Instant::now() - Duration::from_secs(2);
    loop {
        if last_send.elapsed() >= Duration::from_secs(1) {
            count += 1;
            let mut frame =
                hmi::protocol::encode_text(field.page, field.id, &format!("TEST {count}"), 12);
            frame.extend_from_slice(&settings.terminator);
            port.write_all(&frame)?;
            println!("sent  {}", String::from_utf8_lossy(&frame).escape_debug());
            last_send = Instant::now();
        }
        let mut chunk = [0u8; 128];
        let events = match port.read(&mut chunk) {
            Ok(n) => {
                println!(
                    "got   {}",
                    String::from_utf8_lossy(&chunk[..n]).escape_debug()
                );
                parser.push(&chunk[..n])
            }
            Err(e) if e.kind() == std::io::ErrorKind::TimedOut => parser.flush(),
            Err(e) => return Err(e.into()),
        };
        for event in events {
            let name = layout
                .touched(event.page, event.kind, event.id)
                .map_or("(not in layout)", |w| w.name.as_str());
            println!("      => {event:?} {name}");
        }
    }
}

fn write_layout(dir: &Path, config: &Config) -> Result<()> {
    let sensors = load_sensors(&config.sensors_file)?;
    // Sample figures for the preview image only.
    let mut state = State {
        clock_ok: true,
        cloud_enabled: true,
        cloud_connected: true,
        recorded: 1240,
        published: 1209,
        unsent: 31,
        last_publish: Some(Instant::now()),
        started: Some(Instant::now()),
        ..State::default()
    };
    state.note(format!("started, {} sensors", sensors.len()));
    state.note("cloud connected");
    state.note("PT_05 NO REPLY");
    let mut mock = sensors::Mock::new(sensors.clone());
    for spec in &sensors {
        let mut latest = classify(spec, mock.read(&spec.sensor_id));
        if spec.sensor_id == "PT_05" {
            latest = classify(
                spec,
                Err(airthra_edge::model::Fault::new("NO REPLY", "sample")),
            );
        }
        state.latest.insert(spec.sensor_id.clone(), latest);
    }
    let mut ui = Ui::new(sensors);
    let mut sample = wifi::MockWifi {
        current: "Plant-Floor".into(),
    };
    ui.wifi_result(wifi::Response::Status {
        ssid: "Plant-Floor".into(),
        ip: "192.168.100.200".into(),
    });
    ui.wifi_result(wifi::Response::Scanned(wifi::Backend::scan(&mut sample)));
    for touch in ["pick1", "tap0", "tap8", "tap17"] {
        ui.press(touch);
    }
    let layout = Layout::new();
    std::fs::create_dir_all(dir)?;
    std::fs::write(dir.join("BUILD_SHEET.md"), layout.build_sheet())?;
    std::fs::write(
        dir.join("preview.svg"),
        layout.preview_svg(&ui.render(&state)),
    )?;
    println!(
        "wrote {} and preview.svg",
        dir.join("BUILD_SHEET.md").display()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clock_gate_rejects_old_and_backwards_clocks() {
        assert!(!clock_trusted(0, 0));
        assert!(clock_trusted(BUILD_EPOCH + 10, 0));
        assert!(!clock_trusted(BUILD_EPOCH + 10, BUILD_EPOCH + 1000));
        assert!(clock_trusted(BUILD_EPOCH + 950, BUILD_EPOCH + 1000));
    }
}
