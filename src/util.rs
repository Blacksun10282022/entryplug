use chrono::{Local, NaiveDate};
use sha1::{Digest, Sha1};
use sha2::Sha256;
use std::collections::HashMap;
use std::io::{self, IsTerminal, Read};
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Output};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

pub fn now_iso() -> String { Local::now().format("%Y-%m-%dT%H:%M:%S").to_string() }
pub fn now_hm() -> String { Local::now().format("%Y-%m-%d %H:%M").to_string() }
pub fn today() -> NaiveDate { Local::now().date_naive() }
pub fn today_iso() -> String { today().format("%Y-%m-%d").to_string() }

pub fn sha1_hex(data: &[u8]) -> String { hex::encode(Sha1::digest(data)) }
pub fn sha256_hex(data: &[u8]) -> String { hex::encode(Sha256::digest(data)) }

pub fn blob_short_hash(data: &[u8]) -> String {
    let mut h = Sha1::new();
    h.update(format!("blob {}\0", data.len()).as_bytes());
    h.update(data);
    hex::encode(h.finalize())[..8].to_string()
}

pub fn clean_path(p: &Path) -> PathBuf {
    let s = p.to_string_lossy();
    if let Some(r) = s.strip_prefix(r"\\?\UNC\") { PathBuf::from(format!(r"\\{}", r)) }
    else if let Some(r) = s.strip_prefix(r"\\?\") { PathBuf::from(r) }
    else { p.to_path_buf() }
}

pub fn posix_str(p: &Path) -> String { clean_path(p).to_string_lossy().replace('\\', "/") }

pub fn normalize_lexical(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in clean_path(p).components() {
        match c {
            Component::CurDir => {}
            Component::ParentDir if matches!(out.components().next_back(), Some(Component::Normal(_))) => { out.pop(); }
            other => out.push(other),
        }
    }
    out
}

pub fn resolve_existing_or_lexical(p: &Path) -> PathBuf {
    if let Ok(c) = std::fs::canonicalize(p) { return clean_path(&c); }
    let norm = normalize_lexical(p);
    let mut tail = Vec::new();
    let mut cur = norm.as_path();
    while !cur.exists() {
        let Some(name) = cur.file_name() else { break };
        tail.push(name.to_os_string());
        let Some(parent) = cur.parent() else { break };
        cur = parent;
    }
    let mut base = std::fs::canonicalize(cur).map(|c| clean_path(&c)).unwrap_or_else(|_| cur.to_path_buf());
    for seg in tail.into_iter().rev() { base.push(seg); }
    normalize_lexical(&base)
}

pub fn home_dir() -> PathBuf {
    std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."))
}

pub fn expand_tilde(s: &str) -> PathBuf {
    if let Some(r) = s.strip_prefix("~/").or_else(|| s.strip_prefix("~\\")) { home_dir().join(r) }
    else if s == "~" { home_dir() }
    else { PathBuf::from(s) }
}

pub fn read_stdin_if_piped() -> String {
    if io::stdin().is_terminal() { return String::new(); }
    let mut buf = String::new();
    let _ = io::stdin().read_to_string(&mut buf);
    buf
}

pub fn stamp_hook(hooks_dir: &Path, name: &str) {
    let _ = std::fs::create_dir_all(hooks_dir);
    let _ = std::fs::write(hooks_dir.join(name), format!("{}\n", now_iso()));
}

pub fn git_run(cwd: &Path, args: &[&str], extra_env: &[(&str, &str)], drop_env: &[&str]) -> io::Result<Output> {
    let mut cmd = Command::new("git");
    cmd.args(args).current_dir(cwd);
    for k in drop_env { cmd.env_remove(k); }
    for (k, v) in extra_env { cmd.env(k, v); }
    cmd.output()
}

pub fn git_ro(cwd: &Path, args: &[&str]) -> Option<String> {
    let out = git_run(cwd, args, &[("GIT_OPTIONAL_LOCKS", "0")], &[]).ok()?;
    out.status.success().then(|| String::from_utf8_lossy(&out.stdout).to_string())
}

pub fn git_first_dates(root: &Path) -> HashMap<String, NaiveDate> {
    let mut dates = HashMap::new();
    let Some(raw) = git_ro(root, &["-c", "core.quotePath=false", "log", "--diff-filter=A", "--format=COMMIT %cs", "--name-only", "-z"]) else { return dates };
    let mut cur_day: Option<NaiveDate> = None;
    for chunk in raw.split('\0') {
        for line in chunk.lines().map(str::trim).filter(|l| !l.is_empty()) {
            if let Some(d) = line.strip_prefix("COMMIT ") {
                cur_day = NaiveDate::parse_from_str(d.trim(), "%Y-%m-%d").ok();
            } else if let Some(d) = cur_day {
                dates.entry(line.replace('\\', "/")).or_insert(d);
            }
        }
    }
    dates
}

pub fn write_lf(path: &Path, content: &str) -> io::Result<()> {
    if let Some(p) = path.parent() { std::fs::create_dir_all(p)?; }
    std::fs::write(path, content.replace("\r\n", "\n").as_bytes())
}

pub fn unique_dest(dir: &Path, name: &str) -> PathBuf {
    let cand = dir.join(name);
    if !cand.exists() { return cand; }
    let stem = Path::new(name).file_stem().and_then(|s| s.to_str()).unwrap_or(name);
    let ext = Path::new(name).extension().and_then(|s| s.to_str()).map(|e| format!(".{}", e)).unwrap_or_default();
    (2..1000).map(|i| dir.join(format!("{}-{}{}", stem, i, ext))).find(|p| !p.exists())
        .unwrap_or_else(|| dir.join(format!("{}-{}{}", stem, now_iso().replace(':', ""), ext)))
}
