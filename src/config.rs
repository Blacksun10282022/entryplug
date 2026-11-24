use crate::util;
use regex::Regex;
use serde::Deserialize;
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

pub const SUPPORTED_SHAPES: &[i64] = &[1, 2];

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ToolDecl {
    pub name: String, #[serde(default)] pub path: String, #[serde(skip)] pub dir: PathBuf,
    #[serde(default)] pub depends: Vec<String>, #[serde(default)] pub ttl_days: HashMap<String, i64>,
    #[serde(default)] pub unreviewed: Option<usize>, #[serde(default)] pub outcome_days: Option<i64>,
}
#[derive(Debug, Clone)] pub struct CorpusDecl { pub path: String, pub sub: String, pub tool: String }
#[derive(Debug, Clone, Deserialize, Default)] pub struct PilotSkills { #[serde(default)] pub skills: String, #[serde(default)] pub user_skills: String }
#[derive(Debug, Clone, Deserialize)] pub struct OutboundRule { pub tool: String, #[serde(rename = "match", default)] pub match_re: String }
#[derive(Debug, Clone, Deserialize)] pub struct PromptHint { pub id: String, pub pattern: String, pub hint: String, #[serde(default = "d_cool")] pub cooldown_hours: f64 }
#[derive(Debug, Clone)] pub struct Policy { pub protected: Vec<String>, pub unprotected: Vec<String>, pub protect: Vec<String>, pub tools: Vec<(String, String)> }
#[derive(Debug, Clone)] pub struct WalkFile { pub path: PathBuf, pub rel: String, pub area: String, pub sub: String, pub tool: String, pub mtime_ns: i64, pub size: i64 }

