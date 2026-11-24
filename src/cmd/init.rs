use crate::config::Config;
use crate::pilots;
use crate::store::index;
use crate::util;
use regex::Regex;
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

fn put(path: &Path, text: &str, log: &mut Vec<(String, String)>, cfg: &Config) -> Result<bool, String> {
    let norm = text.replace("\r\n", "\n");
    let old = fs::read_to_string(path).ok().map(|s| s.replace("\r\n", "\n"));
    if old.as_deref() == Some(norm.as_str()) { log.push(("already current".into(), cfg.rel(path))); return Ok(false); }
    util::write_lf(path, &norm).map_err(|e| e.to_string())?;
    log.push((if old.is_some() { "updated" } else { "written" }.into(), cfg.rel(path)));
    Ok(true)
}
fn copy_if_absent(path: &Path, content: &str, log: &mut Vec<(String, String)>, cfg: &Config) -> Result<(), String> {
    if path.exists() { log.push(("skipped (exists)".into(), cfg.rel(path))); Ok(()) } else { put(path, content, log, cfg).map(|_| ()) }
}
fn hook_tag(cmd: &str) -> Option<&'static str> {
    let s = cmd.replace('\\', "/");
    if s.contains("gate pretool") || s.contains("gates/outbound.py") || s.contains(" outbound") { Some("pretool") }
    else if s.contains("gate posttool") { Some("posttool") }
    else if s.contains("gate prompt") || s.contains("prompt_hint.py") { Some("prompt") }
    else if s.contains("gate precompact") || s.contains("gates/precompact.py") { Some(if s.contains("--emit") { "precompact-emit" } else { "precompact" }) }
    else if s.contains("status") && s.contains("--emit") { Some("status") }
    else if s.contains("gate stop") || s.contains("gates/stop.py") { Some("stop") }
    else { None }
}

fn install_precommit(cfg: &Config, bin: &str, log: &mut Vec<(String, String)>) -> Result<(), String> {
    if !cfg.root.join(".git").exists() { log.push(("skipped".into(), "pre-commit: not a git repo".into())); return Ok(()); }
    let hook = pilots::precommit_path(&cfg.root);
    if hook.is_file() {
        let old = fs::read_to_string(&hook).unwrap_or_default();
        if !old.contains("gate precommit") && !old.contains("precommit.py") {
            let bak = hook.with_file_name("pre-commit.before-entryplug");
            let _ = fs::rename(&hook, &bak); log.push(("backed up".into(), cfg.rel(&bak)));
        }
    }
    put(&hook, &format!("#!/bin/sh\n# entryplug berserk lock — written by plug init.\nexec \"{}\" gate precommit\n", bin), log, cfg)?;
    #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; let _ = fs::set_permissions(&hook, fs::Permissions::from_mode(0o755)); }
    Ok(())
}

fn install_claude(cfg: &Config, bin: &str, log: &mut Vec<(String, String)>) -> Result<(), String> {
    let settings = cfg.root.join(".claude").join("settings.json");
    let mut data: Value = fs::read_to_string(&settings).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_else(|| json!({}));
    {
        let obj = data.as_object_mut().ok_or("settings.json is not an object")?;
        let deny = obj.entry("permissions").or_insert_with(|| json!({})).as_object_mut().unwrap().entry("deny").or_insert_with(|| json!([])).as_array_mut().unwrap();
        for r in pilots::deny_rules(cfg) { if !deny.iter().any(|x| x.as_str() == Some(&r)) { deny.push(Value::String(r)); } }
        let hooks = obj.entry("hooks").or_insert_with(|| json!({})).as_object_mut().unwrap();
        for (ev, groups) in pilots::claude_hooks_json(cfg, bin).as_object().unwrap() {
            let have = hooks.entry(ev.clone()).or_insert_with(|| json!([])).as_array_mut().unwrap();
            for g in groups.as_array().unwrap() {
                let (wcmd, wtag) = (g["hooks"][0]["command"].as_str().unwrap_or(""), hook_tag(g["hooks"][0]["command"].as_str().unwrap_or("")));
                if let Some(ex) = have.iter_mut().find(|x| x.get("hooks").and_then(|v| v.as_array()).map(|hs| hs.iter().any(|h| { let c = h.get("command").and_then(|v| v.as_str()).unwrap_or(""); c == wcmd || (wtag.is_some() && hook_tag(c) == wtag) })).unwrap_or(false)) { *ex = g.clone(); } else { have.push(g.clone()); }
            }
        }
    }
    put(&settings, &(serde_json::to_string_pretty(&data).unwrap() + "\n"), log, cfg)?;
    let mcp = cfg.root.join(".mcp.json");
    let mut mdata: Value = fs::read_to_string(&mcp).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_else(|| json!({}));
    mdata["mcpServers"]["entryplug"] = json!({"command": bin, "args": ["--root", util::posix_str(&cfg.root), "mcp"]});
    put(&mcp, &(serde_json::to_string_pretty(&mdata).unwrap() + "\n"), log, cfg)?;
    copy_if_absent(&cfg.root.join("CLAUDE.md"), pilots::CLAUDE_MD, log, cfg)
}

