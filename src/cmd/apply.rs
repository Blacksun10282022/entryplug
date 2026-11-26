use crate::cmd::{check, init};
use crate::config::{self, Config};
use crate::domain::diff::{self, ProposalPatch};
use crate::domain::shapes;
use crate::store::index;
use crate::util;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

const AGENT_ENV: &[&str] = &["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_SESSION_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_THREAD_ID", "CURSOR_AGENT", "AIDER_CHAT", "ANTIGRAVITY_AGENT", "ANTIGRAVITY_CONVERSATION_ID"];

fn owner_refusal(proposal: &str, owner: bool) -> Option<String> {
    if owner || std::env::var("PLUG_OWNER").ok().as_deref() == Some("1") { return None; }
    let seen: Vec<&str> = AGENT_ENV.iter().copied().filter(|k| std::env::var(k).map(|v| !v.is_empty()).unwrap_or(false)).collect();
    (!seen.is_empty()).then(|| format!(
        "apply: agent environment detected ({}) — approving or rejecting is the owner's move.\n  in a terminal:  plug apply {}\n  from the chat:  ! plug apply {} --owner\n  look first:     plug apply {} --dry-run",
        seen.join(", "), proposal, proposal, proposal
    ))
}

fn new_errors(before: &[check::Finding], after: &[check::Finding]) -> Vec<check::Finding> {
    let mut counts: HashMap<(String, String, String), usize> = HashMap::new();
    for e in before { *counts.entry((e.code.clone(), e.file.clone(), e.msg.clone())).or_insert(0) += 1; }
    let mut out = Vec::new();
    for e in after {
        let k = (e.code.clone(), e.file.clone(), e.msg.clone());
        if let Some(c) = counts.get_mut(&k).filter(|c| **c > 0) {
            *c -= 1;
            if e.code != "shape_version" { continue; }
        }
        out.push(e.clone());
    }
    out
}

