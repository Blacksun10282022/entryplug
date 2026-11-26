use crate::config::{self, Config};
use crate::domain::{quotes, shapes};
use crate::pilots::{self, HookCall, PilotKind};
use crate::store::{self, index, telemetry};
use crate::util;
use regex::Regex;
use serde_json::json;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

const EDIT_TOOLS: &[&str] = &["Edit", "Write", "MultiEdit", "NotebookEdit", "edit_file", "write_file", "write_to_file", "replace_file_content", "multi_replace_file_content", "apply_patch"];

fn load_cfg_from_hint(cwd: Option<&str>) -> Result<Config, String> {
    if let Ok(r) = std::env::var("PLUG_ROOT") { if !r.trim().is_empty() { return config::load(Path::new(&r)); } }
    config::load(&config::find_root(cwd.map(Path::new))?)
}
fn agy_empty(p: PilotKind) -> i32 { if p == PilotKind::Antigravity { println!("{{}}"); } 0 }

fn check_worktree_lock(cfg: &Config, call: &HookCall) -> Option<String> {
    if std::env::var("KB_APPROVE").ok().as_deref() == Some("1") { return None; }
    let hooks_pre = format!("{}/", cfg.hooks_rel.trim_matches('/'));
    if EDIT_TOOLS.contains(&call.tool_name.as_str()) {
        let (policy, _) = cfg.head_policy();
        for rel in call.file_paths.iter().filter_map(|r| config::canonical_rel_inside(&cfg.root, r)) {
            if config::is_protected(&policy, &rel) || rel.starts_with(&hooks_pre) || rel == cfg.hooks_rel.trim_matches('/') {
                return Some(format!("berserk lock: {} cannot edit protected path '{}' — write a proposal under {}/pending/ for owner `plug apply`", call.tool_name, rel, cfg.proposals_rel));
            }
        }
    }
    if let Some(cmd) = &call.command {
        // `2>&1`, `2>/dev/null`, `> $null` write nowhere: drop them, or every read that silences stderr reads as a write.
        static RE_SAFE: OnceLock<Regex> = OnceLock::new(); let cmd = &RE_SAFE.get_or_init(|| Regex::new(r"(?i)\d?>&\d|\d?>>?\s*(?:/dev/null|\$null|nul)\b").unwrap()).replace_all(cmd, " ").into_owned();
        static RE_MUT: OnceLock<Regex> = OnceLock::new(); static RE_RED: OnceLock<Regex> = OnceLock::new();
        let spans: Vec<&str> = if RE_MUT.get_or_init(|| Regex::new(r"(?i)(?:\bsed\s+-i|\brm\b|\bRemove-Item|\bmv\b|\bMove-Item|\bcp\b|\bCopy-Item|write_text|write_bytes|shutil\.|git\s+checkout\s+--|git\s+restore)").unwrap()).is_match(cmd) { vec![cmd.as_str()] }
            else { RE_RED.get_or_init(|| Regex::new(r"(?i)(?:(?:^|[\s0-9])>>?|\b(?:tee|Out-File|Set-Content|Add-Content)\b)[^;&|\r\n]*").unwrap()).find_iter(cmd).map(|m| m.as_str()).collect() };
        if !spans.is_empty() {
            let (policy, _) = cfg.head_policy();
            for span in spans {
                for tok in span.split(|c: char| c.is_whitespace() || matches!(c, '"' | '\'' | ';' | '|' | '&' | '(' | ')' | '>' | '<')).map(str::trim).filter(|t| !t.is_empty() && !t.starts_with('-')) {
                    let norm = tok.replace('\\', "/");
                    if norm.contains(&hooks_pre) || norm.ends_with(cfg.hooks_rel.trim_matches('/')) { return Some(format!("berserk lock: shell command mutates protected path '{}'", norm)); }
                    if let Some(rel) = config::canonical_rel_inside(&cfg.root, &norm).filter(|r| !r.is_empty() && (config::is_protected(&policy, r) || r.starts_with(&hooks_pre))) { return Some(format!("berserk lock: shell command mutates protected path '{}'", rel)); }
                }
            }
        }
    }
    None
}

