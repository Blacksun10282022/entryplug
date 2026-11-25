use crate::config::Config;
use crate::util;
use chrono::{DateTime, Local, NaiveDateTime};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

#[derive(Debug, Default, Serialize, Deserialize)] struct TraceState { offsets: HashMap<String, u64> }
struct Turn { day: String, hhmm: String, pilot: String, role: String, text: String }
#[derive(Debug, Default)] pub struct TraceStats { pub files_scanned: usize, pub turns_written: usize, pub days_touched: usize, pub masked_hits: usize }

fn luhn_ok(digits: &str) -> bool {
    digits.chars().rev().enumerate().try_fold(0u32, |s, (i, c)| {
        let mut n = c.to_digit(10)?; if i % 2 == 1 { n *= 2; if n > 9 { n -= 9; } } Some(s + n)
    }).map(|s| s % 10 == 0).unwrap_or(false)
}

pub fn mask_sensitive(input: &str) -> (String, usize) {
    static RE_KEY: OnceLock<Regex> = OnceLock::new(); static RE_PEM: OnceLock<Regex> = OnceLock::new();
    static RE_PWD: OnceLock<Regex> = OnceLock::new(); static RE_NUM: OnceLock<Regex> = OnceLock::new();
    let mut n = 0;
    let s1 = RE_KEY.get_or_init(|| Regex::new(r"sk-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|xox[bap]-[A-Za-z0-9\-]{20,}|eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}(?:\.[A-Za-z0-9_\-]+)?").unwrap()).replace_all(input, |_: &regex::Captures| { n += 1; "〔已遮：密钥〕" }).into_owned();
    let s2 = RE_PEM.get_or_init(|| Regex::new(r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----").unwrap()).replace_all(&s1, |_: &regex::Captures| { n += 1; "〔已遮：私钥〕" }).into_owned();
    let s3 = RE_PWD.get_or_init(|| Regex::new(r"(?i)((?:password|passwd|pwd|密码)\s*(?:是|为|[:：=])\s*)(\S{4,})").unwrap()).replace_all(&s2, |c: &regex::Captures| { n += 1; format!("{}〔已遮：密码〕", &c[1]) }).into_owned();
    let (mut out, mut last, b) = (String::with_capacity(s3.len()), 0, s3.as_bytes());
    for m in RE_NUM.get_or_init(|| Regex::new(r"(?:\d{4}[ \-]?){3}\d{4}(?:[ \-]?\d{1,3})?[Xx]?").unwrap()).find_iter(&s3) {
        let prev_ok = m.start() == 0 || !matches!(b[m.start() - 1], b'0'..=b'9' | b'A'..=b'Z' | b'a'..=b'z' | b'/' | b'=' | b'_' | b'-' | b':');
        let next_ok = m.end() == b.len() || !matches!(b[m.end()], b'0'..=b'9' | b'A'..=b'Z' | b'a'..=b'z' | b'/' | b'=' | b'_' | b'-');
        let compact: String = m.as_str().chars().filter(|c| *c != ' ' && *c != '-').collect();
        let body = compact.trim_end_matches(&['X', 'x'][..]);
        let is_id = compact.len() == 18 && body.len() >= 12 && matches!(&body[6..8], "19" | "20") && (&body[8..10] >= "01" && &body[8..10] <= "12") && (&body[10..12] >= "01" && &body[10..12] <= "31");
        out.push_str(&s3[last..m.start()]);
        if prev_ok && next_ok && (is_id || (compact.chars().all(|c| c.is_ascii_digit()) && (16..=19).contains(&compact.len()) && luhn_ok(&compact))) { n += 1; out.push_str("〔已遮：卡号或证件号形状〕"); }
        else { out.push_str(m.as_str()); }
        last = m.end();
    }
    out.push_str(&s3[last..]);
    (out, n)
}

fn parse_ts(ts: &str) -> (String, String) {
    if let Ok(dt) = DateTime::parse_from_rfc3339(ts) { let l = dt.with_timezone(&Local); return (l.format("%Y-%m-%d").to_string(), l.format("%H:%M").to_string()); }
    if let Ok(n) = NaiveDateTime::parse_from_str(&ts[..19.min(ts.len())], "%Y-%m-%dT%H:%M:%S") { return (n.format("%Y-%m-%d").to_string(), n.format("%H:%M").to_string()); }
    (util::today_iso(), Local::now().format("%H:%M").to_string())
}

fn extract_turn(pilot: &str, val: &Value) -> Option<Turn> {
    let text_blocks = |v: &Value| -> String {
        v.as_str().map(|s| s.trim().into()).unwrap_or_else(|| v.as_array().map(|a| a.iter().filter_map(|b| (b.get("type").and_then(|t| t.as_str()).unwrap_or("text") == "text").then(|| b.get("text").and_then(|s| s.as_str())).flatten()).collect::<Vec<_>>().join("\n").trim().into()).unwrap_or_default())
    };
    let (role, text, ts) = match pilot {
        "claude-code" => {
            let ty = val.get("type").and_then(|v| v.as_str())?;
            if (ty != "user" && ty != "assistant") || val.get("isCompactSummary").and_then(|v| v.as_bool()) == Some(true) { return None; }
            (if ty == "user" { "主人" } else { "驾驶员" }, text_blocks(val.pointer("/message/content")?), val.get("timestamp").and_then(|v| v.as_str()).unwrap_or(""))
        }
        "codex" => {
            let p = val.get("payload").unwrap_or(val);
            let r = p.get("role").and_then(|v| v.as_str()).or_else(|| val.get("role").and_then(|v| v.as_str()))?;
            if (r != "user" && r != "assistant") || (val.get("type").and_then(|v| v.as_str()) == Some("event_msg") && p.get("type").and_then(|v| v.as_str()) != Some("user_message")) { return None; }
            (if r == "user" { "主人" } else { "驾驶员" }, text_blocks(p.get("content").or_else(|| p.get("message"))?), val.get("timestamp").and_then(|v| v.as_str()).unwrap_or(""))
        }
        "antigravity" => {
            let r = match val.get("type").and_then(|v| v.as_str())? { "USER_INPUT" => "主人", "PLANNER_RESPONSE" => "驾驶员", _ => return None };
            (r, val.get("content").and_then(|v| v.as_str()).unwrap_or("").trim().into(), val.get("created_at").and_then(|v| v.as_str()).unwrap_or(""))
        }
        _ => return None,
    };
    const SKIP: &[&str] = &["<system-reminder", "<task-notification", "<teammate-message", "<local-command-", "<bash-stdout", "<bash-stderr", "<user-prompt-submit-hook", "<command-message", "<persisted-output", "<available-deferred-tools", "[SYSTEM NOTIFICATION", "Stop hook feedback"];
    if text.is_empty() || SKIP.iter().any(|p| text.starts_with(p)) { return None; }
    let (day, hhmm) = parse_ts(ts);
    Some(Turn { day, hhmm, pilot: pilot.into(), role: role.into(), text })
}

fn collect_jsonl(dir: &Path, depth: usize, pilot: &str, out: &mut Vec<(String, PathBuf)>) {
    if depth == 0 { return; }
    for ent in fs::read_dir(dir).ok().into_iter().flatten().flatten() {
        let p = ent.path();
        if p.is_dir() { collect_jsonl(&p, depth - 1, pilot, out); }
        else if p.extension().and_then(|s| s.to_str()) == Some("jsonl") { out.push((pilot.into(), p)); }
    }
}

fn file_mentions_repo(path: &Path, needle: &str) -> bool {
    let Ok(mut f) = File::open(path) else { return false };
    let mut buf = vec![0u8; 8192];
    let n = f.read(&mut buf).unwrap_or(0);
    // The repo name must end there: `base` must not match a sibling copy named `base-wt-x`.
    let s = String::from_utf8_lossy(&buf[..n]).to_lowercase(); s.match_indices(needle).any(|(i, m)| !s[i + m.len()..].starts_with(|c: char| c == '-' || c == '_' || c.is_alphanumeric()))
}

fn discover_sources(cfg: &Config, pf: &str) -> Vec<(String, PathBuf)> {
    if let Ok(extra) = std::env::var("PLUG_TRACE_SOURCES") {
        return extra.split(';').filter_map(|it| it.split_once('=').map(|(p, path)| (p.trim().into(), PathBuf::from(path.trim())))).collect();
    }
    let (home, leaf, mut out) = (util::home_dir(), cfg.root.file_name().unwrap_or_default().to_string_lossy().to_lowercase(), Vec::new());
    if pf == "all" || pf == "claude-code" {
        let slug = util::posix_str(&cfg.root).replace(':', "-").replace('/', "-").to_lowercase();
        for ent in fs::read_dir(home.join(".claude/projects")).ok().into_iter().flatten().flatten() {
            let n = ent.file_name().to_string_lossy().to_lowercase();
            if n == slug || n.ends_with(&leaf) { collect_jsonl(&ent.path(), 1, "claude-code", &mut out); }
        }
    }
    if pf == "all" || pf == "codex" {
        let ch = std::env::var_os("CODEX_HOME").map(PathBuf::from).unwrap_or_else(|| home.join(".codex"));
        let mut c = Vec::new(); collect_jsonl(&ch.join("sessions"), 4, "codex", &mut c);
        out.extend(c.into_iter().filter(|(_, p)| file_mentions_repo(p, &leaf)));
    }
    if pf == "all" || pf == "antigravity" {
        for ent in fs::read_dir(home.join(".gemini/antigravity/brain")).ok().into_iter().flatten().flatten() {
            let p = ent.path().join(".system_generated/logs/transcript.jsonl");
            if p.is_file() && file_mentions_repo(&p, &leaf) { out.push(("antigravity".into(), p)); }
        }
    }
    out
}

pub fn sync(cfg: &Config, pilot_filter: &str, dry_run: bool) -> Result<TraceStats, String> {
    let Some(out_dir) = cfg.logs_dir() else { return Err("plug.yaml has no `logs:` directory configured".into()) };
    let sp = cfg.kb_dir().join("trace_state.json");
    let mut state: TraceState = fs::read_to_string(&sp).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    let (mut by_day, mut stats) = (BTreeMap::<String, Vec<Turn>>::new(), TraceStats::default());
    for (pilot, path) in discover_sources(cfg, pilot_filter) {
        let Ok(meta) = fs::metadata(&path) else { continue };
        let key = util::posix_str(&path);
        let prev = state.offsets.get(&key).copied().unwrap_or(0);
        if meta.len() <= prev { continue; }
        stats.files_scanned += 1;
        let (Ok(mut fh), mut buf) = (File::open(&path), String::new()) else { continue };
        if fh.seek(SeekFrom::Start(prev)).is_err() || fh.read_to_string(&mut buf).is_err() { continue; }
        let last_nl = buf.rfind('\n').map(|i| i + 1).unwrap_or(0);
        if last_nl == 0 { continue; }
        for line in buf[..last_nl].lines() {
            if let Some(t) = serde_json::from_str::<Value>(line).ok().and_then(|v| extract_turn(&pilot, &v)) { by_day.entry(t.day.clone()).or_default().push(t); }
        }
        state.offsets.insert(key, prev + last_nl as u64);
    }
    if !dry_run && !by_day.is_empty() {
        fs::create_dir_all(&out_dir).map_err(|e| e.to_string())?;
        let paste_dir = out_dir.join("粘贴");
        for (day, turns) in &by_day {
            let df = out_dir.join(format!("{}.md", day));
            let is_new = !df.exists();
            let mut fh = OpenOptions::new().create(true).append(true).open(&df).map_err(|e| e.to_string())?;
            if is_new { let _ = writeln!(fh, "# {} 流水\n", day); }
            for t in turns {
                let (masked, n) = mask_sensitive(&t.text);
                stats.masked_hits += n;
                let body = if masked.chars().count() > 2000 {
                    let h = &util::sha256_hex(masked.as_bytes())[..12];
                    let _ = fs::create_dir_all(&paste_dir);
                    let _ = util::write_lf(&paste_dir.join(format!("{}.txt", h)), &masked);
                    format!("{}…\n\n_(长文本全文见 `粘贴/{}.txt`)_", masked.chars().take(400).collect::<String>(), h)
                } else { masked };
                let _ = writeln!(fh, "## {} · {} · {}\n\n{}\n", t.hhmm, t.pilot, t.role, body);
                stats.turns_written += 1;
            }
            stats.days_touched += 1;
        }
        let _ = util::write_lf(&sp, &serde_json::to_string_pretty(&state).unwrap_or_else(|_| "{}".into()));
    } else { stats.days_touched = by_day.len(); stats.turns_written = by_day.values().map(Vec::len).sum(); }
    Ok(stats)
}
