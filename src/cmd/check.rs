use crate::config::{self, Config, WalkFile};
use crate::domain::{quotes, shapes, tokenize};
use crate::pilots::{self, PilotKind};
use crate::store::{index, telemetry};
use crate::util;
use chrono::NaiveDate;
use rayon::prelude::*;
use regex::Regex;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs;
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::OnceLock;

const HOOKS: &[&str] = &["precommit", "outbound", "precompact", "stop"];
const VERBS: &[&str] = &["index", "check", "apply", "eval", "search", "status", "init", "mcp", "hash", "gate", "trace", "review", "outbound"];

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Finding { pub level: String, pub code: String, pub file: String, pub msg: String, pub at: String }
#[derive(Debug, Default)]
pub struct CheckOutput { pub errors: Vec<Finding>, pub warnings: Vec<Finding>, pub moved: Vec<String>, pub numbers: String }
struct LoadedFile { wf: WalkFile, text: String, parsed: shapes::ParsedFile, age: i64 }

fn agrees(fm: &shapes::Fm) -> bool {
    let (c, v) = (shapes::fm_str(fm, "chosen"), shapes::fm_str(fm, "verdict"));
    if c.is_empty() { return false; }
    if c == v || ["同意", "同 ", "按它", "按 verdict"].iter().any(|p| c.starts_with(p)) { return true; }
    static RE_OPT: OnceLock<Regex> = OnceLock::new();
    let re = RE_OPT.get_or_init(|| Regex::new(r"^(?:推荐\s*)?([A-Z])(?:$|[\s（(：:、.。])").unwrap());
    fn strip(s: &str) -> &str { s.trim_matches(&['*', '`', ' '][..]) }
    matches!((re.captures(strip(&c)), re.captures(strip(&v))), (Some(a), Some(b)) if a[1] == b[1])
}

fn ratio(k: usize, n: usize, pct: bool) -> String {
    if n == 0 { return "-".into(); }
    if n < 10 || !pct { return format!("{}/{}", k, n); }
    let (p, z, nf) = (k as f64 / n as f64, 1.96f64, n as f64);
    let d = 1.0 + z * z / nf; let c = (p + z * z / (2.0 * nf)) / d;
    let h = z * ((p * (1.0 - p) / nf + z * z / (4.0 * nf * nf)).sqrt()) / d;
    format!("{}/{}  {}% [{},{}]", k, n, (100.0 * p).round() as i64, (100.0 * (c - h)).round() as i64, (100.0 * (c + h)).round() as i64)
}

fn load_referenced_corpus(hints: &HashSet<String>, corpus: &[WalkFile]) -> HashMap<String, Vec<String>> {
    if hints.is_empty() { return HashMap::new(); }
    let hn: Vec<String> = hints.iter().map(|h| quotes::norm_title(h)).filter(|s| s.chars().count() >= 2).collect();
    let picked: Vec<&WalkFile> = corpus.iter().filter(|wf| {
        let st = wf.path.file_stem().and_then(|s| s.to_str()).unwrap_or("");
        let sn = quotes::norm_title(st);
        hints.iter().any(|h| st.contains(h.as_str())) || hn.iter().any(|x| sn.contains(x.as_str()) || (sn.chars().count() >= 4 && x.contains(&sn)))
    }).collect();
    let mut map: HashMap<String, Vec<String>> = HashMap::new();
    for (id, title, norm) in picked.par_iter().filter_map(|wf| {
        let d = shapes::parse_doc(&fs::read_to_string(&wf.path).ok()?, &wf.path);
        Some((d.id, d.title, quotes::compact_ws(&d.text)))
    }).collect::<Vec<_>>() {
        map.entry(id).or_default().push(norm.clone());
        map.entry(title).or_default().push(norm);
    }
    map
}

