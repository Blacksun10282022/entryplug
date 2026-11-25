use crate::config::{self, Config};
use crate::domain::shapes;
use crate::pilots::{self, PilotKind};
use crate::store::{self, index, search::{self, SearchOpts}, telemetry};
use crate::util;
use serde::Serialize;
use std::fs;
use std::path::Path;
use std::time::Instant;

const PILOT_ONLY: &str = "(boot line for you, the pilot: never paste it, a hook or trust status, or index numbers into an answer for the owner)";

#[derive(Debug, Serialize)]
pub struct LayerStatus { pub key: String, pub label: String, pub ok: bool, pub detail: String }
#[derive(Debug, Serialize)]
pub struct StatusReport {
    pub layers: Vec<LayerStatus>, pub plug_off: bool, pub due_line: Option<String>, pub review_line: Option<String>,
    pub sync_rate: f64, pub verdict: String, pub panel: String, pub exit_code: i32,
}

fn dots(label: &str, width: usize) -> String { let mut s = format!("{} ", label); while s.len() < width { s.push('.'); } s.push(' '); s }
fn mark(ok: bool) -> &'static str { if ok { "[OK]" } else { "[NG]" } }
fn layer(key: &str, label: &str, (ok, detail): (bool, String)) -> LayerStatus { LayerStatus { key: key.into(), label: label.into(), ok, detail } }

fn check_index(cfg: &Config) -> (bool, String, bool) {
    let ip = cfg.index_path();
    if !ip.is_file() { return (false, format!("{} missing — nothing can be searched", cfg.index_rel), false); }
    let con = match store::open_ro(&ip) { Ok(c) => c, Err(e) => return (false, format!("{} unreadable ({})", cfg.index_rel, e), false) };
    if !store::is_v2_schema(&con) { return (false, format!("{} is legacy schema v1 (run plug index --full)", cfg.index_rel), false); }
    let docs: i64 = con.query_row("SELECT CAST(value AS INTEGER) FROM meta WHERE key='docs_count'", [], |r| r.get(0)).unwrap_or(0);
    let t0 = Instant::now();
    if let Err(e) = search::search(cfg, &SearchOpts { queries: vec!["entryplug".into()], scope: "all".into(), k: 3, check_stale: false, ..Default::default() }) {
        return (false, format!("{} query failed ({})", cfg.index_rel, e), false);
    }
    let base = format!("{} ({} docs, {}ms)", Path::new(&cfg.index_rel).file_name().and_then(|s| s.to_str()).unwrap_or("state.sqlite"), docs, t0.elapsed().as_millis());
    match index::stale_lag(cfg) { Some(l) => (false, format!("{} · STALE: {} (MCP reads it as is)", base, l), true), None => (true, base, true) }
}

fn check_base(cfg: &Config) -> (bool, String) {
    let Ok(txt) = fs::read_to_string(cfg.self_dir().join("RULES.md")) else { return (false, format!("{}/RULES.md missing", cfg.self_rel)) };
    let cnt = |d: &Path| fs::read_dir(d).ok().into_iter().flatten().flatten().filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("md")).count();
    let mut p = vec![format!("RULES {}", shapes::parse_rules(&txt).ids.len())];
    if cfg.self_dir().join("style.md").is_file() { p.push("style".into()); }
    p.push(format!("facts {}", cnt(&cfg.self_dir().join("facts"))));
    let mems = cnt(&cfg.memory_dir()); if mems > 0 { p.push(format!("memory {}", mems)); }
    p.push(format!("records {}", cnt(&cfg.records_dir())));
    (true, format!("{}/ ({})", cfg.self_rel, p.join(" · ")))
}

fn check_atfield(cfg: &Config) -> (bool, String) {
    let hook = pilots::precommit_path(&cfg.root);
    let pre_ok = pilots::precommit_hook_ok(&hook);
    let pre_msg = if pre_ok { "pre-commit armed" } else if !hook.exists() { "pre-commit NOT installed" } else { "pre-commit NOT plug init hook" };
    let claude = pilots::audit_pilot(cfg, PilotKind::ClaudeCode);
    let has_other = cfg.root.join(".codex/hooks.json").is_file() || cfg.root.join(pilots::AGY_PLUGIN).join("hooks.json").is_file();
    if !claude.installed && has_other { return (pre_ok, format!("no Claude deny (pretool+pre-commit active) · {}", pre_msg)); }
    if !claude.installed { return (false, format!("deny MISSING · {}", pre_msg)); }
    match claude.issues.iter().find(|s| s.contains("deny")) {
        None => (pre_ok, format!("deny written ({} rules) · {}", pilots::deny_rules(cfg).len(), pre_msg)),
        Some(iss) => (false, format!("{} · {}", iss, pre_msg)),
    }
}

