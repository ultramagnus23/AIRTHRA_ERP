//! Publishing against a minimal in-process MQTT broker.

use airthra_edge::config::Mqtt;
use airthra_edge::model::{rfc3339, Reading, Shared, State};
use airthra_edge::store::Store;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::mpsc::channel;
use std::time::{Duration, Instant};
use time::OffsetDateTime;

/// Reads one MQTT packet: (first byte, body).
fn packet(stream: &mut impl Read) -> Option<(u8, Vec<u8>)> {
    let mut byte = [0u8; 1];
    stream.read_exact(&mut byte).ok()?;
    let header = byte[0];
    let (mut length, mut shift) = (0usize, 0);
    loop {
        stream.read_exact(&mut byte).ok()?;
        length |= usize::from(byte[0] & 0x7F) << shift;
        if byte[0] & 0x80 == 0 {
            break;
        }
        shift += 7;
    }
    let mut body = vec![0; length];
    stream.read_exact(&mut body).ok()?;
    Some((header, body))
}

#[test]
fn rows_are_marked_sent_only_after_the_broker_acknowledges() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let (seen, published) = channel();
    let (release, gate) = channel::<()>();
    std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        while let Some((header, body)) = packet(&mut stream) {
            match header >> 4 {
                1 => stream.write_all(&[0x20, 2, 0, 0]).unwrap(), // CONNACK
                3 => {
                    let topic_len = usize::from(u16::from_be_bytes([body[0], body[1]]));
                    let topic = String::from_utf8(body[2..2 + topic_len].to_vec()).unwrap();
                    let id = [body[2 + topic_len], body[3 + topic_len]];
                    let payload = String::from_utf8(body[4 + topic_len..].to_vec()).unwrap();
                    seen.send((topic, payload)).unwrap();
                    gate.recv().unwrap();
                    stream.write_all(&[0x40, 2, id[0], id[1]]).unwrap(); // PUBACK
                }
                12 => stream.write_all(&[0xD0, 0]).unwrap(), // PINGRESP
                _ => {}
            }
        }
    });

    let dir = std::env::temp_dir().join(format!("airthra-broker-{}", std::process::id()));
    let database = dir.join("q.db");
    let _ = std::fs::remove_file(&database);
    let mut store = Store::open(&database).unwrap();
    store
        .insert(&[Reading {
            plant_id: "p1".into(),
            sensor_id: "pH".into(),
            ts: rfc3339(OffsetDateTime::now_utc()),
            value: Some(7.0),
            quality_flag: 0,
            source: "hardware".into(),
        }])
        .unwrap();
    let shared: Shared = std::sync::Arc::new(std::sync::Mutex::new(State::default()));
    let config = Mqtt {
        host: "127.0.0.1".into(),
        port,
        username: "u".into(),
        password: "test-only".into(),
        ca_cert: None,
    };
    let path = database.clone();
    std::thread::spawn(move || airthra_edge::uplink::run(config, "p1".into(), path, shared));

    let (topic, payload) = published.recv_timeout(Duration::from_secs(10)).unwrap();
    assert_eq!(topic, "plants/p1/readings");
    assert!(payload.contains("\"sensor_id\":\"pH\""));
    assert_eq!(store.unsent_count().unwrap(), 1, "not yet acknowledged");
    release.send(()).unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while store.unsent_count().unwrap() != 0 {
        assert!(Instant::now() < deadline, "row never marked sent");
        std::thread::sleep(Duration::from_millis(50));
    }
    let _ = std::fs::remove_dir_all(dir);
}