pub fn run(cfg: &Config, proposal: &str, reject: Option<&str>, dry_run: bool, owner: bool) -> i32 {
    let ppath = if Path::new(proposal).is_absolute() { Path::new(proposal).to_path_buf() } else { cfg.root.join(proposal) };
    if !ppath.is_file() { println!("apply: no such proposal {}", proposal); return 1; }
    if !dry_run { if let Some(r) = owner_refusal(proposal, owner) { println!("{}", r); return 1; } }
    let prel = cfg.rel(&ppath);
    if let Some(reason) = reject {
        let rdir = cfg.proposals_dir().join("rejected");
        let _ = fs::create_dir_all(&rdir);
        let dst = util::unique_dest(&rdir, ppath.file_name().and_then(|s| s.to_str()).unwrap_or("rejected.md"));
        let next = format!("{}\n\nrejected: {} · {}\n", fs::read_to_string(&ppath).unwrap_or_default().trim_end(), util::today_iso(), reason);
        if let Err(e) = util::write_lf(&dst, &next) { eprintln!("apply: {}", e); return 1; }
        let _ = fs::remove_file(&ppath);
        let _ = index::build(cfg, false, false);
        println!("rejected → {}", cfg.rel(&dst));
        return 0;
    }

    let raw = match fs::read_to_string(&ppath) { Ok(s) => s, Err(e) => { println!("apply: read failed: {}", e); return 1; } };
    let parsed = diff::parse_proposal(&raw);
    if !parsed.errors.is_empty() { println!("apply: proposal is out of shape: {}", parsed.errors.join("; ")); return 1; }
    let target_raw = shapes::fm_str(&parsed.fm, "target");
    let Some(trel) = config::canonical_rel_inside(&cfg.root, &target_raw).filter(|r| !r.is_empty() && !r.split('/').any(|s| s == ".git")) else { println!("apply: target must be a valid non-.git file inside the repo: {}", target_raw); return 1; };
    let (target, base) = (cfg.root.join(&trel), shapes::fm_str(&parsed.fm, "base"));
    if target.is_dir() { println!("apply: target is a directory: {}", trel); return 1; }
    let current = fs::read(&target).ok();
    if current.is_none() && base != "new" && base != "-" { println!("apply: target {} does not exist but base is {} (new file needs `base: new`) → refused", trel, base); return 1; }
    if let Some(bytes) = &current { let h = util::blob_short_hash(bytes); if h != base { println!("apply: base mismatch — proposal {}, {} is now {} → refused, nothing overwritten", base, trel, h); return 1; } }

    let (action, new_content): (&str, Option<String>) = match &parsed.patch.unwrap() {
        ProposalPatch::Retire => { if current.is_none() { println!("apply: target to retire does not exist: {}", trel); return 1; } ("retire", None) }
        ProposalPatch::FullText(txt) => (if current.is_none() { "add" } else { "replace" }, Some(txt.clone())),
        ProposalPatch::UnifiedDiff(ud) => {
            let Some(bytes) = &current else { println!("apply: unified diff requires existing target (use `base: new` full block for new files)"); return 1; };
            match diff::apply_unified_diff(&String::from_utf8_lossy(bytes), ud) { Ok(p) => ("replace", Some(p)), Err(e) => { println!("apply: unified diff failed ({}) → refused, nothing overwritten", e); return 1; } }
        }
    };

    let retire_dest = target.parent().unwrap_or(&cfg.root).join("retired").join(target.file_name().unwrap_or_default());
    if action == "retire" { println!("retire: {} → {}", trel, cfg.rel(&retire_dest)); }
    else if let Some(ref nc) = new_content { println!("{}", diff::render_unified_diff(&current.as_deref().map(|b| String::from_utf8_lossy(b).to_string()).unwrap_or_default(), nc, &trel)); }
    if dry_run { return 0; }

    let before = check::check_repo(cfg, false, true, false);
    let rollback = || { if action == "retire" { let _ = fs::rename(&retire_dest, &target); } else if let Some(b) = &current { let _ = fs::write(&target, b); } else { let _ = fs::remove_file(&target); } };
    if action == "retire" {
        if let Some(p) = retire_dest.parent() { let _ = fs::create_dir_all(p); }
        if let Err(e) = fs::rename(&target, &retire_dest) { println!("apply: move failed: {}", e); return 1; }
    } else if let Some(ref nc) = new_content { if let Err(e) = util::write_lf(&target, nc) { println!("apply: write failed: {}", e); return 1; } }

    let next_cfg = if trel.eq_ignore_ascii_case("plug.yaml") { match config::load(&cfg.root) { Ok(c) => c, Err(e) => { rollback(); println!("apply: invalid plug.yaml ({}), rolled back", e); return 1; } } } else { cfg.clone() };
    let introduced = new_errors(&before.errors, &check::check_repo(&next_cfg, false, true, false).errors);
    if !introduced.is_empty() { rollback(); println!("apply: check found ERRORs this change introduces, rolled back:\n{}", check::format_findings(&introduced, &[])); return 1; }

    let applied_dst = next_cfg.proposals_dir().join("applied").join(ppath.file_name().unwrap_or_default());
    let _ = fs::create_dir_all(applied_dst.parent().unwrap());
    if let Err(e) = fs::rename(&ppath, &applied_dst) { rollback(); println!("apply: move proposal failed ({}), rolled back", e); return 1; }
    let (psha, applied_rel) = (util::sha256_hex(raw.as_bytes())[..12].to_string(), next_cfg.rel(&applied_dst));
    let mut paths = vec![trel.clone(), prel.clone(), applied_rel.clone()];
    if action == "retire" { paths.push(next_cfg.rel(&retire_dest)); }
    let synced = if trel.eq_ignore_ascii_case("plug.yaml") { init::sync_installed_pilots(&next_cfg) } else { Vec::new() };
    for (st, sp) in &synced { if matches!(st.as_str(), "written" | "updated") && !sp.starts_with(".git") { paths.push(sp.clone()); } }
    if util::git_ro(&next_cfg.root, &["rev-parse", "--git-dir"]).is_some() {
        let env = [("KB_APPROVE", "1")];
        for p in &paths { let _ = util::git_run(&next_cfg.root, &["add", "-A", "--", p], &env, &[]); }
        let mut da = vec!["diff", "--cached", "--name-only", "-z", "--no-renames", "--"]; da.extend(paths.iter().map(String::as_str));
        let staged: Vec<String> = util::git_ro(&next_cfg.root, &da).unwrap_or_default().split('\0').map(str::trim).filter(|s| !s.is_empty()).map(String::from).collect();
        if !staged.is_empty() {
            let msg = format!("apply: {} {}\n\nProposal: {}\nProposal-Sha: {}\n", action, trel, prel, psha);
            let mut ca = vec!["commit", "-q", "--only", "-m", &msg, "--"]; ca.extend(staged.iter().map(String::as_str));
            let ok = util::git_run(&next_cfg.root, &ca, &env, &[]);
            if !matches!(&ok, Ok(o) if o.status.success()) {
                let _ = fs::rename(&applied_dst, &ppath); rollback(); let _ = util::git_run(&next_cfg.root, &["reset", "-q", "HEAD", "--"], &[], &[]);
                let detail = ok.map(|o| format!("{}{}", String::from_utf8_lossy(&o.stderr), String::from_utf8_lossy(&o.stdout))).unwrap_or_else(|e| e.to_string());
                println!("apply: commit failed, rolled back cleanly: {}", detail.trim()); return 1;
            }
        }
    }
    let _ = index::build(&next_cfg, false, false);
    if !synced.is_empty() { println!("apply: plug.yaml changed → auto-synced & committed pilot wiring ({} item(s))", synced.len()); for (st, msg) in &synced { if st == "RE-TRUST" { println!("apply: {} {}", st, msg); } } }
    println!("landed and committed: {} {} · proposal → {} · Proposal-Sha {}", action, trel, applied_rel, psha);
    0
}