fn check_worktree(cfg: &Config) -> (bool, String) {
    let mut args = vec!["-c", "core.quotePath=false", "status", "--porcelain", "-z", "--untracked-files=no", "--", "plug.yaml", "self/RULES.md", "self/style.md", "self/facts", "tools"];
    let extra: Vec<String> = cfg.protect.iter().filter(|p| !p.contains('*')).cloned().collect();
    args.extend(extra.iter().map(String::as_str));
    let Some(raw) = util::git_ro(&cfg.root, &args) else { return (true, "not a git repo".into()) };
    if raw.trim().is_empty() { return (true, "clean (protected paths match HEAD)".into()); }
    let (policy, _) = cfg.head_policy();
    let drift: Vec<String> = raw.split('\0').filter(|e| e.len() >= 4).map(|e| e[3..].trim().replace('\\', "/"))
        .filter(|p| !p.to_lowercase().ends_with("/playbooks/index.md") && config::is_protected(&policy, p)).collect();
    if drift.is_empty() { (true, "clean (protected paths match HEAD)".into()) }
    else { (false, format!("protected drift vs HEAD: {}{}", drift.iter().take(3).cloned().collect::<Vec<_>>().join(", "), if drift.len() > 3 { format!(" +{}", drift.len() - 3) } else { String::new() })) }
}

fn check_sortie(cfg: &Config) -> (bool, String) {
    if cfg.outbound.is_empty() { return (false, "no outbound list in plug.yaml".into()); }
    let audits = [PilotKind::ClaudeCode, PilotKind::Codex, PilotKind::Antigravity].map(|p| pilots::audit_pilot(cfg, p));
    let inst: Vec<_> = audits.iter().filter(|a| a.installed).collect();
    if inst.is_empty() { return (false, "no pilot hooks wired (run plug init --pilot all)".into()); }
    let probs: Vec<String> = inst.iter().flat_map(|a| a.issues.iter().cloned()).collect();
    if !probs.is_empty() { return (false, probs.join("; ")); }
    (true, format!("armed ({}){}", inst.iter().map(|a| a.pilot.name()).collect::<Vec<_>>().join("+"), if cfg.plug_off() { " (passing through: .plug-off)" } else { "" }))
}

