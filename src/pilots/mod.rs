pub mod trace;

use crate::config::Config;
use crate::util;
use regex::Regex;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub const CLAUDE_MD: &str = include_str!("../../pilots/claude-code/CLAUDE.md");
pub const AGENTS_MD: &str = include_str!("../../pilots/codex/AGENTS.md");
pub const GEMINI_MD: &str = include_str!("../../pilots/antigravity/GEMINI.md");
pub const CLAUDE_PRETOOL_MATCHER: &str = "Bash|PowerShell|shell|Artifact|mcp__.*|Edit|Write|MultiEdit|NotebookEdit";
pub const CLAUDE_POSTTOOL_MATCHER: &str = "Edit|Write|MultiEdit";
pub const CODEX_PRETOOL_MATCHER: &str = "Bash|PowerShell|shell|Artifact|mcp__.*|apply_patch|edit_file|write_file";
pub const CODEX_POSTTOOL_MATCHER: &str = "apply_patch|edit_file|write_file";
pub const AGY_PLUGIN: &str = ".agents/plugins/entryplug";
pub const AGY_PRETOOL_MATCHER: &str = "run_command|send_command_input|manage_task|call_mcp_tool|mcp_.*|write_to_file|replace_file_content|multi_replace_file_content|edit_file|write_file";
pub const AGY_POSTTOOL_MATCHER: &str = "write_to_file|replace_file_content|multi_replace_file_content|edit_file|write_file";
pub const AGY_DESC_MAX: usize = 1024;
pub const CLAUDE_DESC_MAX: usize = 1536;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PilotKind { ClaudeCode, Codex, Antigravity }
impl PilotKind {
    pub fn name(self) -> &'static str { match self { Self::ClaudeCode => "claude-code", Self::Codex => "codex", Self::Antigravity => "antigravity" } }
    pub fn from_str(s: &str) -> Option<Self> { match s { "claude-code" | "claude" => Some(Self::ClaudeCode), "codex" => Some(Self::Codex), "antigravity" | "agy" => Some(Self::Antigravity), _ => None } }
}
#[derive(Debug, Clone)]
pub struct HookCall {
    pub pilot: PilotKind, pub tool_name: String, pub command: Option<String>, pub file_paths: Vec<String>,
    pub raw_args: Value, pub cwd: Option<String>, pub prompt: Option<String>, pub event_name: String, pub transcript_path: Option<String>,
}
#[derive(Debug, Clone)]
pub struct PilotAudit { pub pilot: PilotKind, pub installed: bool, pub ok: bool, pub issues: Vec<String> }

pub fn posix_abs_for_deny(p: &Path) -> String {
    let s = util::posix_str(&util::resolve_existing_or_lexical(p));
    let b = s.as_bytes();
    if b.len() >= 2 && b[0].is_ascii_alphabetic() && b[1] == b':' { format!("//{}{}", (b[0] as char).to_ascii_lowercase(), &s[2..]) } else { s }
}
pub fn deny_rules(cfg: &Config) -> Vec<String> {
    let base = posix_abs_for_deny(&cfg.root);
    let mut rules: Vec<String> = ["self/RULES.md", "self/facts/**", "self/style.md", "plug.yaml"].iter().map(|x| format!("Edit({}/{})", base, x)).collect();
    for t in &cfg.tools {
        let p = t.path.trim_matches('/').replace('\\', "/");
        rules.extend(["SKILL.md", "READING.md", "dict/**", "playbooks/**", "materials/**", "kit/**", "checks/**"].iter().map(|x| format!("Edit({}/{}/{})", base, p, x)));
    }
    rules.extend(cfg.protect.iter().map(|x| format!("Edit({}/{})", base, x.trim_matches('/').replace('\\', "/"))));
    rules.push(format!("Edit({}/{}/**)", base, cfg.hooks_rel.trim_matches('/')));
    rules
}
pub fn current_plug_bin() -> String { util::posix_str(&util::clean_path(&std::env::current_exe().unwrap_or_else(|_| PathBuf::from("plug")))) }

fn mk_cmd(bin: &str, args: &[&str], quote: bool) -> String {
    let head = if quote { format!("\"{}\"", bin) } else { bin.into() };
    std::iter::once(head).chain(args.iter().map(|a| if quote && a.contains(' ') { format!("\"{}\"", a) } else { (*a).into() })).collect::<Vec<_>>().join(" ")
}
fn hgrp(matcher: Option<&str>, cmd: String, timeout: u64) -> Value {
    let h = json!([{"type": "command", "command": cmd, "timeout": timeout}]);
    match matcher { Some(m) => json!({"matcher": m, "hooks": h}), None => json!({"hooks": h}) }
}
fn collect_file_paths(args: &Value, out: &mut Vec<String>) {
    for k in ["file_path", "path", "Path", "TargetFile", "AbsolutePath", "notebook_path"] {
        if let Some(s) = args.get(k).and_then(|v| v.as_str()).map(str::trim).filter(|s| !s.is_empty()) {
            if !out.iter().any(|x| x == s) { out.push(s.into()); }
        }
    }
}