pub fn run_pretool() -> i32 {
    let Some(call) = pilots::detect_and_parse_stdin(&util::read_stdin_if_piped()) else { return 0 };
    let Ok(cfg) = load_cfg_from_hint(call.cwd.as_deref()) else { return 0 };
    if let Some(reason) = check_worktree_lock(&cfg, &call) {
        telemetry::log_event(&cfg, "gate_deny", &reason, call.pilot.name(), "");
        println!("{}", pilots::format_deny(call.pilot, &reason));
        return 0;
    }
    if cfg.plug_off() { return 0; }
    util::stamp_hook(&cfg.hooks_dir(), "outbound");
    let target_text = call.command.clone().unwrap_or_else(|| serde_json::to_string(&call.raw_args).unwrap_or_default());
    for rule in &cfg.outbound {
        if Regex::new(&rule.tool).map(|r| r.is_match(&call.tool_name)).unwrap_or(false)
            && (rule.match_re.trim().is_empty() || Regex::new(&rule.match_re).map(|r| r.is_match(&target_text)).unwrap_or(false))
        {
            let reason = format!("sortie lock: {} matched outbound rule ({}) — outward actions need the owner's own hands: {}", call.tool_name, rule.tool, target_text.chars().take(100).collect::<String>());
            telemetry::log_event(&cfg, "gate_deny", &reason, call.pilot.name(), "");
            println!("{}", pilots::format_deny(call.pilot, &reason));
            return 0;
        }
    }
    0
}

fn verify_record_quotes_fast(cfg: &Config, body: &str) -> Vec<String> {
    let qrefs = quotes::extract_quotes(body);
    if qrefs.is_empty() { return Vec::new(); }
    let Ok(con) = store::open_ro(&cfg.index_path()) else { return Vec::new() };
    let Ok(mut st) = con.prepare("SELECT DISTINCT doc, title, file FROM chunks WHERE scope = 'corpus'") else { return Vec::new() };
    let rows: Vec<(String, String, String)> = st.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?))).ok().into_iter().flatten().filter_map(Result::ok).collect();
    let (mut cache, mut bad) = (HashMap::<String, String>::new(), Vec::new());
    for qr in &qrefs {
        let hn = quotes::norm_title(&qr.doc_hint);
        let cands: Vec<_> = rows.iter().filter(|(d, t, _)| d == &qr.doc_hint || t == &qr.doc_hint || (hn.chars().count() >= 2 && (quotes::norm_title(t).contains(&hn) || quotes::norm_title(d).contains(&hn)))).take(5).collect();
        if cands.is_empty() { bad.push(format!("unknown corpus doc '{}' for「{}」", qr.doc_hint, qr.quote.chars().take(24).collect::<String>())); continue; }
        let ok = cands.iter().any(|(_, _, f)| quotes::quote_matches_text(&qr.quote, cache.entry(f.clone()).or_insert_with(|| fs::read_to_string(cfg.root.join(f)).map(|t| quotes::compact_ws(&t)).unwrap_or_default())));
        if !ok { bad.push(format!("quote not found in '{}':「{}」", qr.doc_hint, qr.quote.chars().take(28).collect::<String>())); }
    }
    bad
}

