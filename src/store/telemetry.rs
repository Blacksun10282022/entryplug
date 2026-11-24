use crate::config::Config;
use crate::store;
use crate::util;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;

const MAX_TELEMETRY_BYTES: u64 = 5 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BlindEntry { pub ts: String, pub file: String, pub sha1: String, pub verdict_hash: String, pub has_chosen: bool }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryEvent {
    pub ts: String, pub event: String,
    #[serde(default)] pub detail: String, #[serde(default)] pub pilot: String, #[serde(default)] pub topic: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct TopicPulseRow { pub topic: String, pub sessions_since: i64, pub fragments_since: i64, pub last_seen: String, pub last_reviewed: String }

pub fn blind_path(cfg: &Config) -> PathBuf { cfg.kb_dir().join("blind.jsonl") }
pub fn telemetry_path(cfg: &Config) -> PathBuf { cfg.kb_dir().join("telemetry.jsonl") }

pub fn read_blind_map(cfg: &Config) -> HashMap<String, BlindEntry> {
    let mut map = HashMap::new();
    if let Ok(raw) = std::fs::read_to_string(blind_path(cfg)) {
        for line in raw.lines() {
            if let Ok(e) = serde_json::from_str::<BlindEntry>(line) { map.entry(e.file.clone()).or_insert(e); }
        }
    }
    map
}

pub fn record_blind_commitment(cfg: &Config, rel: &str, text: &str, verdict: &str, has_chosen: bool) {
    if verdict.trim().is_empty() || read_blind_map(cfg).contains_key(rel) { return; }
    let entry = BlindEntry {
        ts: util::now_iso(), file: rel.into(), sha1: util::sha1_hex(text.as_bytes()),
        verdict_hash: util::sha256_hex(verdict.trim().as_bytes())[..16].into(), has_chosen,
    };
    let p = blind_path(cfg);
    if let Some(par) = p.parent() { let _ = std::fs::create_dir_all(par); }
    if let (Ok(line), Ok(mut fh)) = (serde_json::to_string(&entry), OpenOptions::new().create(true).append(true).open(&p)) {
        let _ = writeln!(fh, "{}", line);
    }
}

pub fn log_event(cfg: &Config, event: &str, detail: &str, pilot: &str, topic: &str) {
    let p = telemetry_path(cfg);
    if let Some(par) = p.parent() { let _ = std::fs::create_dir_all(par); }
    if std::fs::metadata(&p).map(|m| m.len() >= MAX_TELEMETRY_BYTES).unwrap_or(false) {
        let _ = std::fs::rename(&p, cfg.kb_dir().join("telemetry.jsonl.1"));
    }
    let ev = TelemetryEvent { ts: util::now_iso(), event: event.into(), detail: detail.chars().take(240).collect(), pilot: pilot.into(), topic: topic.into() };
    if let (Ok(line), Ok(mut fh)) = (serde_json::to_string(&ev), OpenOptions::new().create(true).append(true).open(&p)) {
        let _ = writeln!(fh, "{}", line);
    }
}

pub fn read_events(cfg: &Config, since_iso: &str) -> Vec<TelemetryEvent> {
    std::fs::read_to_string(telemetry_path(cfg)).ok().into_iter()
        .flat_map(|r| r.lines().filter_map(|l| serde_json::from_str::<TelemetryEvent>(l).ok()).collect::<Vec<_>>())
        .filter(|e| e.ts.as_str() >= since_iso).collect()
}

pub fn last_review_ts(cfg: &Config) -> Option<String> {
    std::fs::read_to_string(telemetry_path(cfg)).ok()?
        .lines().filter_map(|l| serde_json::from_str::<TelemetryEvent>(l).ok())
        .filter(|e| e.event == "review_done").map(|e| e.ts).last()
}

pub fn bump_topic_pulse(cfg: &Config, topic: &str, add_session: i64, add_fragment: i64) {
    let t = topic.trim();
    if t.is_empty() { return; }
    let Ok(con) = store::open_rw(&cfg.index_path()) else { return };
    if !store::is_v2_schema(&con) { return; }
    let _ = con.execute(
        "INSERT INTO topic_pulse(topic, sessions_since, fragments_since, last_seen, last_reviewed) VALUES(?1,?2,?3,?4,'')
         ON CONFLICT(topic) DO UPDATE SET sessions_since=sessions_since+excluded.sessions_since, fragments_since=fragments_since+excluded.fragments_since, last_seen=excluded.last_seen",
        rusqlite::params![t, add_session, add_fragment, util::now_iso()],
    );
}

pub fn reset_topic_pulse(cfg: &Config, topic: Option<&str>) {
    let Ok(con) = store::open_rw(&cfg.index_path()) else { return };
    if !store::is_v2_schema(&con) { return; }
    let now = util::now_iso();
    if let Some(t) = topic {
        let _ = con.execute("UPDATE topic_pulse SET sessions_since=0, fragments_since=0, last_reviewed=?1 WHERE lower(topic)=lower(?2)", rusqlite::params![now, t]);
    } else {
        let _ = con.execute("UPDATE topic_pulse SET sessions_since=0, fragments_since=0, last_reviewed=?1", [&now]);
    }
}

pub fn list_topic_pulse(cfg: &Config) -> Vec<TopicPulseRow> {
    let Ok(con) = store::open_ro(&cfg.index_path()) else { return Vec::new() };
    let Ok(mut st) = con.prepare("SELECT topic, sessions_since, fragments_since, last_seen, last_reviewed FROM topic_pulse ORDER BY (sessions_since + fragments_since) DESC, last_seen DESC") else { return Vec::new() };
    let out = st.query_map([], |r| Ok(TopicPulseRow { topic: r.get(0)?, sessions_since: r.get(1)?, fragments_since: r.get(2)?, last_seen: r.get(3)?, last_reviewed: r.get(4)? }))
        .ok().into_iter().flatten().filter_map(Result::ok).collect();
    out
}