fn jstr<'a>(v: &'a Value, k: &str) -> Option<&'a str> { v.get(k).and_then(|x| x.as_str()) }

pub fn detect_and_parse_stdin(raw: &str) -> Option<HookCall> {
    let val: Value = serde_json::from_str(raw.trim()).ok()?;
    let obj = val.as_object()?;
    let cwd = jstr(&val, "cwd").map(String::from).or_else(|| val.get("workspacePaths").and_then(|v| v.as_array()).and_then(|a| a.first()).and_then(|v| v.as_str()).map(String::from));
    let transcript_path = jstr(&val, "transcript_path").map(String::from);
    if let Some(tc) = val.get("toolCall").filter(|v| v.is_object()) {
        let (raw_name, args) = (jstr(tc, "name").unwrap_or(""), tc.get("args").cloned().unwrap_or_else(|| json!({})));
        let (mut tool_name, mut command, mut file_paths) = (raw_name.to_string(), None, Vec::new());
        match raw_name {
            "run_command" => command = jstr(&args, "CommandLine").map(String::from),
            "send_command_input" => command = jstr(&args, "Input").map(String::from),
            "manage_task" if jstr(&args, "Action") == Some("send_input") => if let Some(inp) = jstr(&args, "Input") { tool_name = "send_command_input".into(); command = Some(inp.into()); },
            "call_mcp_tool" => tool_name = format!("mcp__{}__{}", jstr(&args, "ServerName").unwrap_or(""), jstr(&args, "ToolName").unwrap_or("")),
            n if n.starts_with("mcp_") && !n.starts_with("mcp__") => tool_name = format!("mcp__{}", &n[4..]),
            _ => {}
        }
        collect_file_paths(&args, &mut file_paths);
        return Some(HookCall { pilot: PilotKind::Antigravity, tool_name, command, file_paths, raw_args: args, cwd, prompt: None, event_name: jstr(&val, "hookEventName").unwrap_or("PreToolUse").into(), transcript_path });
    }
    let pilot = if obj.contains_key("hookEventName") || obj.contains_key("workspacePaths") || obj.contains_key("conversationId") { PilotKind::Antigravity }
        else if obj.contains_key("turn_id") { PilotKind::Codex } else { PilotKind::ClaudeCode };
    let (tool_name, args) = (jstr(&val, "tool_name").unwrap_or("").to_string(), val.get("tool_input").cloned().unwrap_or_else(|| json!({})));
    let (command, mut file_paths) = (jstr(&args, "command").map(String::from), Vec::new());
    collect_file_paths(&args, &mut file_paths);
    if tool_name == "apply_patch" {
        for l in jstr(&args, "input").or_else(|| jstr(&args, "patch")).unwrap_or("").lines() {
            for pre in ["*** Update File: ", "*** Add File: ", "*** Delete File: ", "*** Move to: "] { if let Some(p) = l.strip_prefix(pre) { file_paths.push(p.trim().into()); } }
        }
    }
    let prompt = jstr(&val, "prompt").or_else(|| jstr(&val, "userPrompt")).or_else(|| jstr(&val, "user_prompt")).map(String::from);
    let event_name = jstr(&val, "hook_event_name").or_else(|| jstr(&val, "hookEventName")).unwrap_or("").into();
    Some(HookCall { pilot, tool_name, command, file_paths, raw_args: args, cwd, prompt, event_name, transcript_path })
}

pub fn format_deny(pilot: PilotKind, reason: &str) -> String {
    serde_json::to_string(&if pilot == PilotKind::Antigravity { json!({"decision": "deny", "reason": reason}) }
        else { json!({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}) }).unwrap_or_default()
}
pub fn format_boot(pilot: PilotKind, panel: &str, brief: &str) -> String {
    serde_json::to_string(&if pilot == PilotKind::Antigravity {
        json!({"injectSteps": [{"systemMessage": {"systemMessage": brief, "renderInfo": {"markdown": format!("```\n{}\n```", panel)}}}]})
    } else { json!({"systemMessage": panel, "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": brief}}) }).unwrap_or_default()
}
pub fn format_context(pilot: PilotKind, event: &str, text: Option<&str>) -> String {
    match (pilot, text.filter(|s| !s.trim().is_empty())) {
        (PilotKind::Antigravity, None) => "{}".into(),
        (PilotKind::Antigravity, Some(m)) => serde_json::to_string(&json!({"injectSteps": [{"systemMessage": {"systemMessage": m}}]})).unwrap_or_else(|_| "{}".into()),
        (_, None) => String::new(),
        (_, Some(m)) => serde_json::to_string(&json!({"hookSpecificOutput": {"hookEventName": event, "additionalContext": m}})).unwrap_or_default(),
    }
}

