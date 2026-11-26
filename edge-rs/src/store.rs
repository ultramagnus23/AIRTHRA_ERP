//! SQLite: local history plus the queue of readings not yet acknowledged by
//! the broker. One row serves both, so nothing is written twice.

use crate::model::{rfc3339, Reading};
use anyhow::Result;
use rusqlite::{params, Connection};
use std::path::Path;
use time::{Duration, OffsetDateTime};

pub struct Store {
    db: Connection,
}

impl Store {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        let db = Connection::open(path)?;
        db.busy_timeout(std::time::Duration::from_secs(10))?;
        db.pragma_update(None, "journal_mode", "WAL")?;
        db.pragma_update(None, "synchronous", "NORMAL")?;
        db.execute_batch(
            "CREATE TABLE IF NOT EXISTS readings (
                 id      INTEGER PRIMARY KEY AUTOINCREMENT,
                 ts      TEXT NOT NULL,
                 payload TEXT NOT NULL,
                 sent    INTEGER NOT NULL DEFAULT 0
             );
             CREATE INDEX IF NOT EXISTS readings_unsent ON readings(id) WHERE sent = 0;
             CREATE INDEX IF NOT EXISTS readings_ts ON readings(ts);",
        )?;
        Ok(Store { db })
    }

    pub fn insert(&mut self, batch: &[Reading]) -> Result<()> {
        let tx = self.db.transaction()?;
        {
            let mut insert =
                tx.prepare_cached("INSERT INTO readings (ts, payload) VALUES (?1, ?2)")?;
            for reading in batch {
                insert.execute(params![reading.ts, serde_json::to_string(reading)?])?;
            }
        }
        tx.commit()?;
        Ok(())
    }

    /// Oldest unsent rows as (id, payload JSON).
    pub fn unsent(&self, limit: usize) -> Result<Vec<(i64, String)>> {
        let mut query = self.db.prepare_cached(
            "SELECT id, payload FROM readings WHERE sent = 0 ORDER BY id LIMIT ?1",
        )?;
        let rows = query.query_map([limit as i64], |r| Ok((r.get(0)?, r.get(1)?)))?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn unsent_count(&self) -> Result<u64> {
        let n: i64 =
            self.db
                .query_row("SELECT COUNT(*) FROM readings WHERE sent = 0", [], |r| {
                    r.get(0)
                })?;
        Ok(n as u64)
    }

    /// Marks everything up to `last_id` as delivered.
    pub fn mark_sent(&self, last_id: i64) -> Result<()> {
        self.db.execute(
            "UPDATE readings SET sent = 1 WHERE sent = 0 AND id <= ?1",
            [last_id],
        )?;
        Ok(())
    }

    /// Drops delivered history older than the retention window. Undelivered
    /// rows are kept for four times as long to ride out long outages.
    pub fn prune(&self, now: OffsetDateTime, retention_days: i64) -> Result<()> {
        let sent_before = rfc3339(now - Duration::days(retention_days));
        let any_before = rfc3339(now - Duration::days(retention_days * 4));
        self.db.execute(
            "DELETE FROM readings WHERE (sent = 1 AND ts < ?1) OR ts < ?2",
            params![sent_before, any_before],
        )?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn queues_acknowledges_and_prunes() {
        let dir = std::env::temp_dir().join(format!("airthra-store-{}", std::process::id()));
        let path = dir.join("t.db");
        let _ = std::fs::remove_file(&path);
        let mut store = Store::open(&path).unwrap();
        let now = OffsetDateTime::now_utc();
        let reading = |ts: OffsetDateTime| Reading {
            plant_id: "p".into(),
            sensor_id: "s".into(),
            ts: rfc3339(ts),
            value: Some(1.0),
            quality_flag: 0,
            source: "mock".into(),
        };
        store
            .insert(&[reading(now - Duration::days(10)), reading(now)])
            .unwrap();
        let rows = store.unsent(10).unwrap();
        assert_eq!(rows.len(), 2);
        store.prune(now, 7).unwrap();
        assert_eq!(
            store.unsent_count().unwrap(),
            2,
            "unsent rows survive a week's outage"
        );
        store.mark_sent(rows[0].0).unwrap();
        assert_eq!(store.unsent_count().unwrap(), 1);
        store.prune(now, 7).unwrap();
        assert_eq!(store.unsent(10).unwrap()[0].0, rows[1].0);
        drop(store);
        let _ = std::fs::remove_dir_all(dir);
    }
}