fn d_cool() -> f64 { 3.0 }
pub fn default_protected() -> Vec<String> { ["self/RULES.md", "self/facts/**", "self/style.md", "tools/**", "plug.yaml"].map(String::from).into() }
pub fn default_unprotected() -> Vec<String> { ["**/corpus/**", "work/**", "workshop/**"].map(String::from).into() }
pub fn default_pilots() -> BTreeMap<String, PilotSkills> {
    BTreeMap::from([
        ("claude-code".into(), PilotSkills { skills: ".claude/skills".into(), user_skills: "~/.claude/skills".into() }),
        ("codex".into(), PilotSkills { skills: ".agents/skills".into(), user_skills: "~/.agents/skills".into() }),
        ("antigravity".into(), PilotSkills { skills: ".agents/skills".into(), user_skills: "~/.gemini/config/skills".into() }),
    ])
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct Config {
    #[serde(skip)] pub root: PathBuf, #[serde(rename = "machine")] pub machine_pin: String, pub shape_version: i64,
    #[serde(rename = "self")] pub self_rel: String, #[serde(rename = "proposals")] pub proposals_rel: String,
    #[serde(rename = "index")] pub index_rel: String, #[serde(rename = "books_index")] pub books_index_rel: String,
    #[serde(rename = "index_md")] pub index_md_rel: String, #[serde(rename = "numbers")] pub numbers_rel: String,
    #[serde(rename = "hooks")] pub hooks_rel: String, #[serde(rename = "pin")] pub pin_rel: String,
    #[serde(rename = "memory")] pub memory_rel: String, #[serde(rename = "logs")] pub logs_rel: Option<String>,
    pub language: String, pub tools: Vec<ToolDecl>,
    #[serde(rename = "corpus")] raw_corpus: Option<serde_yaml::Value>, #[serde(rename = "books")] raw_books: Option<serde_yaml::Value>, #[serde(rename = "aliases")] raw_aliases: Option<serde_yaml::Value>,
    #[serde(skip)] pub corpus: Vec<CorpusDecl>, #[serde(skip)] pub books: Vec<CorpusDecl>,
    #[serde(skip)] pub aliases_paths: Vec<String>, #[serde(skip)] pub inline_aliases: HashMap<String, Vec<String>>,
    pub pilots: BTreeMap<String, PilotSkills>, pub outbound: Vec<OutboundRule>,
    pub protected: Vec<String>, pub unprotected: Vec<String>, pub protect: Vec<String>,
    exclude: Vec<String>, #[serde(skip)] pub exclude_res: Vec<Regex>, pub prompt_hints: Vec<PromptHint>,
    pub review_interval_days: i64, pub topic_pulse_sessions: i64, pub topic_pulse_fragments: i64, pub outcome_days: i64,
}

fn parse_corpus_val(val: Option<&serde_yaml::Value>, def_sub: &str) -> Vec<CorpusDecl> {
    let mut out = Vec::new();
    match val {
        Some(serde_yaml::Value::String(s)) => out.push(CorpusDecl { path: s.clone(), sub: def_sub.into(), tool: String::new() }),
        Some(serde_yaml::Value::Sequence(seq)) => for it in seq {
            if let Some(s) = it.as_str() { out.push(CorpusDecl { path: s.into(), sub: def_sub.into(), tool: String::new() }); }
            else if let Some(m) = it.as_mapping() {
                let gs = |k: &str| m.get(serde_yaml::Value::String(k.into())).and_then(|x| x.as_str()).map(String::from);
                if let Some(p) = gs("path") {
                    let sub = gs("sub").or_else(|| gs("kind")).unwrap_or_else(|| if p.contains("clean") { "clean".into() } else if p.contains("raw") { "raw".into() } else { def_sub.into() });
                    out.push(CorpusDecl { path: p, sub, tool: gs("tool").unwrap_or_default() });
                }
            }
        },
        Some(serde_yaml::Value::Mapping(m)) => for (k, v) in m {
            if let (Some(sub), Some(p)) = (k.as_str(), v.as_str()) { out.push(CorpusDecl { path: p.into(), sub: sub.into(), tool: String::new() }); }
        },
        _ => {}
    }
    out
}

pub fn find_root(start: Option<&Path>) -> Result<PathBuf, String> {
    let base = match start { Some(p) if !p.as_os_str().is_empty() => util::resolve_existing_or_lexical(p), _ => std::env::current_dir().map_err(|e| e.to_string())? };
    let mut cur = if base.is_file() { base.parent().unwrap_or(&base).to_path_buf() } else { base };
    loop {
        if cur.join("plug.yaml").is_file() { return Ok(util::clean_path(&cur)); }
        if !cur.pop() { return Err("plug.yaml not found in this directory or any parent".into()); }
    }
}

fn fill_defaults(cfg: &mut Config, root: PathBuf) {
    let dstr = |s: &mut String, v: &str| if s.is_empty() { *s = v.into(); };
    cfg.root = root.clone();
    dstr(&mut cfg.machine_pin, &format!("entryplug {}", util::VERSION));
    if cfg.shape_version == 0 { cfg.shape_version = 1; }
    dstr(&mut cfg.self_rel, "self"); dstr(&mut cfg.proposals_rel, "proposals");
    dstr(&mut cfg.index_rel, ".kb/state.sqlite"); dstr(&mut cfg.books_index_rel, ".kb/books.sqlite");
    dstr(&mut cfg.index_md_rel, "index.md"); dstr(&mut cfg.numbers_rel, "self/数字.md");
    dstr(&mut cfg.hooks_rel, ".kb/hooks"); dstr(&mut cfg.pin_rel, ".kb/pin.md");
    dstr(&mut cfg.memory_rel, &format!("{}/memory", cfg.self_rel)); dstr(&mut cfg.language, "中文");
    if cfg.pilots.is_empty() { cfg.pilots = default_pilots(); }
    if cfg.protected.is_empty() { cfg.protected = default_protected(); }
    if cfg.unprotected.is_empty() { cfg.unprotected = default_unprotected(); }
    if cfg.review_interval_days == 0 { cfg.review_interval_days = 7; }
    if cfg.topic_pulse_sessions == 0 { cfg.topic_pulse_sessions = 5; }
    if cfg.topic_pulse_fragments == 0 { cfg.topic_pulse_fragments = 4; }
    if cfg.outcome_days == 0 { cfg.outcome_days = 30; }
    for t in &mut cfg.tools { if t.path.is_empty() { t.path = format!("tools/{}", t.name); } t.dir = root.join(&t.path); }
}

pub fn load(root: &Path) -> Result<Config, String> {
    let root = util::resolve_existing_or_lexical(root);
    let raw = std::fs::read_to_string(root.join("plug.yaml")).map_err(|_| format!("plug.yaml not found at {}", util::posix_str(&root)))?;
    let mut cfg: Config = serde_yaml::from_str(&raw).map_err(|e| format!("invalid plug.yaml: {}", e))?;
    fill_defaults(&mut cfg, root.clone());
    cfg.corpus = parse_corpus_val(cfg.raw_corpus.as_ref(), "clean");
    for t in &cfg.tools {
        for sub in ["clean", "raw", ""] {
            let rel = if sub.is_empty() { format!("{}/corpus", t.path) } else { format!("{}/corpus/{}", t.path, sub) };
            let dir = root.join(&rel);
            if dir.is_dir() && !cfg.corpus.iter().any(|c| c.path == rel) && !(sub.is_empty() && (dir.join("clean").is_dir() || dir.join("raw").is_dir())) {
                cfg.corpus.push(CorpusDecl { path: rel, sub: if sub.is_empty() { "clean".into() } else { sub.into() }, tool: t.name.clone() });
            }
        }
    }
    cfg.books = parse_corpus_val(cfg.raw_books.as_ref(), "books");
    match cfg.raw_aliases.as_ref() {
        Some(serde_yaml::Value::String(s)) => cfg.aliases_paths.push(s.clone()),
        Some(serde_yaml::Value::Sequence(seq)) => cfg.aliases_paths.extend(seq.iter().filter_map(|x| x.as_str().map(String::from))),
        Some(serde_yaml::Value::Mapping(m)) => for (k, v) in m {
            if let Some(ks) = k.as_str() {
                let vs: Vec<String> = v.as_sequence().map(|s| s.iter().filter_map(|x| x.as_str().map(String::from)).collect()).or_else(|| v.as_str().map(|s| vec![s.into()])).unwrap_or_default();
                if !vs.is_empty() { cfg.inline_aliases.insert(ks.into(), vs); }
            }
        },
        _ => {}
    }
    cfg.exclude_res = cfg.exclude.iter().filter_map(|p| compile_glob(p)).collect();
    Ok(cfg)
}

impl Config {
    pub fn self_dir(&self) -> PathBuf { self.root.join(&self.self_rel) }
    pub fn records_dir(&self) -> PathBuf { self.self_dir().join("records") }
    pub fn memory_dir(&self) -> PathBuf { self.root.join(&self.memory_rel) }
    pub fn proposals_dir(&self) -> PathBuf { self.root.join(&self.proposals_rel) }
    pub fn index_path(&self) -> PathBuf { self.root.join(&self.index_rel) }
    pub fn books_index_path(&self) -> PathBuf { self.root.join(&self.books_index_rel) }
    pub fn index_md_path(&self) -> PathBuf { self.root.join(&self.index_md_rel) }
    pub fn numbers_path(&self) -> PathBuf { self.root.join(&self.numbers_rel) }
    pub fn hooks_dir(&self) -> PathBuf { self.root.join(&self.hooks_rel) }
    pub fn pin_path(&self) -> PathBuf { self.root.join(&self.pin_rel) }
    pub fn kb_dir(&self) -> PathBuf { self.index_path().parent().unwrap_or(&self.root).to_path_buf() }
    pub fn logs_dir(&self) -> Option<PathBuf> { self.logs_rel.as_ref().map(|r| util::resolve_existing_or_lexical(&self.root.join(r))) }
    pub fn plug_off(&self) -> bool { self.root.join(".plug-off").exists() }
    pub fn shape_ok(&self) -> bool { SUPPORTED_SHAPES.contains(&self.shape_version) }
    pub fn machine_ok(&self) -> bool { let p = self.machine_pin.split_whitespace().last().unwrap_or(""); p.is_empty() || p == util::VERSION || p == "0.1.0" }
    pub fn rel(&self, p: &Path) -> String {
        if let Ok(r) = p.strip_prefix(&self.root) { return util::posix_str(r); }
        let abs = util::resolve_existing_or_lexical(p);
        if let Ok(r) = abs.strip_prefix(&self.root) { return util::posix_str(r); }
        let (rs, ps) = (util::posix_str(&self.root), util::posix_str(&abs));
        if cfg!(windows) && ps.to_lowercase().starts_with(&(rs.to_lowercase() + "/")) { ps[rs.len() + 1..].into() } else { ps }
    }
    pub fn policy(&self) -> Policy { Policy { protected: self.protected.clone(), unprotected: self.unprotected.clone(), protect: self.protect.clone(), tools: self.tools.iter().map(|t| (t.name.clone(), t.path.trim_matches('/').replace('\\', "/"))).collect() } }
    pub fn head_policy(&self) -> (Policy, bool) {
        let Some(mut hc) = util::git_ro(&self.root, &["show", "HEAD:plug.yaml"]).and_then(|r| serde_yaml::from_str::<Config>(&r).ok()) else { return (self.policy(), false) };
        fill_defaults(&mut hc, self.root.clone()); (hc.policy(), true)
    }
    pub fn is_excluded(&self, rel: &str) -> bool { let t = rel.replace('\\', "/"); self.exclude_res.iter().any(|r| r.is_match(t.trim_start_matches("./"))) }
}

pub fn compile_glob(pattern: &str) -> Option<Regex> {
    let pat = pattern.replace('\\', "/").trim_start_matches("./").to_string();
    let (mut re, b, mut i) = (String::from(if cfg!(windows) { "(?i)^" } else { "^" }), pat.as_bytes(), 0);
    while i < b.len() {
        if i + 2 < b.len() && &b[i..i + 3] == b"**/" { re.push_str("(?:.*/)?"); i += 3; }
        else if i + 1 < b.len() && &b[i..i + 2] == b"**" { re.push_str(".*"); i += 2; }
        else if b[i] == b'*' { re.push_str("[^/]*"); i += 1; }
        else if b[i] == b'?' { re.push_str("[^/]"); i += 1; }
        else { let ch = pat[i..].chars().next().unwrap(); re.push_str(&regex::escape(&ch.to_string())); i += ch.len_utf8(); }
    }
    re.push('$');
    Regex::new(&re).ok()
}
pub fn glob_match(pattern: &str, text: &str) -> bool { compile_glob(pattern).map(|r| r.is_match(text.replace('\\', "/").trim_start_matches("./"))).unwrap_or(false) }

pub fn is_protected(policy: &Policy, rel: &str) -> bool {
    let rp = rel.replace('\\', "/"); let rp = rp.trim_start_matches("./");
    if policy.unprotected.iter().any(|p| glob_match(p, rp)) { return false; }
    if policy.protect.iter().any(|p| glob_match(p, rp)) { return true; }
    policy.protected.iter().any(|pat| if pat == "tools/**" { policy.tools.iter().any(|(_, tp)| glob_match(&format!("{}/**", tp), rp) || glob_match(tp, rp)) } else { glob_match(pat, rp) })
}

pub fn canonical_rel_inside(root: &Path, candidate: &str) -> Option<String> {
    let raw = candidate.trim().trim_matches(&['"', '\''][..]);
    if raw.is_empty() { return None; }
    let norm = if raw.starts_with("//") && raw.len() >= 4 && raw.as_bytes()[2].is_ascii_alphabetic() && raw.as_bytes()[3] == b'/' { format!("{}:/{}", raw.as_bytes()[2] as char, &raw[4..]) } else { raw.into() };
    let p = PathBuf::from(&norm);
    let abs = util::resolve_existing_or_lexical(&if p.is_absolute() { p } else { root.join(&p) });
    let (rs, a) = (util::posix_str(root), util::posix_str(&abs));
    if if cfg!(windows) { a.eq_ignore_ascii_case(&rs) } else { a == rs } { return Some(String::new()); }
    let sw = if cfg!(windows) { a.to_lowercase().starts_with(&(rs.to_lowercase() + "/")) } else { a.starts_with(&(rs.clone() + "/")) };
    sw.then(|| a[rs.len() + 1..].to_string())
}

pub fn meta_stat(m: &std::fs::Metadata) -> (i64, i64) {
    (m.modified().ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_nanos() as i64).unwrap_or(0), m.len() as i64)
}