pub fn claude_hooks_json(cfg: &Config, bin: &str) -> Value {
    let root = util::posix_str(&cfg.root);
    json!({
        "PreToolUse": [hgrp(Some(CLAUDE_PRETOOL_MATCHER), mk_cmd(bin, &["gate", "pretool"], true), 30)],
        "PostToolUse": [hgrp(Some(CLAUDE_POSTTOOL_MATCHER), mk_cmd(bin, &["gate", "posttool"], true), 10)],
        "UserPromptSubmit": [hgrp(None, mk_cmd(bin, &["gate", "prompt"], true), 10)],
        "PreCompact": [hgrp(None, mk_cmd(bin, &["gate", "precompact"], true), 30)],
        "SessionStart": [hgrp(Some("compact"), mk_cmd(bin, &["gate", "precompact", "--emit"], true), 30), hgrp(Some("startup|resume|clear"), mk_cmd(bin, &["--root", &root, "status", "--emit"], true), 30)],
        "Stop": [hgrp(None, mk_cmd(bin, &["gate", "stop"], true), 20)]
    })
}
pub fn codex_hooks_json(cfg: &Config, bin: &str) -> Value {
    let root = util::posix_str(&cfg.root);
    json!({"hooks": {
        "PreToolUse": [hgrp(Some(CODEX_PRETOOL_MATCHER), mk_cmd(bin, &["gate", "pretool"], false), 30)],
        "PostToolUse": [hgrp(Some(CODEX_POSTTOOL_MATCHER), mk_cmd(bin, &["gate", "posttool"], false), 10)],
        "PreCompact": [hgrp(None, mk_cmd(bin, &["gate", "precompact"], false), 30)],
        "SessionStart": [hgrp(Some("startup|resume|clear"), mk_cmd(bin, &["--root", &root, "status", "--emit"], false), 30), hgrp(Some("compact"), mk_cmd(bin, &["gate", "precompact", "--emit"], false), 30)],
        "Stop": [hgrp(None, mk_cmd(bin, &["gate", "stop"], false), 20)]
    }})
}
pub fn antigravity_plugin_files(cfg: &Config, bin: &str) -> BTreeMap<String, Value> {
    let root = util::posix_str(&cfg.root);
    BTreeMap::from([
        (format!("{}/plugin.json", AGY_PLUGIN), json!({"name": "entryplug"})),
        (format!("{}/mcp_config.json", AGY_PLUGIN), json!({"mcpServers": {"entryplug": {"command": bin, "args": ["--root", root, "mcp"]}}})),
        (format!("{}/hooks.json", AGY_PLUGIN), json!({
            "sortie-lock": {"PreToolUse": [hgrp(Some(AGY_PRETOOL_MATCHER), mk_cmd(bin, &["gate", "pretool"], false), 30)]},
            "hot-index": {"PostToolUse": [hgrp(Some(AGY_POSTTOOL_MATCHER), mk_cmd(bin, &["gate", "posttool"], false), 10)]},
            "prompt-router": {"PreInvocation": [hgrp(None, mk_cmd(bin, &["gate", "prompt"], false), 10)]},
            "boot-panel": {"SessionStart": [{"type": "command", "command": mk_cmd(bin, &["--root", &root, "status", "--emit", "antigravity"], false), "timeout": 30}]}
        })),
    ])
}

