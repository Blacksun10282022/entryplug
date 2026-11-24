use crate::config::Config;
use crate::domain::shapes;
use crate::store::{self, telemetry};
use crate::util;
use chrono::Duration;
use serde::Serialize;
use std::collections::HashMap;
use std::fs;

#[derive(Debug, Serialize)]
struct RecordDigest { file: String, date: String, tool: String, kind: String, situation: String, verdict: String, outcome: String }
#[derive(Debug, Serialize)]
struct ReviewDigest {
    generated_at: String, since: String, topic: Option<String>, recent_records: Vec<RecordDigest>,
    overdue_decisions: Vec<String>, topic_pulses: Vec<telemetry::TopicPulseRow>, memory_counts: HashMap<String, usize>,
    memory_matches: Vec<String>, log_days_matching: Vec<String>, telemetry_counts: HashMap<String, usize>,
    top_zero_hits: Vec<(String, usize)>, quote_rejections: Vec<String>,
}

pub fn run(cfg: &Config, since: &str, topic: Option<&str>, as_json: bool, mark_reviewed: bool) -> i32 {
    let s = since.trim().to_lowercase();
    let days = s.strip_suffix('d').and_then(|n| n.parse::<i64>().ok()).or_else(|| s.strip_suffix('w').and_then(|n| n.parse::<i64>().ok()).map(|w| w * 7)).unwrap_or(7).max(1);
    let cutoff_day = (util::today() - Duration::days(days)).format("%Y-%m-%d").to_string();
    let topic_low = topic.map(|t| t.to_lowercase());
    let (mut recent_records, mut overdue_decisions) = (Vec::new(), Vec::new());

    if let Ok(con) = store::open_ro(&cfg.index_path()) {
        if let Ok(mut st) = con.prepare("SELECT file, date, tool, kind, situation, verdict, outcome, topic FROM records WHERE superseded_by = '' AND date >= ?1 ORDER BY date DESC, file DESC LIMIT 120") {
            for (file, date, tool, kind, sit, verdict, outcome, rt) in st.query_map([&cutoff_day], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?, r.get::<_, String>(4)?, r.get::<_, String>(5)?, r.get::<_, String>(6)?, r.get::<_, String>(7)?))).ok().into_iter().flatten().filter_map(Result::ok) {
                if topic_low.as_ref().map(|tl| format!("{} {} {} {} {}", file, tool, sit, verdict, rt).to_lowercase().contains(tl)).unwrap_or(true) {
                    recent_records.push(RecordDigest { file, date, tool, kind, situation: sit, verdict, outcome });
                }
            }
        }
        if let Ok(mut st) = con.prepare("SELECT file, due, situation FROM records WHERE kind='decision' AND due != '' AND due <= ?1 AND outcome = '' AND superseded_by = '' ORDER BY due ASC") {
            overdue_decisions = st.query_map([util::today_iso()], |r| Ok(format!("{} (due {}): {}", r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))).ok().into_iter().flatten().filter_map(Result::ok).collect();
        }
    }
    let mut topic_pulses = telemetry::list_topic_pulse(cfg);
    if let Some(tl) = &topic_low { topic_pulses.retain(|p| p.topic.to_lowercase().contains(tl)); }

    let (mut memory_counts, mut memory_matches) = (HashMap::<String, usize>::new(), Vec::new());
    for p in fs::read_dir(cfg.memory_dir()).ok().into_iter().flatten().flatten().map(|e| e.path()).filter(|p| p.extension().and_then(|s| s.to_str()) == Some("md") && p.file_name().and_then(|s| s.to_str()) != Some("MEMORY.md")) {
        if let Ok(txt) = fs::read_to_string(&p) {
            let st = shapes::split_frontmatter(&txt).0.map(|f| shapes::fm_str(&f, "status")).filter(|s| !s.is_empty()).unwrap_or_else(|| "unverified".into());
            *memory_counts.entry(st.clone()).or_insert(0) += 1;
            if topic_low.as_ref().map(|tl| p.to_string_lossy().to_lowercase().contains(tl) || txt.to_lowercase().contains(tl)).unwrap_or(false) { memory_matches.push(format!("{} [{}]", cfg.rel(&p), st)); }
        }
    }

    let mut log_days_matching = Vec::new();
    if let Some(ldir) = cfg.logs_dir() {
        let mut files: Vec<_> = fs::read_dir(&ldir).ok().into_iter().flatten().flatten().map(|e| e.path()).collect();
        files.sort();
        for p in files.into_iter().rev() {
            let n = p.file_name().and_then(|s| s.to_str()).unwrap_or("");
            if n.len() != 13 || !n.ends_with(".md") || &n[..10] < cutoff_day.as_str() { continue; }
            if let Some(tl) = &topic_low {
                let hits = fs::read_to_string(&p).map(|t| t.to_lowercase().matches(tl).count()).unwrap_or(0);
                if hits > 0 { log_days_matching.push(format!("{} ({} mentions)", n, hits)); }
            } else { log_days_matching.push(n.into()); }
        }
    }

    let (mut telemetry_counts, mut zero_map, mut quote_rejections) = (HashMap::<String, usize>::new(), HashMap::<String, usize>::new(), Vec::new());
    for ev in telemetry::read_events(cfg, &format!("{}T00:00:00", cutoff_day)) {
        *telemetry_counts.entry(ev.event.clone()).or_insert(0) += 1;
        if ev.event == "zero_hit" { *zero_map.entry(ev.detail).or_insert(0) += 1; }
        else if ev.event == "quote_reject" && quote_rejections.len() < 15 { quote_rejections.push(format!("{} · {}", &ev.ts[..10.min(ev.ts.len())], ev.detail)); }
    }
    let mut top_zero_hits: Vec<(String, usize)> = zero_map.into_iter().collect();
    top_zero_hits.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    top_zero_hits.truncate(15);

    if mark_reviewed {
        telemetry::log_event(cfg, "review_done", &format!("since={} topic={}", since, topic.unwrap_or("all")), "", topic.unwrap_or(""));
        telemetry::reset_topic_pulse(cfg, topic);
    }
    let digest = ReviewDigest { generated_at: util::now_iso(), since: cutoff_day, topic: topic.map(String::from), recent_records, overdue_decisions, topic_pulses, memory_counts, memory_matches, log_days_matching, telemetry_counts, top_zero_hits, quote_rejections };
    if as_json { println!("{}", serde_json::to_string_pretty(&digest).unwrap_or_else(|_| "{}".into())); return 0; }

    println!("# EntryPlug Dual-Loop Review Digest · since {}{}\n\n## Loop A — About Owner\n- Active records: {}", digest.since, digest.topic.as_ref().map(|t| format!(" · topic: {}", t)).unwrap_or_default(), digest.recent_records.len());
    for r in digest.recent_records.iter().take(15) { println!("  - {} `{}` [{}|{}] {} → {}", r.date, r.file, r.tool, r.kind, r.situation, r.verdict.chars().take(60).collect::<String>()); }
    for d in digest.overdue_decisions.iter().take(10) { println!("  - [overdue] {}", d); }
    for tp in digest.topic_pulses.iter().take(10) { println!("  - [pulse] {}: {}s/{}f{}", tp.topic, tp.sessions_since, tp.fragments_since, if tp.sessions_since >= cfg.topic_pulse_sessions || tp.fragments_since >= cfg.topic_pulse_fragments { " [HOT]" } else { "" }); }
    println!("- Shared memory: verified={}, unverified={}, caution={}", digest.memory_counts.get("verified").copied().unwrap_or(0), digest.memory_counts.get("unverified").copied().unwrap_or(0), digest.memory_counts.get("caution").copied().unwrap_or(0));
    for m in digest.memory_matches.iter().take(12) { println!("  - {}", m); }
    if !digest.log_days_matching.is_empty() { println!("- Matching trace logs: {}", digest.log_days_matching.iter().take(10).cloned().collect::<Vec<_>>().join(", ")); }
    println!("\n## Loop B — About EntryPlug\n- Telemetry: zero_hit={}, gate_deny={}, quote_reject={}", digest.telemetry_counts.get("zero_hit").copied().unwrap_or(0), digest.telemetry_counts.get("gate_deny").copied().unwrap_or(0), digest.telemetry_counts.get("quote_reject").copied().unwrap_or(0));
    for (q, n) in digest.top_zero_hits.iter().take(8) { println!("  - ({}x) {}", n, q); }
    for qr in digest.quote_rejections.iter().take(6) { println!("  - {}", qr); }
    println!("\nNext: draft <=5 items (verified wins / caution traps + EntryPlug fixes) for owner approval.");
    0
}