pub fn run_posttool() -> i32 {
    let Some(call) = pilots::detect_and_parse_stdin(&util::read_stdin_if_piped()) else { return 0 };
    let Ok(cfg) = load_cfg_from_hint(call.cwd.as_deref()) else { return agy_empty(call.pilot) };
    let mut advs = Vec::new();
    for rel in call.file_paths.iter().filter_map(|p| config::canonical_rel_inside(&cfg.root, p)) {
        let _ = index::index_one_file(&cfg, &rel);
        let Some((area, _, _)) = config::classify_rel(&cfg, &rel).filter(|(a, _, _)| a == "record" || a == "memory") else { continue };
        let Ok(text) = fs::read_to_string(cfg.root.join(&rel)) else { continue };
        let p = shapes::parse_file(&text, &area);
        if area == "record" {
            let v = shapes::fm_str(&p.fm, "verdict");
            if shapes::record_kind(&p.fm) == shapes::RecordKind::Decision && !v.is_empty() {
                telemetry::record_blind_commitment(&cfg, &rel, &text, &v, !shapes::fm_str(&p.fm, "chosen").is_empty());
            }
            let bad = verify_record_quotes_fast(&cfg, &p.body);
            if !bad.is_empty() {
                let msg = format!("entryplug quote verify ({}): {}", rel, bad.join("; "));
                telemetry::log_event(&cfg, "quote_reject", &msg, call.pilot.name(), &shapes::fm_str(&p.fm, "tool"));
                advs.push(msg);
            }
        }
        let pk = [shapes::fm_str(&p.fm, "topic"), shapes::fm_str(&p.fm, "tool")].into_iter().find(|s| !s.is_empty() && s != "none").unwrap_or_default();
        if !pk.is_empty() { telemetry::bump_topic_pulse(&cfg, &pk, 0, 1); }
    }
    let out = pilots::format_context(call.pilot, "PostToolUse", (!advs.is_empty()).then(|| advs.join("\n")).as_deref());
    if !out.is_empty() { println!("{}", out); }
    0
}

fn cooldown_ready(stamp: &Path, hours: f64) -> bool {
    hours <= 0.0 || fs::metadata(stamp).and_then(|m| m.modified()).ok().and_then(|t| SystemTime::now().duration_since(t).ok()).map(|d| d.as_secs_f64() >= hours * 3600.0).unwrap_or(true)
}

pub fn run_prompt() -> i32 {
    let Some(call) = pilots::detect_and_parse_stdin(&util::read_stdin_if_piped()) else { return 0 };
    let Ok(cfg) = load_cfg_from_hint(call.cwd.as_deref()) else { return agy_empty(call.pilot) };
    if cfg.plug_off() { return agy_empty(call.pilot); }
    let prompt = call.prompt.as_deref().unwrap_or("");
    let mut notes: Vec<String> = cfg.prompt_hints.iter().filter(|h| Regex::new(&h.pattern).map(|r| r.is_match(prompt)).unwrap_or(false) && cooldown_ready(&cfg.hooks_dir().join(format!("hint_{}", h.id)), h.cooldown_hours))
        .map(|h| { util::stamp_hook(&cfg.hooks_dir(), &format!("hint_{}", h.id)); h.hint.clone() }).collect();
    if !prompt.is_empty() {
        let low = prompt.to_lowercase();
        for tp in telemetry::list_topic_pulse(&cfg).into_iter().filter(|tp| tp.topic.len() >= 2 && low.contains(&tp.topic.to_lowercase())) {
            let st_name = format!("pulse_{}", tp.topic.to_lowercase());
            let mut cs = tp.sessions_since;
            if cooldown_ready(&cfg.hooks_dir().join(&st_name), 1.0) { util::stamp_hook(&cfg.hooks_dir(), &st_name); telemetry::bump_topic_pulse(&cfg, &tp.topic, 1, 0); cs += 1; }
            if cs >= cfg.topic_pulse_sessions || tp.fragments_since >= cfg.topic_pulse_fragments {
                notes.push(format!("[topic_pulse] '{}' accumulated {} sessions / {} fragments — consider `plug review --topic {}` to draft a 2-column experience card for owner approval.", tp.topic, cs, tp.fragments_since, tp.topic));
            }
        }
    }
    let out = pilots::format_context(call.pilot, "UserPromptSubmit", (!notes.is_empty()).then(|| notes.join("\n")).as_deref());
    if !out.is_empty() { println!("{}", out); }
    0
}