pub fn codex_hook_hashes(hooks_json: &Path) -> Vec<(String, String)> {
    let Some(hooks) = std::fs::read_to_string(hooks_json).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()).and_then(|v| v.get("hooks").cloned()).and_then(|v| v.as_object().cloned()) else { return Vec::new() };
    let path_str = util::clean_path(hooks_json).to_string_lossy().to_string();
    let mut out = Vec::new();
    for (ev, groups) in &hooks {
        let snake = match ev.as_str() {
            "PreToolUse" => "pre_tool_use", "PermissionRequest" => "permission_request", "PostToolUse" => "post_tool_use",
            "PreCompact" => "pre_compact", "PostCompact" => "post_compact", "SessionStart" => "session_start", "SessionEnd" => "session_end",
            "UserPromptSubmit" => "user_prompt_submit", "SubagentStart" => "subagent_start", "SubagentStop" => "subagent_stop",
            "Stop" => "stop", "Interrupt" => "interrupt", o => o,
        }.to_lowercase();
        let (short, in_ctx) = (snake == "session_end" || snake == "interrupt", matches!(snake.as_str(), "pre_tool_use" | "post_tool_use" | "session_start" | "user_prompt_submit" | "subagent_start"));
        for (gi, g) in groups.as_array().into_iter().flatten().enumerate() {
            for (hi, h) in g.get("hooks").and_then(|v| v.as_array()).into_iter().flatten().enumerate() {
                let raw_t = h.get("timeout").and_then(|v| v.as_i64());
                let t = if short { raw_t.unwrap_or(1).clamp(1, 3) } else { raw_t.unwrap_or(600).max(1) };
                let mut hm = BTreeMap::from([("async", Value::Bool(h.get("async").and_then(|v| v.as_bool()).unwrap_or(false))), ("command", Value::String(h.get("command").and_then(|v| v.as_str()).unwrap_or("").into())), ("timeout", Value::Number(t.into())), ("type", Value::String("command".into()))]);
                if let Some(sm) = h.get("statusMessage").filter(|v| !v.is_null()) { hm.insert("statusMessage", sm.clone()); }
                if in_ctx { if let Some(l) = h.get("additionalContextLimit").filter(|v| !v.is_null() && v.as_i64() != Some(2500)) { hm.insert("additionalContextLimit", l.clone()); } }
                let mut obj = BTreeMap::from([("event_name", Value::String(snake.clone())), ("hooks", Value::Array(vec![serde_json::to_value(hm).unwrap()]))]);
                if let Some(m) = g.get("matcher").filter(|v| !v.is_null()) { obj.insert("matcher", m.clone()); }
                out.push((format!("{}:{}:{}:{}", path_str, snake, gi, hi), format!("sha256:{}", util::sha256_hex(serde_json::to_string(&obj).unwrap_or_default().as_bytes()))));
            }
        }
    }
    out
}

pub fn codex_config_path() -> PathBuf { std::env::var_os("CODEX_HOME").map(PathBuf::from).unwrap_or_else(|| util::home_dir().join(".codex")).join("config.toml") }

pub fn codex_trust_problem(cfg: &Config) -> Option<String> {
    let hooks = cfg.root.join(".codex").join("hooks.json");
    if !hooks.is_file() { return None; }
    let (conf, fix) = (codex_config_path(), "open an interactive `codex` in this repo once and trust the hooks on `Hooks need review`.");
    let doc: toml::Value = std::fs::read_to_string(&conf).ok().and_then(|r| toml::from_str(&r).ok())?;
    let mut state: BTreeMap<String, &toml::Table> = BTreeMap::new();
    for (k, v) in doc.get("hooks").and_then(|v| v.get("state")).and_then(|v| v.as_table()).into_iter().flatten() {
        if let Some(t) = v.as_table() { state.insert(k.to_lowercase().replace('\\', "/"), t); }
    }
    let want = codex_hook_hashes(&hooks);
    if want.is_empty() { return Some("Codex hooks.json has no hooks".into()); }
    let (mut off, mut bad) = (0, 0);
    for (k, h) in &want {
        match state.get(&k.to_lowercase().replace('\\', "/")) {
            Some(st) if st.get("enabled").and_then(|v| v.as_bool()) == Some(false) => off += 1,
            Some(st) if st.get("trusted_hash").and_then(|v| v.as_str()) == Some(h.as_str()) => {}
            _ => bad += 1,
        }
    }
    if off > 0 { Some(format!("{} of {} Codex hooks disabled in {}", off, want.len(), util::posix_str(&conf))) }
    else if bad > 0 { Some(format!("{} of {} Codex hooks untrusted/changed (skipped silently). {}", bad, want.len(), fix)) }
    else { None }
}

pub fn codex_posture() -> String {
    let conf = codex_config_path();
    let Some(doc) = std::fs::read_to_string(&conf).ok().and_then(|r| toml::from_str::<toml::Value>(&r).ok()) else { return format!("{} unreadable", util::posix_str(&conf)) };
    format!("approval_policy={} · sandbox_mode={}", doc.get("approval_policy").and_then(|v| v.as_str()).unwrap_or("unset"), doc.get("sandbox_mode").and_then(|v| v.as_str()).unwrap_or("unset"))
}