fn is_sup(r: &LoadedFile, sup: &HashSet<String>) -> bool {
    sup.contains(&r.wf.rel) || sup.contains(r.wf.path.file_stem().and_then(|s| s.to_str()).unwrap_or(""))
}
fn run_trusted_tool_checks(cfg: &Config, at: &str, errs: &mut Vec<Finding>, warns: &mut Vec<Finding>) {
    let scripts: Vec<_> = cfg.tools.iter().flat_map(|t| fs::read_dir(t.dir.join("checks")).ok().into_iter().flatten().flatten())
        .map(|e| e.path()).filter(|p| p.extension().and_then(|s| s.to_str()) == Some("py")).map(|p| (cfg.rel(&p), p)).collect();
    if scripts.is_empty() { return; }
    let dirty: HashSet<String> = util::git_ro(&cfg.root, &["status", "--porcelain", "-z"]).unwrap_or_default().split('\0').filter(|e| e.len() >= 4).map(|e| e[3..].trim().replace('\\', "/")).collect();
    let tracked: HashSet<String> = util::git_ro(&cfg.root, &["ls-files", "-z"]).unwrap_or_default().split('\0').map(|s| s.trim().replace('\\', "/")).collect();
    let mut py_bin: Option<&str> = None;
    for (rel, p) in scripts {
        if !tracked.contains(&rel) || dirty.contains(&rel) {
            warns.push(Finding { level: "WARNING".into(), code: "check_untrusted".into(), file: rel, msg: "equipment check script untracked/modified (skipped — D70)".into(), at: at.into() }); continue;
        }
        let py = *py_bin.get_or_insert_with(|| ["python", "python3"].into_iter().find(|b| Command::new(b).arg("--version").output().map(|o| o.status.success()).unwrap_or(false)).unwrap_or("python"));
        if let Ok(o) = Command::new(py).arg(&p).current_dir(&cfg.root).env("PLUG_ROOT", &cfg.root).output() {
            for l in format!("{}\n{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr)).lines().map(str::trim) {
                if let Some(r) = l.strip_prefix("ERROR ") { errs.push(Finding { level: "ERROR".into(), code: "tool_check".into(), file: rel.clone(), msg: r.into(), at: at.into() }); }
                else if let Some(r) = l.strip_prefix("WARNING ") { warns.push(Finding { level: "WARNING".into(), code: "tool_check".into(), file: rel.clone(), msg: r.into(), at: at.into() }); }
            }
        }
    }
}