pub fn run_precommit() -> i32 {
    let root = std::env::current_dir().ok().and_then(|cwd| util::git_ro(&cwd, &["rev-parse", "--show-toplevel"]).map(|s| PathBuf::from(s.trim())).filter(|p| p.join("plug.yaml").is_file()).map(|p| util::clean_path(&p)).or_else(|| config::find_root(Some(&cwd)).ok()));
    let Some(cfg) = root.and_then(|r| config::load(&r).ok()) else { eprintln!("berserk lock: plug.yaml not found — fix config first"); return 1; };
    let files: Vec<String> = if std::env::var_os("GIT_INDEX_FILE").is_none() && std::env::var("PLUG_STAGED").is_ok() {
        std::env::var("PLUG_STAGED").unwrap_or_default().lines().map(|l| l.trim().replace('\\', "/")).filter(|l| !l.is_empty()).collect()
    } else {
        util::git_ro(&cfg.root, &["diff", "--cached", "--name-only", "-z", "--no-renames", "--diff-filter=ACMRD"]).unwrap_or_default().split('\0').map(|s| s.trim().replace('\\', "/")).filter(|s| !s.is_empty()).collect()
    };
    util::stamp_hook(&cfg.hooks_dir(), "precommit");
    let (policy, from_head) = cfg.head_policy();
    if !from_head { eprintln!("berserk lock warning: HEAD has no readable plug.yaml; using working-tree protection policy"); }
    let hit: Vec<&String> = files.iter().filter(|f| config::is_protected(&policy, f)).collect();
    if !hit.is_empty() && std::env::var("KB_APPROVE").ok().as_deref() != Some("1") {
        let more = if hit.len() > 1 { format!(" ({} in total)", hit.len()) } else { String::new() };
        eprintln!("berserk lock: this commit touches the protected path {}{} — rules and equipment can only be changed through a refit request ({}/pending/); the owner approves with plug apply", hit[0], more, cfg.proposals_rel);
        return 1;
    }
    let bad: Vec<String> = files.iter().flat_map(|rel| {
        config::classify_rel(&cfg, rel).filter(|(a, _, _)| a == "record" || a == "proposal")
            .and_then(|(a, _, _)| fs::read_to_string(cfg.root.join(rel)).ok().map(|t| (a, t)))
            .map(|(a, t)| shapes::parse_file(&t, &a).errors.into_iter().map(|e| format!("{} · {}", rel, e)).collect::<Vec<_>>()).unwrap_or_default()
    }).collect();
    if !bad.is_empty() {
        let more = if bad.len() > 1 { format!(" ({} in total)", bad.len()) } else { String::new() };
        eprintln!("shape error, commit refused: {}{} — fix the file; plug check explains the shape", bad[0], more);
        return 1;
    }
    0
}

fn build_pin(cfg: &Config) -> String {
    let mut recs: Vec<(u128, PathBuf)> = fs::read_dir(cfg.records_dir()).ok().into_iter().flatten().flatten().map(|e| e.path()).filter(|p| p.extension().and_then(|s| s.to_str()) == Some("md"))
        .map(|p| (fs::metadata(&p).and_then(|m| m.modified()).ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_nanos()).unwrap_or(0), p)).collect();
    recs.sort_by(|a, b| b.0.cmp(&a.0));
    let (mut sit, mut tool, mut path) = ("(no records yet)".into(), "(no records yet)".into(), "(none)".into());
    if let Some((_, newest)) = recs.first() {
        if let Ok(txt) = fs::read_to_string(newest) {
            let fm = shapes::split_frontmatter(&txt).0.unwrap_or_default();
            let (s, t) = (shapes::fm_str(&fm, "situation"), shapes::fm_str(&fm, "tool"));
            sit = if s.is_empty() { "?".into() } else { s }; tool = if t.is_empty() { "?".into() } else { t }; path = cfg.rel(newest);
        }
    }
    let pend = fs::read_dir(cfg.proposals_dir().join("pending")).ok().into_iter().flatten().flatten().filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("md")).count();
    format!("[entry plug · compaction pin · {}]\nwhere we are: {}\nrecord: {} (Read it before continuing; do not carry on from memory. A fresh judgment means a new record.)\nequipment: {}\npending proposals: {} ({}/pending/)\nanswer in: {}",
        util::now_hm(), sit, path, tool, pend, cfg.proposals_rel, cfg.language)
}