pub fn audit_pilot(cfg: &Config, pilot: PilotKind) -> PilotAudit {
    let (rel, ptr, matcher) = match pilot {
        PilotKind::ClaudeCode => (".claude/settings.json", "/hooks/PreToolUse", CLAUDE_PRETOOL_MATCHER),
        PilotKind::Codex => (".codex/hooks.json", "/hooks/PreToolUse", CODEX_PRETOOL_MATCHER),
        PilotKind::Antigravity => (".agents/plugins/entryplug/hooks.json", "/sortie-lock/PreToolUse", AGY_PRETOOL_MATCHER),
    };
    let p = cfg.root.join(rel);
    if !p.is_file() { return PilotAudit { pilot, installed: false, ok: true, issues: Vec::new() }; }
    let Some(val) = std::fs::read_to_string(&p).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()) else {
        return PilotAudit { pilot, installed: true, ok: false, issues: vec![format!("{} is invalid JSON", rel)] };
    };
    let mut issues = Vec::new();
    let matched = val.pointer(ptr).and_then(|v| v.as_array()).map(|arr| arr.iter().any(|g| {
        g.get("matcher").and_then(|v| v.as_str()) == Some(matcher)
            && g.get("hooks").and_then(|v| v.as_array()).map(|hs| hs.iter().any(|h| h.get("command").and_then(|c| c.as_str()).map(|s| s.contains("gate pretool")).unwrap_or(false))).unwrap_or(false)
    })).unwrap_or(false);
    if !matched { issues.push(format!("{} PreToolUse matcher or command drifted (run plug init --pilot {})", pilot.name(), pilot.name())); }
    match pilot {
        PilotKind::ClaudeCode => {
            let deny: Vec<&str> = val.pointer("/permissions/deny").and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|v| v.as_str()).collect()).unwrap_or_default();
            if let Some(miss) = deny_rules(cfg).into_iter().find(|r| !deny.contains(&r.as_str())) { issues.push(format!("Claude permissions.deny missing {}", miss)); }
        }
        PilotKind::Codex => {
            if !codex_config_path().is_file() { issues.push(format!("Codex config {} missing — open interactive codex once to trust hooks", util::posix_str(&codex_config_path()))); }
            else if let Some(prob) = codex_trust_problem(cfg) { issues.push(prob); }
        }
        PilotKind::Antigravity => {
            let cfg_p = std::env::var_os("PLUG_AGY_CONFIG").map(PathBuf::from).unwrap_or_else(|| util::home_dir().join(".gemini").join("config")).join("config.json");
            if std::fs::read_to_string(&cfg_p).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()).and_then(|v| v.pointer("/plugins/entryplug/enabled").and_then(|b| b.as_bool())) == Some(false) {
                issues.push(format!("entryplug plugin is disabled in {}", util::posix_str(&cfg_p)));
            }
            let rm = |p: &str, t: &str| Regex::new(p).map(|r| r.is_match(t)).unwrap_or(false);
            let bash: Vec<_> = cfg.outbound.iter().filter(|r| rm(&r.tool, "Bash")).collect();
            for t in ["run_command", "send_command_input"] { if !bash.is_empty() && !bash.iter().all(|r| rm(&r.tool, t)) { issues.push(format!("plug.yaml outbound shell rules missing {}", t)); } }
        }
    }
    PilotAudit { pilot, installed: true, ok: issues.is_empty(), issues }
}

pub fn precommit_path(root: &Path) -> PathBuf {
    let git_dir = std::fs::read_to_string(root.join(".git")).ok().and_then(|s| s.strip_prefix("gitdir:").map(|r| r.trim().to_string()))
        .map(|gd| { let p = PathBuf::from(gd); if p.is_absolute() { p } else { root.join(p) } }).unwrap_or_else(|| root.join(".git"));
    if let Ok(txt) = std::fs::read_to_string(git_dir.join("config")) {
        let mut in_core = false;
        for line in txt.lines().map(str::trim) {
            if line.starts_with('[') { in_core = line.eq_ignore_ascii_case("[core]"); }
            else if in_core {
                if let Some((k, v)) = line.split_once('=') {
                    if k.trim().eq_ignore_ascii_case("hookspath") {
                        let p = PathBuf::from(v.trim().trim_matches('"'));
                        return if p.is_absolute() { p.join("pre-commit") } else { root.join(p).join("pre-commit") };
                    }
                }
            }
        }
    }
    git_dir.join("hooks").join("pre-commit")
}
pub fn precommit_hook_ok(hook: &Path) -> bool { std::fs::read_to_string(hook).map(|t| t.contains("gate precommit")).unwrap_or(false) }
