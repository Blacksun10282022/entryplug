use regex::Regex;
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo_root() -> PathBuf { PathBuf::from(env!("CARGO_MANIFEST_DIR")) }

fn git_files(root: &Path) -> Vec<String> {
    let out = Command::new("git")
        .args(["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
        .current_dir(root).output().expect("git ls-files");
    String::from_utf8_lossy(&out.stdout).split('\0').filter(|s| !s.is_empty() && root.join(s).is_file()).map(String::from).collect()
}

fn collect_rs(dir: &Path, out: &mut Vec<PathBuf>) {
    for ent in fs::read_dir(dir).into_iter().flatten().flatten() {
        let p = ent.path();
        if p.is_dir() { collect_rs(&p, out); }
        else if p.extension().and_then(|s| s.to_str()) == Some("rs") { out.push(p); }
    }
}

#[test]
fn ratchet_forbidden_symbols_absent_in_src() {
    let forbidden = [
        "PLUG_NO_NATIVE",
        "fast_bin",
        "plug-fast",
        "jieba",
        "fancy_regex",
        "select count(distinct doc) from fts",
        "delete from fts where file",
    ];
    let mut files = Vec::new();
    collect_rs(&repo_root().join("src"), &mut files);
    assert!(!files.is_empty());
    let mut hits = Vec::new();
    for p in files {
        let low = fs::read_to_string(&p).unwrap_or_default().to_lowercase();
        for pat in &forbidden {
            if low.contains(&pat.to_lowercase()) {
                hits.push(format!("{}: contains forbidden symbol '{}'", p.display(), pat));
            }
        }
    }
    assert!(hits.is_empty(), "forbidden symbols found:\n{}", hits.join("\n"));
}

#[test]
fn ratchet_production_src_loc_under_3400() {
    let mut files = Vec::new();
    collect_rs(&repo_root().join("src"), &mut files);
    let mut code_lines = 0usize;
    for p in files {
        let txt = fs::read_to_string(&p).unwrap_or_default();
        code_lines += txt.lines().filter(|l| { let t = l.trim(); !t.is_empty() && !t.starts_with("//") }).count();
    }
    assert!(code_lines <= 3400, "production src code LOC {} exceeded 3,400 ratchet", code_lines);
}

#[test]
fn no_leak_public_repo_hygiene() {
    let root = repo_root();
    let files = git_files(&root);
    let text_exts: HashSet<&str> = ["rs", "py", "md", "yaml", "yml", "json", "toml", "txt", "cfg", "ini", ""].into_iter().collect();
    let re_user_path = Regex::new(r"[A-Za-z]:[\\/]+Users[\\/]+[^<\\\s/]|/[cC]/Users/[^<\s/]|/home/[a-z]\w+/|/Users/[a-z]\w+/").unwrap();
    let re_secrets = [
        Regex::new(r"sk-[A-Za-z0-9]{20,}").unwrap(),
        Regex::new(r"AKIA[0-9A-Z]{16}").unwrap(),
        Regex::new(r"-----BEGIN [A-Z ]*PRIVATE KEY").unwrap(),
        Regex::new(r"ghp_[A-Za-z0-9]{30,}").unwrap(),
        Regex::new(r"(?i)\bcookie\s*[:=]\s*[A-Za-z0-9%=;_\-]{24,}").unwrap(),
        Regex::new(r"(?i)\bbearer\s+[A-Za-z0-9\-_\.]{24,}").unwrap(),
    ];
    let re_bv = Regex::new(r"BV1[0-9A-Za-z]{9}").unwrap();
    let re_forbidden_dir = Regex::new(r"(^|/)(records|proposals|materials|corpus|self)/").unwrap();

    for rel in &files {
        if !rel.starts_with("example-tool/") {
            assert!(!re_forbidden_dir.is_match(rel) && !rel.ends_with(".sqlite"), "private dir or sqlite outside example-tool: {}", rel);
        }
        let p = root.join(rel);
        let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
        if !text_exts.contains(ext.as_str()) { continue; }
        let txt = fs::read_to_string(&p).unwrap_or_default();
        assert!(!re_user_path.is_match(&txt), "user absolute path leaked in {}", rel);
        if !rel.starts_with("tests/") {
            for rx in &re_secrets {
                assert!(!rx.is_match(&txt), "secret pattern leaked in {}", rel);
            }
        }
        if !rel.starts_with("example-tool/") {
            for m in re_bv.find_iter(&txt) {
                assert_eq!(m.as_str(), "BV1EXAMPLE01", "real BV id leaked in {}: {}", rel, m.as_str());
            }
        }
        if !rel.starts_with("example-tool/") && !rel.starts_with("docs/") {
            let cjk = txt.chars().filter(|c| ('\u{4E00}'..='\u{9FFF}').contains(c)).count();
            assert!(cjk <= 20_000, "long Chinese text ({} chars) in {}", cjk, rel);
        }
        if rel.ends_with("plug.yaml") {
            assert!(rel.starts_with("example-tool/"), "sample plug.yaml outside example-tool: {}", rel);
        }
    }

    // Layer 2: owner private leak term list if present on machine (never committed)
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from);
    if let Some(lp) = home.map(|h| h.join(".kb").join("leak_terms.txt")).filter(|p| p.is_file()) {
        let terms: Vec<String> = fs::read_to_string(lp).unwrap_or_default().lines().map(str::trim).filter(|l| !l.is_empty() && !l.starts_with('#')).map(String::from).collect();
        for rel in &files {
            let p = root.join(rel);
            let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
            if !text_exts.contains(ext.as_str()) { continue; }
            let txt = fs::read_to_string(&p).unwrap_or_default();
            for t in &terms {
                assert!(!txt.contains(t.as_str()), "private leak term found in {}", rel);
            }
        }
    }
}