pub fn check_repo(cfg: &Config, expire: bool, tool_checks: bool, write_numbers: bool) -> CheckOutput {
    let (today, at, mut out) = (util::today(), util::now_hm(), CheckOutput::default());
    let pe = |o: &mut CheckOutput, c: &str, f: &str, m: String| o.errors.push(Finding { level: "ERROR".into(), code: c.into(), file: f.into(), msg: m, at: at.clone() });
    let pw = |o: &mut CheckOutput, c: &str, f: &str, m: String| o.warnings.push(Finding { level: "WARNING".into(), code: c.into(), file: f.into(), msg: m, at: at.clone() });
    if !cfg.shape_ok() { pe(&mut out, "shape_version", "plug.yaml", format!("shape version {} unknown — refusing to run", cfg.shape_version)); return out; }
    if !cfg.machine_ok() { pw(&mut out, "machine_pin", "plug.yaml", format!("pinned '{}' != installed {}", cfg.machine_pin, util::VERSION)); }
    for t in &cfg.tools { if !t.dir.is_dir() { pe(&mut out, "tool_path", "plug.yaml", format!("equipment dir missing: {}", t.path)); } }
    for c in &cfg.corpus { if !cfg.root.join(&c.path).is_dir() { pw(&mut out, "corpus_path", "plug.yaml", format!("corpus dir missing: {}", c.path)); } }
    let (corpus, non_corpus): (Vec<_>, Vec<_>) = config::walk(cfg).into_iter().filter(|w| w.area != "checks" && w.area != "log").partition(|w| w.area == "corpus");
    let need_gd = non_corpus.iter().any(|w| matches!(w.area.as_str(), "dict" | "playbook" | "proposal") && w.path.file_stem().and_then(|s| s.to_str()).and_then(|s| s.get(..10)).and_then(shapes::parse_day).is_none());
    let gdates = if need_gd { util::git_first_dates(&cfg.root) } else { HashMap::new() };
    let loaded: Vec<LoadedFile> = non_corpus.par_iter().filter_map(|wf| {
        let text = fs::read_to_string(&wf.path).ok()?;
        let parsed = shapes::parse_file(&text, if wf.sub == "kit" && !text.starts_with("---") { "" } else { wf.area.as_str() });
        let age = shapes::parse_day(&shapes::fm_str(&parsed.fm, "date")).or_else(|| wf.path.file_stem().and_then(|s| s.to_str()).and_then(|s| s.get(..10)).and_then(shapes::parse_day)).or_else(|| gdates.get(&wf.rel).copied()).map(|d| (today - d).num_days().max(0)).unwrap_or(0);
        Some(LoadedFile { wf: wf.clone(), text, parsed, age })
    }).collect();
    let (mut rules_p, mut entries, mut records, mut proposals, mut materials, mut manuals) = (None, Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new());
    for lf in &loaded {
        for e in &lf.parsed.errors { pe(&mut out, "shape", &lf.wf.rel, e.clone()); }
        match lf.wf.area.as_str() { "rules" => rules_p = Some(shapes::parse_rules(&lf.text)), "dict" | "playbook" => entries.push(lf), "record" => records.push(lf), "proposal" => proposals.push(lf), "material" => materials.push(lf), "manual" => manuals.push(lf), _ => {} }
    }
    let mut hints: HashSet<String> = entries.iter().flat_map(|e| e.parsed.obs.iter().filter_map(|o| o.doc.clone())).collect();
    for r in &records { if shapes::record_kind(&r.parsed.fm) == shapes::RecordKind::Decision { hints.extend(quotes::extract_quotes(&r.parsed.body).into_iter().map(|q| q.doc_hint)); } }
    let docs_norm = load_referenced_corpus(&hints, &corpus);
    let tool_map: HashMap<&str, &config::ToolDecl> = cfg.tools.iter().map(|t| (t.name.as_str(), t)).collect();
    let (mut names, mut anchors, mut inbound): (HashMap<(String, String), String>, HashSet<String>, HashMap<String, usize>) = (HashMap::new(), HashSet::new(), entries.iter().filter(|e| e.wf.area == "dict").map(|e| (e.wf.rel.clone(), 0)).collect());
    for e in &entries {
        for nm in std::iter::once(shapes::fm_str(&e.parsed.fm, "title")).chain(shapes::fm_list(&e.parsed.fm, "aliases")).filter(|s| !s.is_empty()) {
            let k = (e.wf.tool.clone(), nm.clone());
            if let Some(prev) = names.get(&k).filter(|p| *p != &e.wf.rel) { pw(&mut out, "collision", &e.wf.rel, format!("'{}' collides with {}", nm, prev)); } else { names.insert(k, e.wf.rel.clone()); }
        }
        anchors.extend(e.parsed.obs.iter().filter_map(|o| o.anchor.clone()));
    }
    let re_other = Regex::new(r"^\s*[-*]\s*(让|叫|要求|告诉|向|逼|劝)对方").unwrap();
    for e in &entries {
        for link in &e.parsed.links {
            let (t2, name) = link.rsplit_once('/').unwrap_or((e.wf.tool.as_str(), link.as_str()));
            if t2 != e.wf.tool && !tool_map.get(e.wf.tool.as_str()).map(|td| td.depends.iter().any(|d| d == t2)).unwrap_or(false) { pe(&mut out, "cross_tool", &e.wf.rel, format!("[[{}]] undeclared dep {}", link, t2)); }
            else if let Some(dst) = names.get(&(t2.into(), name.into())) { if dst != &e.wf.rel { if let Some(c) = inbound.get_mut(dst) { *c += 1; } } }
            else { pe(&mut out, "link", &e.wf.rel, format!("[[{}]] unresolved", link)); }
        }
        for o in &e.parsed.obs {
            let wh = format!("{}:{}", e.wf.rel, o.line);
            if o.missing_src { pe(&mut out, "obs_src", &wh, "no (src: …)".into()); continue; }
            for r in &o.refs { if !anchors.contains(r) { pe(&mut out, "pid", &wh, format!("{} unresolved", r)); } }
            if let (Some(q), Some(doc)) = (&o.quote, &o.doc) {
                if !docs_norm.contains_key(doc) { pe(&mut out, "anchor", &wh, format!("no corpus doc '{}'", doc)); }
                else if !quotes::verify_quote_in_map(&quotes::QuoteRef { doc_hint: doc.clone(), quote: q.clone() }, &docs_norm) { pe(&mut out, "anchor", &wh, format!("anchor sentence not found in {}: '{}'", doc, q.chars().take(30).collect::<String>())); }
            } else if o.refs.is_empty() && !o.unanchored { pe(&mut out, "obs_src", &wh, "src lacks quote or ^p ref".into()); }
        }
        if e.parsed.body.chars().count() > 4000 || e.parsed.obs.len() > 25 { pw(&mut out, "long", &e.wf.rel, "page too long".into()); }
        if shapes::fm_str(&e.parsed.fm, "kind") == "concept" && shapes::fm_list(&e.parsed.fm, "aliases").len() < 2 { pw(&mut out, "aliases", &e.wf.rel, "concept <2 aliases".into()); }
        let st = shapes::fm_str(&e.parsed.fm, "stance");
        if st == "warning" || st == "diagnostic" {
            for sec in ["动作", "练习"] { for l in e.parsed.sections.get(sec).map(String::as_str).unwrap_or("").lines() { if re_other.is_match(l) { pw(&mut out, "warning_action", &e.wf.rel, format!("stance={} aims action at other party", st)); } } }
        }
    }
    for (rel, n) in &inbound { if *n < 3 && entries.iter().find(|e| &e.wf.rel == rel).map(|e| e.age <= 30).unwrap_or(false) { pw(&mut out, "inbound", rel, format!("new entry has {} inbound (<3)", n)); } }
    for t in &cfg.tools { if let Some(wu) = t.unreviewed { let got: usize = entries.iter().filter(|e| e.wf.tool == t.name).map(|e| e.parsed.obs.iter().filter(|o| o.unreviewed).count()).sum(); if got != wu { pw(&mut out, "unreviewed", &t.path, format!("[?] count {} != {}", got, wu)); } } }

    let (rule_ids, retired_ids) = rules_p.as_ref().map(|r| (r.ids.clone(), r.retired_ids.clone())).unwrap_or_default();
    if let Some(rules) = &rules_p {
        for k in ["model", "reviewed"] { if !rules.header.contains_key(k) { pw(&mut out, "rules_header", "self/RULES.md", format!("missing {}:", k)); } }
        let (ts, ym) = (today.format("%Y-%m-%d").to_string(), today.format("%Y-%m").to_string());
        for s in &rules.sections {
            if let Some(exp) = s.expires.as_ref().filter(|e| *e < &ts) { pw(&mut out, "rules_expired", "self/RULES.md", format!("section '{}' expired ({})", s.name, exp)); }
            for l in &s.lines {
                if !l.dated && !s.name.contains("退役") { pw(&mut out, "rule_date", "self/RULES.md", format!("{} carries no date", l.id)); }
                for rv in [l.review.as_ref(), s.review.as_ref()].into_iter().flatten() { if rv < &ym { pw(&mut out, "rules_review", "self/RULES.md", format!("{} due for review in {}", l.id, rv)); } }
            }
        }
    }
    let mut sup_set = HashSet::new();
    for r in &records { let sup = shapes::fm_str(&r.parsed.fm, "supersedes"); if !sup.is_empty() { sup_set.insert(sup.clone()); if let Some(st) = Path::new(&sup).file_stem().and_then(|s| s.to_str()) { sup_set.insert(st.into()); } } }
    for r in &records {
        let basis = r.parsed.sections.get("依据").map(String::as_str).unwrap_or("");
        let mut unsure = Vec::new();
        for (rid, cited) in shapes::rule_citations(basis, &rule_ids) {
            if rule_ids.contains(&rid) { if retired_ids.contains(&rid) { pw(&mut out, "rid_retired", &r.wf.rel, format!("{} retired", rid)); } }
            else if cited { pe(&mut out, "rid", &r.wf.rel, format!("{} not in RULES.md", rid)); }
            else if !unsure.contains(&rid) { unsure.push(rid); }
        }
        if !unsure.is_empty() && shapes::record_kind(&r.parsed.fm) == shapes::RecordKind::Decision { pw(&mut out, "rid_unsure", &r.wf.rel, format!("{} look like rule ids", unsure.join("、"))); }
        let od = tool_map.get(shapes::fm_str(&r.parsed.fm, "tool").as_str()).and_then(|t| t.outcome_days).unwrap_or(cfg.outcome_days);
        if shapes::outcome_owed(&r.parsed.fm, r.age, today, od, is_sup(r, &sup_set)) {
            if let Some(d) = shapes::due_date(&r.parsed.fm) { pw(&mut out, "due", &r.wf.rel, format!("due {} ({}d ago) has no outcome", d, (today - d).num_days())); }
            else { pw(&mut out, "outcome", &r.wf.rel, format!("decision record has had no outcome for {} days", r.age)); }
        }
    }
    let mut seen_p = HashMap::new();
    for p in proposals.iter().filter(|x| x.wf.sub == "pending") {
        if let Some(prev) = seen_p.insert((shapes::fm_str(&p.parsed.fm, "target"), shapes::fm_str(&p.parsed.fm, "from")), p.wf.rel.clone()) { pw(&mut out, "dup", &p.wf.rel, format!("duplicate proposal: {}", prev)); }
        if !p.text.contains("plug apply") { pw(&mut out, "footer", &p.wf.rel, "no `plug apply` footer".into()); }
        if expire && p.age > 30 {
            let dst = util::unique_dest(&cfg.proposals_dir().join("rejected"), p.wf.path.file_name().and_then(|s| s.to_str()).unwrap_or("expired.md"));
            if util::write_lf(&dst, &format!("{}\n\nrejected: {} · expired ({}d)\n", p.text.trim_end(), today, p.age)).is_ok() { let _ = fs::remove_file(&p.wf.path); out.moved.push(p.wf.rel.clone()); }
        }
    }
    for m in &materials {
        if let Some(d) = shapes::parse_day(&shapes::fm_str(&m.parsed.fm, "expires")) { if d < today { pw(&mut out, "expired", &m.wf.rel, format!("material expired on {}", d)); } continue; }
        if m.wf.sub == "kit" { continue; }
        let k = shapes::fm_str(&m.parsed.fm, "kind");
        let ttl = tool_map.get(m.wf.tool.as_str()).and_then(|t| t.ttl_days.get(&k).or_else(|| t.ttl_days.get("default"))).copied().unwrap_or(90);
        if m.age > ttl { pw(&mut out, "expired", &m.wf.rel, format!("material past shelf life ({}: {}d > {}d)", k, m.age, ttl)); }
    }
    let dtotal: usize = manuals.iter().map(|m| { let dl = shapes::fm_str(&m.parsed.fm, "description").chars().count() + shapes::fm_str(&m.parsed.fm, "when_to_use").chars().count(); if dl > 1536 { pw(&mut out, "desc", &m.wf.rel, format!("description {} chars > 1536", dl)); } dl }).sum();
    if dtotal > 4000 { pw(&mut out, "desc", "tools", format!("manual descriptions total {} > 4000", dtotal)); }
    for pk in [PilotKind::ClaudeCode, PilotKind::Codex, PilotKind::Antigravity] {
        let a = pilots::audit_pilot(cfg, pk);
        if a.installed && !a.ok { let code = match pk { PilotKind::Codex => "codex_trust", PilotKind::Antigravity => "agy_plugin", PilotKind::ClaudeCode => "claude_wiring" }; for iss in a.issues { pw(&mut out, code, pk.name(), iss); } }
    }
    let (re_lie, re_verb) = (Regex::new(r"(?i)sortie lock.{0,200}(only records|cannot veto|records, not a lock|obligation, not a fence)").unwrap(), Regex::new(r"(?m)(?:`|!\s|^\s*)plug\s+([a-z][\w-]*)").unwrap());
    for mn in ["CLAUDE.md", "AGENTS.md", "GEMINI.md"] {
        if let Ok(txt) = fs::read_to_string(cfg.root.join(mn)) {
            if re_lie.is_match(&txt) { pw(&mut out, "map_claim", mn, "map falsely claims sortie lock cannot veto".into()); }
            for c in re_verb.captures_iter(&txt) { if !VERBS.contains(&&c[1]) { pw(&mut out, "path", mn, format!("unknown command plug {}", &c[1])); } }
        }
    }
    match fs::read_to_string(cfg.index_md_path()) {
        Err(_) => pw(&mut out, "index_md", &cfg.index_md_rel, "index.md missing (run plug index)".into()),
        Ok(txt) => {
            if let Some(m) = entries.iter().find(|e| !txt.contains(&e.wf.rel)) { pw(&mut out, "index_md", &cfg.index_md_rel, format!("index.md missing {}", m.wf.rel)); }
            if txt.len() > 50_000 { pw(&mut out, "index_md", &cfg.index_md_rel, format!("index.md oversized ({} bytes)", txt.len())); }
        }
    }
    for h in HOOKS {
        let stamp = fs::read_to_string(cfg.hooks_dir().join(h)).ok().map(|s| s.trim().to_string()).unwrap_or_default();
        if stamp.get(..10).and_then(shapes::parse_day).map(|d| (today - d).num_days() > 30).unwrap_or(true) {
            pw(&mut out, "hook", &format!("{}/{}", cfg.hooks_rel, h), format!("hook {} {}", h, if stamp.is_empty() { "has never fired".into() } else { format!("last fired {}", stamp) }));
        }
    }
    if let Some(lag) = index::stale_lag(cfg) { pw(&mut out, "index_stale", &cfg.index_rel, format!("index stale ({}); run plug index", lag)); }
    else if !cfg.index_path().is_file() { pw(&mut out, "index_stale", &cfg.index_rel, "index missing; run plug index".into()); }
    if tool_checks { run_trusted_tool_checks(cfg, &at, &mut out.errors, &mut out.warnings); }
    if write_numbers { out.numbers = render_numbers_page(cfg, &records, &sup_set, &docs_norm, &anchors, &rule_ids, &tool_map, today); let _ = util::write_lf(&cfg.numbers_path(), &out.numbers); }
    out
}

