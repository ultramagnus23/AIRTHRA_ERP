//! MQTT publishing. A row is marked delivered only after the broker's QoS 1
//! acknowledgement for the message that carried it.

use crate::config::Mqtt;
use crate::model::{lock, rfc3339, Reading, Shared};
use crate::store::Store;
use anyhow::{Context, Result};
use rumqttc::{Client, Event, MqttOptions, Outgoing, Packet, QoS, TlsConfiguration, Transport};
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver};
use std::time::{Duration, Instant};
use time::OffsetDateTime;

const CHUNK: usize = 500;
const ACK_TIMEOUT: Duration = Duration::from_secs(30);

/// Topic and body for a chunk: fresh readings go to `readings`, older ones to
/// `backfill` in the envelope `ingest/service.py` expects.
pub fn message(
    plant: &str,
    rows: &[(i64, String)],
    now: OffsetDateTime,
) -> Result<(String, String)> {
    let cutoff = rfc3339(now - time::Duration::seconds(15));
    let readings: Vec<Reading> = rows
        .iter()
        .map(|(_, json)| serde_json::from_str(json))
        .collect::<std::result::Result<_, _>>()
        .context("corrupt row in the local queue")?;
    if readings.iter().all(|r| r.ts >= cutoff) {
        Ok((
            format!("plants/{plant}/readings"),
            serde_json::to_string(&readings)?,
        ))
    } else {
        let envelope: Vec<_> = readings
            .iter()
            .map(|r| serde_json::json!({ "kind": "reading", "data": r }))
            .collect();
        Ok((
            format!("plants/{plant}/backfill"),
            serde_json::to_string(&envelope)?,
        ))
    }
}

enum Link {
    Up,
    Down,
    Sent(u16),
    Acked(u16),
}

pub fn run(config: Mqtt, plant: String, database: PathBuf, shared: Shared) -> Result<()> {
    let mut options = MqttOptions::new(format!("edge-{plant}"), &config.host, config.port);
    options.set_keep_alive(Duration::from_secs(30));
    options.set_max_packet_size(1024 * 1024, 1024 * 1024);
    if !config.username.is_empty() {
        options.set_credentials(&config.username, &config.password);
    }
    if let Some(ca_path) = &config.ca_cert {
        let ca = std::fs::read(ca_path)
            .with_context(|| format!("reading CA certificate {}", ca_path.display()))?;
        options.set_transport(Transport::Tls(TlsConfiguration::Simple {
            ca,
            alpn: None,
            client_auth: None,
        }));
    }
    let (client, mut connection) = Client::new(options, 16);
    let (events, link) = channel();
    let status = shared.clone();
    std::thread::spawn(move || {
        for event in connection.iter() {
            let update = match event {
                Ok(Event::Incoming(Packet::ConnAck(_))) => Some(Link::Up),
                Ok(Event::Incoming(Packet::PubAck(ack))) => Some(Link::Acked(ack.pkid)),
                Ok(Event::Outgoing(Outgoing::Publish(id))) => Some(Link::Sent(id)),
                Ok(_) => None,
                Err(e) => {
                    if lock(&status).cloud_connected {
                        eprintln!("mqtt: connection lost: {e}");
                    }
                    lock(&status).cloud_connected = false;
                    std::thread::sleep(Duration::from_secs(2));
                    Some(Link::Down)
                }
            };
            if matches!(update, Some(Link::Up)) {
                eprintln!("mqtt: connected");
                lock(&status).cloud_connected = true;
            }
            if let Some(update) = update {
                if events.send(update).is_err() {
                    return;
                }
            }
        }
    });
    drain(client, link, plant, database, shared)
}

fn drain(
    client: Client,
    link: Receiver<Link>,
    plant: String,
    database: PathBuf,
    shared: Shared,
) -> Result<()> {
    let store = Store::open(&database)?;
    loop {
        // Discard anything left over from an earlier attempt.
        while link.try_recv().is_ok() {}
        lock(&shared).unsent = store.unsent_count()?;
        if !lock(&shared).cloud_connected {
            std::thread::sleep(Duration::from_secs(1));
            continue;
        }
        let rows = store.unsent(CHUNK)?;
        let Some(&(last_id, _)) = rows.last() else {
            std::thread::sleep(Duration::from_secs(1));
            continue;
        };
        let (topic, body) = message(&plant, &rows, OffsetDateTime::now_utc())?;
        if let Err(e) = client.publish(topic, QoS::AtLeastOnce, false, body) {
            eprintln!("mqtt: publish not queued: {e}");
            std::thread::sleep(Duration::from_secs(2));
            continue;
        }
        if wait_for_ack(&link) {
            store.mark_sent(last_id)?;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
}

/// True once the acknowledgement for the message just queued has arrived.
fn wait_for_ack(link: &Receiver<Link>) -> bool {
    let deadline = Instant::now() + ACK_TIMEOUT;
    let mut ours = None;
    while let Some(left) = deadline.checked_duration_since(Instant::now()) {
        match link.recv_timeout(left) {
            Ok(Link::Sent(id)) => ours = ours.or(Some(id)),
            Ok(Link::Acked(id)) if ours == Some(id) => return true,
            Ok(Link::Down) | Err(_) => return false,
            Ok(_) => {}
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn routes_fresh_and_old_readings() {
        let now = OffsetDateTime::now_utc();
        let row = |age: i64| {
            let ts = rfc3339(now - time::Duration::seconds(age));
            (
                1,
                format!(
                    r#"{{"plant_id":"p","sensor_id":"s","ts":"{ts}","value":null,"quality_flag":1,"source":"hardware"}}"#
                ),
            )
        };
        let (topic, body) = message("p", &[row(1)], now).unwrap();
        assert_eq!(topic, "plants/p/readings");
        assert!(body.starts_with("[{\"plant_id\""));
        let (topic, body) = message("p", &[row(600), row(1)], now).unwrap();
        assert_eq!(topic, "plants/p/backfill");
        assert!(body.contains("\"kind\":\"reading\""));
    }

    #[test]
    fn only_our_own_acknowledgement_counts() {
        let (tx, rx) = channel();
        for e in [
            Link::Acked(9),
            Link::Sent(2),
            Link::Acked(9),
            Link::Acked(2),
        ] {
            tx.send(e).unwrap();
        }
        assert!(wait_for_ack(&rx));
        tx.send(Link::Sent(3)).unwrap();
        tx.send(Link::Down).unwrap();
        assert!(!wait_for_ack(&rx));
    }
}