fn collect_dir(dir: &Path, recursive: bool, exts: &[&str], out: &mut Vec<(PathBuf, i64, i64)>) {
    for ent in std::fs::read_dir(dir).ok().into_iter().flatten().flatten() {
        let Ok(ft) = ent.file_type() else { continue };
        let p = ent.path();
        if ft.is_dir() {
            let ns = ent.file_name().to_string_lossy().to_string();
            if recursive && !ns.starts_with('.') && ns != "retired" && ns != "__pycache__" { collect_dir(&p, true, exts, out); }
        } else if ft.is_file() {
            let ext = p.extension().and_then(|s| s.to_str()).unwrap_or("");
            if exts.is_empty() || exts.iter().any(|e| ext.eq_ignore_ascii_case(e)) {
                let (mt, sz) = ent.metadata().map(|m| meta_stat(&m)).unwrap_or((0, 0));
                out.push((p, mt, sz));
            }
        }
    }
}

pub fn walk(cfg: &Config) -> Vec<WalkFile> {
    let (mut out, mut buf) = (Vec::new(), Vec::new());
    let push_one = |out: &mut Vec<WalkFile>, p: PathBuf, area: &str, sub: &str, tool: &str| {
        if let Ok(m) = std::fs::metadata(&p) { if m.is_file() { let rel = cfg.rel(&p); if !cfg.is_excluded(&rel) { let (mtime_ns, size) = meta_stat(&m); out.push(WalkFile { path: p, rel, area: area.into(), sub: sub.into(), tool: tool.into(), mtime_ns, size }); } } }
    };
    let push_buf = |out: &mut Vec<WalkFile>, buf: &mut Vec<(PathBuf, i64, i64)>, area: &str, sub: &str, tool: &str, skip: Option<&str>| {
        for (p, mtime_ns, size) in buf.drain(..) {
            if skip.map(|sk| p.file_name().and_then(|s| s.to_str()).map(|n| n.eq_ignore_ascii_case(sk)).unwrap_or(false)).unwrap_or(false) { continue; }
            let rel = cfg.rel(&p);
            if !cfg.is_excluded(&rel) { out.push(WalkFile { path: p, rel, area: area.into(), sub: sub.into(), tool: tool.into(), mtime_ns, size }); }
        }
    };
    let sdir = cfg.self_dir();
    push_one(&mut out, sdir.join("RULES.md"), "rules", "", ""); push_one(&mut out, sdir.join("style.md"), "style", "", "");
    for (d, rec, a, sk) in [(sdir.join("facts"), true, "facts", None), (cfg.memory_dir(), true, "memory", Some("MEMORY.md")), (cfg.records_dir(), false, "record", None)] { collect_dir(&d, rec, &["md"], &mut buf); push_buf(&mut out, &mut buf, a, "", "", sk); }
    for sub in ["pending", "rejected", "applied"] { collect_dir(&cfg.proposals_dir().join(sub), false, &["md"], &mut buf); push_buf(&mut out, &mut buf, "proposal", sub, "", None); }
    for t in &cfg.tools {
        push_one(&mut out, t.dir.join("SKILL.md"), "manual", "skill", &t.name); push_one(&mut out, t.dir.join("READING.md"), "reading", "", &t.name);
        for (sd, rec, a, sub, exts, sk) in [("dict", false, "dict", "", &["md"][..], None), ("playbooks", false, "playbook", "", &["md"][..], Some("INDEX.md")), ("materials", true, "material", "materials", &["md"][..], None), ("kit", true, "material", "kit", &["md"][..], None), ("checks", false, "checks", "", &["py"][..], None)] {
            collect_dir(&t.dir.join(sd), rec, exts, &mut buf); push_buf(&mut out, &mut buf, a, sub, &t.name, sk);
        }
    }
    for c in &cfg.corpus { collect_dir(&cfg.root.join(&c.path), true, &["md", "txt"], &mut buf); push_buf(&mut out, &mut buf, "corpus", &c.sub, &c.tool, None); }
    if let Some(ldir) = cfg.logs_dir() {
        collect_dir(&ldir, false, &["md"], &mut buf);
        for (p, mtime_ns, size) in buf.drain(..) {
            if let Some(rel) = p.file_name().and_then(|s| s.to_str()).filter(|n| n.len() == 13 && n.as_bytes()[4] == b'-' && n.as_bytes()[7] == b'-').map(|n| format!("logs/{}", n)) {
                out.push(WalkFile { path: p, rel, area: "log".into(), sub: "logs".into(), tool: String::new(), mtime_ns, size });
            }
        }
    }
    out
}