fn render_numbers_page(cfg: &Config, records: &[&LoadedFile], sup_set: &HashSet<String>, docs_norm: &HashMap<String, Vec<String>>, anchors: &HashSet<String>, rule_ids: &HashSet<String>, tool_map: &HashMap<&str, &config::ToolDecl>, today: NaiveDate) -> String {
    let blind = telemetry::read_blind_map(cfg);
    let decisions: Vec<&LoadedFile> = records.iter().copied().filter(|r| shapes::record_kind(&r.parsed.fm) == shapes::RecordKind::Decision).collect();
    let mut tools: Vec<String> = cfg.tools.iter().map(|t| t.name.clone()).collect();
    tools.extend(decisions.iter().map(|r| shapes::fm_str(&r.parsed.fm, "tool")).filter(|t| !t.is_empty() && !tools.contains(t)).collect::<BTreeSet<_>>());
    if tools.is_empty() { tools.push("none".into()); }
    #[derive(Default)]
    struct S { n: usize, unans: usize, pend: usize, valid: usize, nonblind: usize, nocom: usize, agree: usize, it: usize, me: usize, unc: usize, qo: usize, qa: usize, ro: usize, ra: usize, four: usize, cite: usize }
    let mut st: BTreeMap<String, S> = tools.iter().map(|t| (t.clone(), S::default())).collect();
    let re_p = Regex::new(r"\^p\d+").unwrap();
    for r in &decisions {
        let tn = shapes::fm_str(&r.parsed.fm, "tool");
        let Some(s) = st.get_mut(&tn) else { continue };
        s.n += 1;
        let (chosen, outcome) = (shapes::fm_str(&r.parsed.fm, "chosen"), shapes::fm_str(&r.parsed.fm, "outcome"));
        let od = tool_map.get(tn.as_str()).and_then(|t| t.outcome_days).unwrap_or(cfg.outcome_days);
        if chosen.is_empty() { s.unans += 1; }
        if shapes::outcome_owed(&r.parsed.fm, r.age, today, od, is_sup(r, sup_set)) { s.pend += 1; }
        if !chosen.is_empty() {
            match blind.get(&r.wf.rel) { Some(b) if !b.has_chosen => { s.valid += 1; if agrees(&r.parsed.fm) { s.agree += 1; } } Some(_) => s.nonblind += 1, None => s.nocom += 1 }
            if !agrees(&r.parsed.fm) && !outcome.is_empty() {
                match [("it", outcome.rfind("它对")), ("me", outcome.rfind("我对").max(outcome.rfind("你对"))), ("unc", outcome.rfind("说不清"))].into_iter().filter_map(|(k, p)| p.map(|i| (k, i))).max_by_key(|x| x.1).map(|x| x.0) {
                    Some("it") => s.it += 1, Some("me") => s.me += 1, Some("unc") => s.unc += 1, _ => {}
                }
            }
        }
        for qr in quotes::extract_quotes(&r.parsed.body) { s.qa += 1; if quotes::verify_quote_in_map(&qr, docs_norm) { s.qo += 1; } }
        for a in re_p.find_iter(&r.parsed.body).map(|m| m.as_str()).collect::<HashSet<_>>() { s.qa += 1; if anchors.contains(a) { s.qo += 1; } }
        let basis = r.parsed.sections.get("依据").map(String::as_str).unwrap_or("");
        for rid in shapes::rule_refs(basis, rule_ids) { s.ra += 1; if rule_ids.contains(&rid) { s.ro += 1; } }
        if shapes::has_four_elements(&r.parsed.sections) { s.four += 1; }
        if basis.contains("records/") { s.cite += 1; }
    }
    let head = format!("# Sync rate (numbers page) · {} · machine entryplug {} · decision records {} ({}) · unanswered {} · outcome pending {}",
        today, util::VERSION, decisions.len(), tools.iter().map(|t| format!("{} {}", t, st[t].n)).collect::<Vec<_>>().join(" · "),
        st.values().map(|s| s.unans).sum::<usize>(), st.values().map(|s| s.pend).sum::<usize>());
    let row = |lbl: &str, f: &dyn Fn(&S) -> String| format!("| {} | {} |", lbl, tools.iter().map(|t| f(&st[t])).collect::<Vec<_>>().join(" | "));
    vec![
        head, String::new(), format!("| metric | {} |", tools.join(" | ")), format!("|---|{}", "---|".repeat(tools.len())),
        row("agreement rate (blind-valid)", &|s| {
            let mut t = ratio(s.agree, s.valid, true);
            if s.valid >= 30 && s.agree as f64 / s.valid as f64 > 0.95 { t.push_str("  likely sycophancy"); }
            if s.nonblind > 0 { t.push_str(&format!("  ({} non-blind excluded)", s.nonblind)); }
            if s.nocom > 0 { t.push_str(&format!("  ({} without blind commitment)", s.nocom)); }
            t
        }),
        row("who was right after a disagreement", &|s| if s.it + s.me + s.unc == 0 { "0 decidable".into() } else { format!("it was right {} · I was right {} · unclear {}", s.it, s.me, s.unc) }),
        row("quotes verifiable", &|s| ratio(s.qo, s.qa, s.qa >= 10)),
        row("rule references real", &|s| ratio(s.ro, s.ra, false)),
        row("four elements present", &|s| ratio(s.four, s.n, false)),
        row("cites earlier records", &|s| if s.n >= 10 { ratio(s.cite, s.n, false) } else { format!("n<10 ({}/{})", s.cite, s.n) }),
        String::new(), "Decision records only (notes excluded). Blind-valid verified by .kb/blind.jsonl pre-reveal commitment.".into(),
    ].join("\n") + "\n"
}