pub fn build_report(cfg: &Config) -> StatusReport {
    let (io, im, iu) = check_index(cfg);
    let hook = pilots::precommit_path(&cfg.root);
    let berserk = if std::env::var("KB_APPROVE").ok().as_deref() == Some("1") { (false, "DISARMED (KB_APPROVE=1)".into()) }
        else if !hook.exists() { (false, "no pre-commit hook".into()) }
        else if !pilots::precommit_hook_ok(&hook) { (false, "pre-commit hook is not plug init's".into()) } else { (true, "armed".into()) };
    let eq = {
        let names: Vec<&str> = cfg.tools.iter().map(|t| t.name.as_str()).collect();
        let gone: Vec<&str> = cfg.tools.iter().filter(|t| !t.dir.is_dir()).map(|t| t.name.as_str()).collect();
        let pend = fs::read_dir(cfg.proposals_dir().join("pending")).ok().into_iter().flatten().flatten().filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("md")).count();
        let mut d = format!("{} registered ({}) · {} pending", names.len(), if names.is_empty() { "none".into() } else { names.join(", ") }, pend);
        if !gone.is_empty() { d.push_str(&format!(" · MISSING: {}", gone.join(", "))); }
        (gone.is_empty(), d)
    };
    let layers = vec![
        layer("index", "LCL pressure", (io, im)), layer("base", "A10 nerve link", check_base(cfg)),
        layer("at-field", "AT-Field", check_atfield(cfg)), layer("berserk", "Berserk lock", berserk),
        layer("sortie", "Sortie lock", check_sortie(cfg)), layer("worktree", "Worktree", check_worktree(cfg)), layer("equipment", "Equipment bay", eq),
    ];
    let bad: Vec<&LayerStatus> = layers.iter().filter(|l| !l.ok).collect();
    let sync_rate = 100.0 * (layers.len() - bad.len()) as f64 / layers.len() as f64;
    let repo = cfg.root.file_name().and_then(|s| s.to_str()).unwrap_or("UNIT").to_uppercase();
    let verdict = if bad.is_empty() { format!("SYNC RATE {:.1}% — ALL SYSTEMS NOMINAL. {}, LIFT OFF.", sync_rate, repo) }
        else { format!("SYNC RATE {:.1}% — PATTERN ORANGE: {} degraded", sync_rate, bad.iter().map(|l| l.label.as_str()).collect::<Vec<_>>().join(" · ")) };
    let plug_off = cfg.plug_off();
    let due = (!plug_off).then(|| {
        let con = store::open_ro(&cfg.index_path()).ok()?;
        let mut st = con.prepare("SELECT due, doc FROM records WHERE kind='decision' AND due != '' AND due <= ?1 AND outcome = '' AND superseded_by = '' ORDER BY due ASC").ok()?;
        let rows: Vec<(String, String)> = st.query_map([util::today_iso()], |r| Ok((r.get(0)?, r.get(1)?))).ok()?.filter_map(Result::ok).collect();
        let (day, stem) = rows.first()?; let more = rows.len() - 1;
        Some(format!("[--] {}{} due, no outcome yet: {}{} (due {}){} — {} the owner's to give: check later records and logs, then ask him for what they do not show",
            dots("Records due", 20), rows.len(), if more > 0 { "oldest " } else { "" }, stem, day,
            if more > 0 { format!(", and {} more", more) } else { String::new() }, if more > 0 { "their outcomes are" } else { "its outcome is" }))
    }).flatten();
    let rev = (!plug_off).then(|| {
        let mut notes: Vec<String> = Vec::new();
        let hot: Vec<String> = telemetry::list_topic_pulse(cfg).into_iter().filter(|tp| tp.sessions_since >= cfg.topic_pulse_sessions || tp.fragments_since >= cfg.topic_pulse_fragments).map(|tp| format!("{} ({}s/{}f)", tp.topic, tp.sessions_since, tp.fragments_since)).collect();
        if !hot.is_empty() { notes.push(format!("hot topics: {}", hot.join(", "))); }
        // Never reviewed but records exist counts as due too, or a new repo never gets its first nudge.
        match telemetry::last_review_ts(cfg).and_then(|s| s.get(..10).and_then(shapes::parse_day)) { Some(d) => { let days = (util::today() - d).num_days(); if days >= cfg.review_interval_days { notes.push(format!("{}d since last review", days)); } } None => if store::open_ro(&cfg.index_path()).ok().and_then(|c| c.query_row("SELECT COUNT(*) FROM records", [], |r| r.get::<_, i64>(0)).ok()).unwrap_or(0) > 0 { notes.push("never reviewed".into()); } }
        (!notes.is_empty()).then(|| format!("[--] {}{} — run `plug review`", dots("Review due", 20), notes.join(" · ")))
    }).flatten();
    let mut ls = vec![
        "ENTRY PLUG — INSERTION SEQUENCE".into(),
        format!("{} {}{}", mark(layers[0].ok), dots(&layers[0].label, 20), layers[0].detail),
        format!("{} {}{}", mark(layers[1].ok), dots(&layers[1].label, 20), layers[1].detail),
        format!("{} {}{}", mark(layers[2].ok), dots(&layers[2].label, 20), layers[2].detail),
        format!("{} {}{:<14} {} {}{}", mark(layers[3].ok), dots(&layers[3].label, 20), layers[3].detail, mark(layers[4].ok), dots(&layers[4].label, 15), layers[4].detail),
        format!("{} {}{}", mark(layers[5].ok), dots(&layers[5].label, 20), layers[5].detail),
        format!("{} {}{}", mark(layers[6].ok), dots(&layers[6].label, 20), layers[6].detail),
        format!("[--] {}{}", dots("plug-off", 20), if plug_off { "present — sortie lock, compaction pin and record reminder pass through" } else { "not present" }),
    ];
    if let Some(d) = &due { ls.push(d.clone()); }
    if let Some(r) = &rev { ls.push(r.clone()); }
    ls.push(verdict.clone());
    StatusReport { layers, plug_off, due_line: due, review_line: rev, sync_rate, verdict, panel: ls.join("\n"), exit_code: if iu { 0 } else { 1 } }
}

pub fn run(cfg: &Config, emit: Option<&str>, as_json: bool) -> i32 {
    let rep = build_report(cfg);
    if as_json { println!("{}", serde_json::to_string_pretty(&rep).unwrap_or_else(|_| "{}".into())); return rep.exit_code; }
    if let Some(target) = emit {
        let mut parts = vec![format!("entry plug boot: {}", rep.verdict)];
        parts.extend(rep.layers.iter().filter(|l| !l.ok).map(|l| format!("[NG] {}: {}", l.label, l.detail)));
        parts.extend(rep.due_line.iter().cloned()); parts.extend(rep.review_line.iter().cloned());
        println!("{}", pilots::format_boot(PilotKind::from_str(target).unwrap_or(PilotKind::ClaudeCode), &rep.panel, &format!("{} {}", parts.join(" · "), PILOT_ONLY)));
        return 0;
    }
    println!("{}", rep.panel);
    rep.exit_code
}