fn install_codex(cfg: &Config, bin: &str, log: &mut Vec<(String, String)>) -> Result<(), String> {
    copy_if_absent(&cfg.root.join("AGENTS.md"), pilots::AGENTS_MD, log, cfg)?;
    for p in [bin, &util::posix_str(&cfg.root)] { if p.contains(' ') { log.push(("WARNING".into(), format!("Codex hooks: space in path ({})", p))); } }
    if put(&cfg.root.join(".codex/hooks.json"), &(serde_json::to_string_pretty(&pilots::codex_hooks_json(cfg, bin)).unwrap() + "\n"), log, cfg)? {
        log.push(("RE-TRUST".into(), "Codex hooks changed — open an interactive `codex` in this repo once and trust them on `Hooks need review`.".into()));
    }
    let toml_path = cfg.root.join(".codex/config.toml");
    let old = fs::read_to_string(&toml_path).unwrap_or_default();
    let block = format!("[mcp_servers.entryplug]\ncommand = \"{}\"\nargs = [\"--root\", \"{}\", \"mcp\"]\n", bin, util::posix_str(&cfg.root));
    let next = if old.contains("[mcp_servers.entryplug]") {
        Regex::new(r"(?ms)^\[mcp_servers\.entryplug\][ \t]*\n.*?(?:^\[|\z)").unwrap()
            .replace(&old, |c: &regex::Captures| if c[0].ends_with('[') { format!("{}\n[", block) } else { block.clone() }).trim_end_matches('\n').to_string() + "\n"
    } else if old.trim().is_empty() { block } else { format!("{}\n\n{}", old.trim_end_matches('\n'), block) };
    put(&toml_path, &next, log, cfg).map(|_| ())
}

fn install_antigravity(cfg: &Config, bin: &str, log: &mut Vec<(String, String)>) -> Result<(), String> {
    for p in [bin, &util::posix_str(&cfg.root)] { if p.contains(' ') { log.push(("WARNING".into(), format!("Antigravity hooks: space in path ({})", p))); } }
    for (rel, val) in pilots::antigravity_plugin_files(cfg, bin) { put(&cfg.root.join(&rel), &(serde_json::to_string_pretty(&val).unwrap() + "\n"), log, cfg)?; }
    copy_if_absent(&cfg.root.join("AGENTS.md"), pilots::AGENTS_MD, log, cfg)?;
    copy_if_absent(&cfg.root.join("GEMINI.md"), pilots::GEMINI_MD, log, cfg)
}

pub fn sync_installed_pilots(cfg: &Config) -> Vec<(String, String)> {
    let bin = std::env::var("PLUG_BIN").unwrap_or_else(|_| pilots::current_plug_bin());
    let mut log = Vec::new();
    let _ = install_precommit(cfg, &bin, &mut log);
    if cfg.root.join(".claude/settings.json").is_file() { let _ = install_claude(cfg, &bin, &mut log); }
    if cfg.root.join(".codex/hooks.json").is_file() { let _ = install_codex(cfg, &bin, &mut log); }
    if cfg.root.join(pilots::AGY_PLUGIN).join("hooks.json").is_file() { let _ = install_antigravity(cfg, &bin, &mut log); }
    let _ = index::mirror_skills(cfg);
    log
}