pub fn format_findings(errors: &[Finding], warnings: &[Finding]) -> String {
    errors.iter().chain(warnings.iter()).map(|f| format!("{} {} {} · {} [{}]", f.level, f.code, f.file, f.msg, f.at)).collect::<Vec<_>>().join("\n")
}

pub fn run(cfg: &Config, quiet: bool, no_expire: bool, contact: Option<&str>) -> i32 {
    if let Some(pilot) = contact { return run_contact(cfg, pilot); }
    let res = check_repo(cfg, !no_expire, true, true);
    if !quiet { println!("entryplug check · {} · machine {} · errors {} · warnings {}", util::now_hm(), util::VERSION, res.errors.len(), res.warnings.len()); }
    let body = format_findings(&res.errors, &res.warnings);
    if !body.is_empty() { println!("{}", body); } else if !quiet { println!("all clean (0 errors, 0 warnings)"); }
    if res.errors.is_empty() { 0 } else { 1 }
}

fn spawn_io(bin: &str, args: &[&str], cwd: &Path, stdin_s: &str, add: &[(&str, &str)], drop: &[&str]) -> Result<(i32, String, String), String> {
    let mut cmd = Command::new(bin);
    cmd.args(args).current_dir(cwd).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    for k in drop { cmd.env_remove(k); }
    for (k, v) in add { cmd.env(k, v); }
    let mut child = cmd.spawn().map_err(|e| e.to_string())?;
    if let Some(mut sin) = child.stdin.take() { let _ = sin.write_all(stdin_s.as_bytes()); }
    let o = child.wait_with_output().map_err(|e| e.to_string())?;
    Ok((o.status.code().unwrap_or(1), String::from_utf8_lossy(&o.stdout).into(), String::from_utf8_lossy(&o.stderr).into()))
}