pub fn run_precompact(emit_flag: bool) -> i32 {
    let call = pilots::detect_and_parse_stdin(&util::read_stdin_if_piped());
    let Ok(cfg) = load_cfg_from_hint(call.as_ref().and_then(|c| c.cwd.as_deref())) else { return 0 };
    if cfg.plug_off() { return 0; }
    let ev = call.as_ref().map(|c| c.event_name.as_str()).filter(|s| !s.is_empty()).unwrap_or(if emit_flag { "SessionStart" } else { "PreCompact" });
    if ev == "PreCompact" && !emit_flag {
        let text = build_pin(&cfg);
        let _ = util::write_lf(&cfg.pin_path(), &(text.clone() + "\n"));
        util::stamp_hook(&cfg.hooks_dir(), "precompact");
        println!("{}", text);
        return 0;
    }
    let text = fs::read_to_string(cfg.pin_path()).unwrap_or_else(|_| build_pin(&cfg));
    println!("{}", json!({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text.trim()}}));
    0
}

pub fn run_stop() -> i32 {
    let call = pilots::detect_and_parse_stdin(&util::read_stdin_if_piped());
    let Ok(cfg) = load_cfg_from_hint(call.as_ref().and_then(|c| c.cwd.as_deref())) else { return 0 };
    if cfg.plug_off() { return 0; }
    // A linked worktree (`.git` is a file) is a copy: its `../archive` may be the real one, so it never syncs.
    // The sync appends to today's log outside any edit tool, so the index is caught up right after (incremental, ~0.1 s);
    // without it every turn left the next boot panel STALE / PATTERN ORANGE (2026-11-25).
    if cfg.logs_rel.is_some() && !cfg.root.join(".git").is_file() { let _ = pilots::trace::sync(&cfg, "all", false); if cfg.index_path().is_file() { let _ = index::build(&cfg, false, false); } }
    let now_s = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
    let win_h: f64 = std::env::var("PLUG_RECORD_WINDOW").ok().and_then(|s| s.parse().ok()).unwrap_or(8.0);
    let since = call.as_ref().and_then(|c| c.transcript_path.as_deref()).and_then(|tp| fs::metadata(tp).ok()?.created().ok()?.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_secs_f64()).unwrap_or(now_s - win_h * 3600.0);
    let newest = fs::read_dir(cfg.records_dir()).ok().into_iter().flatten().flatten().filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("md"))
        .filter_map(|e| e.metadata().ok()?.modified().ok()?.duration_since(UNIX_EPOCH).ok().map(|d| d.as_secs_f64())).fold(None::<f64>, |a, x| Some(a.map_or(x, |v| v.max(x))));
    let nudged = fs::metadata(cfg.hooks_dir().join("stop")).and_then(|m| m.modified()).ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_secs_f64() >= since).unwrap_or(false);
    util::stamp_hook(&cfg.hooks_dir(), "stop");
    if newest.map(|n| n >= since).unwrap_or(false) || nudged { return 0; }
    println!("{}", json!({"systemMessage": format!("entry plug · no record was written this session. If the owner was given options and chose one, write it now: {}/records/<date>-<slug>.md. If nothing was decided, there is nothing to write — this is a reminder, not a gate.", cfg.self_rel)}));
    0
}