pub fn run(cfg: &Config, pilot: &str, link_skills: bool, print_only: bool) -> i32 {
    let bin = std::env::var("PLUG_BIN").unwrap_or_else(|_| pilots::current_plug_bin());
    let chosen: Vec<&str> = match pilot {
        "claude-code" | "claude" => vec!["claude-code"], "codex" => vec!["codex"], "antigravity" | "agy" => vec!["antigravity"],
        "both" => vec!["claude-code", "codex"], "all" => vec!["claude-code", "codex", "antigravity"],
        o => { eprintln!("init: unknown --pilot '{}'", o); return 1; }
    };
    if print_only {
        println!("bin: {}", bin);
        if chosen.contains(&"claude-code") { println!("--- claude ---\n{}", serde_json::to_string_pretty(&pilots::claude_hooks_json(cfg, &bin)).unwrap()); }
        if chosen.contains(&"codex") { println!("--- codex ---\n{}", serde_json::to_string_pretty(&pilots::codex_hooks_json(cfg, &bin)).unwrap()); }
        if chosen.contains(&"antigravity") { for (k, v) in pilots::antigravity_plugin_files(cfg, &bin) { println!("--- {} ---\n{}", k, serde_json::to_string_pretty(&v).unwrap()); } }
        return 0;
    }
    let mut log = Vec::new();
    let mut step = || -> Result<(), String> {
        install_precommit(cfg, &bin, &mut log)?;
        let gi_p = cfg.root.join(".gitignore");
        let gi_old = fs::read_to_string(&gi_p).unwrap_or_default();
        let ex: BTreeSet<&str> = gi_old.lines().collect();
        let kb_top = format!("{}/", Path::new(&cfg.index_rel).components().next().map(|c| c.as_os_str().to_string_lossy().to_string()).unwrap_or_else(|| ".kb".into()));
        let mut need: Vec<String> = std::iter::once(kb_top).chain(cfg.pilots.values().filter(|ps| !ps.skills.is_empty()).map(|ps| format!("{}/", ps.skills.trim_end_matches('/')))).filter(|x| !ex.contains(x.as_str())).collect();
        need.sort(); need.dedup();
        if need.is_empty() { log.push(("already current".into(), ".gitignore".into())); }
        else { put(&gi_p, &format!("{}{}{}\n", gi_old.trim_end_matches('\n'), if gi_old.is_empty() { "" } else { "\n" }, need.join("\n")), &mut log, cfg)?; }
        for (name, note) in [("work", "# work/\n\nProducts land here. Freely writable.\n"), ("workshop", "# workshop/\n\nDrafts before registration. Freely writable.\n")] { copy_if_absent(&cfg.root.join(name).join("README.md"), note, &mut log, cfg)?; }
        if chosen.contains(&"claude-code") { install_claude(cfg, &bin, &mut log)?; }
        if chosen.contains(&"codex") { install_codex(cfg, &bin, &mut log)?; }
        if chosen.contains(&"antigravity") { install_antigravity(cfg, &bin, &mut log)?; }
        log.push(("mirrored".into(), format!("manuals → {}", index::mirror_skills(cfg)?.join(" · "))));
        if link_skills {
            for pn in &chosen {
                let Some(ps) = cfg.pilots.get(*pn).filter(|p| !p.user_skills.is_empty()) else { continue };
                let base = util::expand_tilde(&ps.user_skills);
                for t in &cfg.tools {
                    if let Ok(txt) = fs::read_to_string(t.dir.join("SKILL.md")) {
                        let dst = base.join(&t.name).join("SKILL.md");
                        let old = fs::read_to_string(&dst).ok();
                        if old.as_deref() == Some(txt.as_str()) { log.push(("already current".into(), util::posix_str(&dst))); }
                        else { util::write_lf(&dst, &txt).map_err(|e| e.to_string())?; log.push((if old.is_some() { "updated" } else { "written" }.into(), util::posix_str(&dst))); }
                    }
                }
            }
        }
        Ok(())
    };
    if let Err(e) = step() { eprintln!("init: {}", e); return 1; }
    for (st, p) in &log { println!("{:<16} {}", st, p); }
    println!("next: plug index → plug status → plug check --contact {}", chosen.join(" and "));
    0
}