pub fn run_contact(cfg: &Config, pilot_name: &str) -> i32 {
    let Some(pilot) = PilotKind::from_str(pilot_name) else { eprintln!("check --contact: unknown pilot '{}'", pilot_name); return 1; };
    let (bin, root_s) = (pilots::current_plug_bin(), util::posix_str(&cfg.root));
    let exe = match pilot { PilotKind::ClaudeCode => "claude", PilotKind::Codex => "codex", PilotKind::Antigravity => "agy" };
    let hv = (if cfg!(windows) { Command::new("cmd").args(["/c", exe, "--version"]).output() } else { Command::new(exe).arg("--version").output() })
        .ok().map(|o| format!("{}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr)).lines().next().unwrap_or("").trim().chars().take(48).collect::<String>())
        .filter(|s| !s.is_empty()).unwrap_or_else(|| "not installed or not on PATH".into());
    let sdir = cfg.pilots.get(pilot.name()).map(|p| p.skills.as_str()).filter(|s| !s.is_empty()).unwrap_or(if pilot == PilotKind::ClaudeCode { ".claude/skills" } else { ".agents/skills" });
    let cap = if pilot == PilotKind::Antigravity { pilots::AGY_DESC_MAX } else { pilots::CLAUDE_DESC_MAX };
    let mut s1_bad = Vec::new();
    for t in &cfg.tools {
        let (src, dst) = (t.dir.join("SKILL.md"), cfg.root.join(sdir).join(&t.name).join("SKILL.md"));
        if fs::read(&src).ok() != fs::read(&dst).ok() { s1_bad.push(format!("{} not mirrored", t.name)); }
        else if let Ok(txt) = fs::read_to_string(&src) {
            let dl = shapes::split_frontmatter(&txt).0.map(|f| shapes::fm_str(&f, "description").chars().count()).unwrap_or(0);
            if dl == 0 || dl > cap { s1_bad.push(format!("{} description invalid/>{}", t.name, cap)); }
        }
    }
    let s1 = (s1_bad.is_empty(), if s1_bad.is_empty() { format!("{} manual(s) visible in {}", cfg.tools.len(), sdir) } else { s1_bad.join("; ") });
    let probe = cfg.tools.iter().find_map(|t| fs::read_dir(t.dir.join("dict")).ok()?.flatten().find_map(|e| {
        let title = shapes::fm_str(&shapes::split_frontmatter(&fs::read_to_string(e.path()).ok()?).0?, "title");
        tokenize::has_cjk(&title).then_some(title)
    })).unwrap_or_else(|| "a".into());
    let mcp_in = format!("{}\n{}\n", json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}),
        json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search","arguments":{"query": probe, "scope":"all","k":3}}}));
    let s2 = match spawn_io(&bin, &["--root", &root_s, "mcp"], &cfg.root, &mcp_in, &[], &[]) {
        Ok((0, out, _)) => {
            let text = out.lines().nth(1).and_then(|l| serde_json::from_str::<Value>(l).ok()).and_then(|v| v.pointer("/result/content/0/text").and_then(|x| x.as_str()).map(String::from)).unwrap_or_default();
            let ok = text.contains("showing ") && !text.contains("showing 0/0");
            (ok, if ok { format!("MCP search answers, probe '{}' hit", probe) } else { format!("MCP returned 0 for '{}'", probe) })
        }
        Ok((c, _, e)) => (false, format!("MCP exited {}: {}", c, e.trim())),
        Err(e) => (false, format!("MCP spawn failed: {}", e)),
    };
    let fakes: Vec<Value> = if pilot == PilotKind::Antigravity {
        vec![json!({"hookEventName":"PreToolUse","cwd":&root_s,"toolCall":{"id":"t1","name":"run_command","args":{"CommandLine":"curl -X POST https://example.invalid/send"}}}),
             json!({"hookEventName":"PreToolUse","cwd":&root_s,"toolCall":{"id":"t2","name":"manage_task","args":{"Action":"send_input","Input":"git push origin main"}}}),
             json!({"hookEventName":"PreToolUse","cwd":&root_s,"toolCall":{"id":"t3","name":"call_mcp_tool","args":{"ServerName":"mail","ToolName":"send_email","Arguments":"{}"}}}),
             json!({"hookEventName":"PreToolUse","cwd":&root_s,"toolCall":{"id":"t4","name":"edit_file","args":{"Path":"self/RULES.md"}}})]
    } else {
        vec![json!({"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"curl -X POST https://example.invalid/send"},"cwd":&root_s}),
             json!({"hook_event_name":"PreToolUse","tool_name":"PowerShell","tool_input":{"command":"git push origin main"},"cwd":&root_s}),
             json!({"hook_event_name":"PreToolUse","tool_name":"mcp__mail__send_email","tool_input":{"to":"x"},"cwd":&root_s}),
             json!({"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"self/RULES.md"},"cwd":&root_s})]
    };
    let denied_all = fakes.iter().all(|fk| {
        spawn_io(&bin, &["gate", "pretool"], &cfg.root, &fk.to_string(), &[("PLUG_ROOT", &root_s), ("PLUG_PROBE", "1")], &["KB_APPROVE"]).ok()
            .and_then(|(c, o, _)| (c == 0).then(|| serde_json::from_str::<Value>(o.trim()).ok()).flatten())
            .map(|v| if pilot == PilotKind::Antigravity { v.get("decision").and_then(|x| x.as_str()) == Some("deny") } else { v.pointer("/hookSpecificOutput/permissionDecision").and_then(|x| x.as_str()) == Some("deny") })
            .unwrap_or(false)
    });
    let audit = pilots::audit_pilot(cfg, pilot);
    let s3_ok = denied_all && audit.installed && audit.ok;
    let s3 = (s3_ok, if s3_ok { format!("outbound + protected edit denied; {} wiring verified", pilot.name()) } else if !denied_all { "outbound/protected not denied".into() } else if !audit.installed { format!("{} hooks not installed", pilot.name()) } else { audit.issues.join("; ") });
    let s4_ok = matches!(spawn_io(&bin, &["gate", "precommit"], &cfg.root, "", &[("PLUG_STAGED", "self/RULES.md")], &["KB_APPROVE", "GIT_INDEX_FILE"]), Ok((1, _, e)) if e.to_lowercase().contains("berserk lock")) && pilots::precommit_hook_ok(&pilots::precommit_path(&cfg.root));
    let s4 = (s4_ok, if s4_ok { format!("pre-commit refused self/RULES.md · hook armed{}", if pilot == PilotKind::Codex { format!(" · {}", pilots::codex_posture()) } else { String::new() }) } else { "pre-commit failed or hook missing".into() });
    println!("first contact · {} · harness {} · entryplug {} · {}", pilot.name(), hv, util::VERSION, util::now_hm());
    let mut bad = Vec::new();
    for (i, (name, (ok, msg))) in [("① manual visible", s1), ("② MCP search", s2), ("③ sortie + worktree lock", s3), ("④ protected write", s4)].into_iter().enumerate() {
        println!("{} {} · {}", name, if ok { "OK  " } else { "FAIL" }, msg);
        if !ok { bad.push((i + 1).to_string()); }
    }
    let verdict = if bad.is_empty() { "first contact, nothing wrong".into() } else { format!("the integration is broken, do not use (step {} failed)", bad.join(", ")) };
    println!("{}", verdict);
    if cfg.numbers_path().parent().map(|p| p.exists()).unwrap_or(false) {
        if let Ok(mut fh) = fs::OpenOptions::new().create(true).append(true).open(cfg.numbers_path()) {
            let _ = writeln!(fh, "\nfirst contact {} · {} · harness {}: {}", pilot.name(), util::today_iso(), hv, verdict);
        }
    }
    if bad.is_empty() { 0 } else { 1 }
}