pub fn walk_books(cfg: &Config) -> Vec<WalkFile> {
    let (mut out, mut buf) = (Vec::new(), Vec::new());
    for b in &cfg.books {
        collect_dir(&cfg.root.join(&b.path), true, &["md", "txt"], &mut buf);
        for (p, mtime_ns, size) in buf.drain(..) { let rel = cfg.rel(&p); if !cfg.is_excluded(&rel) { out.push(WalkFile { path: p, rel, area: "book".into(), sub: b.sub.clone(), tool: b.tool.clone(), mtime_ns, size }); } }
    }
    out
}

pub fn classify_rel(cfg: &Config, rel: &str) -> Option<(String, String, String)> {
    let rp = rel.replace('\\', "/"); let rp = rp.trim_start_matches("./");
    if cfg.is_excluded(rp) { return None; }
    let eq = |a: &str, b: &str| if cfg!(windows) { a.eq_ignore_ascii_case(b) } else { a == b };
    let sw = |s: &str, p: &str| if cfg!(windows) { s.to_lowercase().starts_with(&p.to_lowercase()) } else { s.starts_with(p) };
    let is_md = rp.to_lowercase().ends_with(".md");
    if eq(rp, &format!("{}/RULES.md", cfg.self_rel)) { return Some(("rules".into(), "".into(), "".into())); }
    if eq(rp, &format!("{}/style.md", cfg.self_rel)) { return Some(("style".into(), "".into(), "".into())); }
    if sw(rp, &format!("{}/facts/", cfg.self_rel)) && is_md { return Some(("facts".into(), "".into(), "".into())); }
    if sw(rp, &format!("{}/", cfg.memory_rel.trim_end_matches('/'))) && is_md && !rp.to_lowercase().ends_with("/memory.md") { return Some(("memory".into(), "".into(), "".into())); }
    let rec_pre = format!("{}/records/", cfg.self_rel);
    if sw(rp, &rec_pre) && is_md && !rp[rec_pre.len()..].contains('/') { return Some(("record".into(), "".into(), "".into())); }
    let prop_pre = format!("{}/", cfg.proposals_rel.trim_end_matches('/'));
    if sw(rp, &prop_pre) && is_md { if let Some((sub, rest)) = rp[prop_pre.len()..].split_once('/') { if matches!(sub, "pending" | "rejected" | "applied") && !rest.contains('/') { return Some(("proposal".into(), sub.into(), "".into())); } } }
    for t in &cfg.tools {
        let tp = t.path.trim_matches('/').replace('\\', "/");
        if eq(rp, &format!("{}/SKILL.md", tp)) { return Some(("manual".into(), "skill".into(), t.name.clone())); }
        if eq(rp, &format!("{}/READING.md", tp)) { return Some(("reading".into(), "".into(), t.name.clone())); }
        if sw(rp, &format!("{}/dict/", tp)) && is_md { return Some(("dict".into(), "".into(), t.name.clone())); }
        if sw(rp, &format!("{}/playbooks/", tp)) && is_md && !rp.to_lowercase().ends_with("/index.md") { return Some(("playbook".into(), "".into(), t.name.clone())); }
        if sw(rp, &format!("{}/materials/", tp)) && is_md { return Some(("material".into(), "materials".into(), t.name.clone())); }
        if sw(rp, &format!("{}/kit/", tp)) && is_md { return Some(("material".into(), "kit".into(), t.name.clone())); }
    }
    cfg.corpus.iter().find(|c| sw(rp, &format!("{}/", c.path.trim_matches('/').replace('\\', "/"))) && (is_md || rp.to_lowercase().ends_with(".txt"))).map(|c| ("corpus".into(), c.sub.clone(), c.tool.clone()))
}
