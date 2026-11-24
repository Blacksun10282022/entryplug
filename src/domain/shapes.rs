use crate::domain::entries::{parse_observations, Observation};
use chrono::NaiveDate;
use regex::Regex;
use serde_yaml::Value;
use std::collections::{BTreeMap, HashSet};
use std::path::Path;
use std::sync::OnceLock;

pub type Fm = BTreeMap<String, Value>;
#[derive(Debug, Clone, PartialEq, Eq)] pub enum RecordKind { Note, Decision }
#[derive(Debug, Clone)] pub struct ParsedFile { pub fm: Fm, pub body: String, pub errors: Vec<String>, pub sections: BTreeMap<String, String>, pub links: Vec<String>, pub obs: Vec<Observation> }
#[derive(Debug, Clone)] pub struct RuleLine { pub id: String, pub dated: bool, pub review: Option<String> }
#[derive(Debug, Clone)] pub struct RuleSection { pub name: String, pub expires: Option<String>, pub review: Option<String>, pub lines: Vec<RuleLine> }
#[derive(Debug, Clone)] pub struct ParsedRules { pub header: BTreeMap<String, String>, pub sections: Vec<RuleSection>, pub ids: HashSet<String>, pub retired_ids: HashSet<String> }
#[derive(Debug, Clone)] pub struct ParsedDoc { pub id: String, pub title: String, pub date: String, pub kind: String, pub speaker: String, pub series: String, pub units: Vec<(usize, usize, String, String)>, pub text: String }

pub fn fm_str(fm: &Fm, key: &str) -> String {
    match fm.get(key) { Some(Value::String(s)) => s.trim().into(), Some(Value::Number(n)) => n.to_string(), Some(Value::Bool(b)) => b.to_string(), _ => String::new() }
}
pub fn fm_list(fm: &Fm, key: &str) -> Vec<String> {
    match fm.get(key) {
        Some(Value::Sequence(seq)) => seq.iter().filter_map(|v| match v { Value::String(s) => Some(s.trim().into()), Value::Number(n) => Some(n.to_string()), _ => None }).collect(),
        _ => Vec::new(),
    }
}

pub fn split_frontmatter(text: &str) -> (Option<Fm>, String, Option<String>) {
    let clean = text.strip_prefix('\u{feff}').unwrap_or(text);
    if !clean.starts_with("---") { return (None, clean.into(), None); }
    let norm = clean.replace("\r\n", "\n");
    let Some(rest) = norm.strip_prefix("---").and_then(|r| r.find('\n').filter(|&i| r[..i].trim().is_empty()).map(|i| &r[i + 1..])) else { return (None, norm, None); };
    let (mut end_idx, mut body_start, mut pos) = (None, rest.len(), 0);
    for line in rest.split_inclusive('\n') {
        if line.trim() == "---" { end_idx = Some(pos); body_start = pos + line.len(); break; }
        pos += line.len();
    }
    let Some(end) = end_idx else { return (None, norm, Some("frontmatter has no closing ---".into())); };
    let body = rest[body_start..].to_string();
    let val: Value = match serde_yaml::from_str(&rest[..end]) {
        Ok(Value::Null) => return (Some(BTreeMap::new()), body, None),
        Ok(v) => v,
        Err(e) => return (None, body, Some(format!("frontmatter is not valid YAML: {}", e.to_string().lines().next().unwrap_or("")))),
    };
    let Some(map) = val.as_mapping() else { return (None, body, Some("frontmatter is not a mapping".into())); };
    static RE_ISO: OnceLock<Regex> = OnceLock::new();
    let re_iso = RE_ISO.get_or_init(|| Regex::new(r"^\d{4}-\d{2}-\d{2}$").unwrap());
    let mut fm = BTreeMap::new();
    for (k, v) in map {
        let Some(ks) = k.as_str() else { continue };
        if let Some(s) = v.as_str().map(str::trim) {
            if matches!(ks, "due" | "date" | "expires") && re_iso.is_match(s) && NaiveDate::parse_from_str(s, "%Y-%m-%d").is_err() {
                return (None, body, Some(format!("frontmatter holds an impossible date: {}", s)));
            }
        }
        fm.insert(ks.into(), v.clone());
    }
    if matches!(fm.get("base"), Some(Value::Number(_))) {
        if let Some(raw_b) = rest[..end].lines().find_map(|l| l.trim_start().strip_prefix("base:").map(|r| r.split('#').next().unwrap_or("").trim().trim_matches(&['"', '\''][..]).to_string())).filter(|s| !s.is_empty()) {
            fm.insert("base".into(), Value::String(raw_b));
        }
    }
    (Some(fm), body, None)
}

pub fn section_blocks(lines: &[&str]) -> Vec<(String, usize, Vec<String>)> {
    static OPEN: OnceLock<Regex> = OnceLock::new();
    static CLOSE: OnceLock<Regex> = OnceLock::new();
    let open = OPEN.get_or_init(|| Regex::new(r"^(`{3,})[^`]*$").unwrap());
    let close = CLOSE.get_or_init(|| Regex::new(r"^(`{3,})[ \t]*$").unwrap());
    let (mut out, mut fence) = (vec![(String::new(), 0, Vec::new())], 0usize);
    for (i, line) in lines.iter().enumerate() {
        if fence == 0 { if let Some(c) = open.captures(line) { fence = c[1].len(); } }
        else if close.captures(line).map(|c| c[1].len() >= fence).unwrap_or(false) { fence = 0; }
        if fence == 0 { if let Some(h) = line.strip_prefix("## ") { out.push((h.trim().into(), i + 1, Vec::new())); continue; } }
        out.last_mut().unwrap().2.push((*line).into());
    }
    out
}

pub fn sections(body: &str) -> BTreeMap<String, String> {
    let ls: Vec<&str> = body.lines().collect();
    let mut acc: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for (h, _, v) in section_blocks(&ls) { acc.entry(h).or_default().extend(v); }
    acc.into_iter().map(|(k, v)| (k, v.join("\n").trim().into())).collect()
}
pub fn links(body: &str) -> Vec<String> {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]").unwrap()).captures_iter(body).map(|c| c[1].trim().into()).collect()
}
pub fn parse_day(s: &str) -> Option<NaiveDate> { let t = s.trim(); (t.len() == 10).then(|| NaiveDate::parse_from_str(t, "%Y-%m-%d").ok()).flatten() }
pub fn due_date(fm: &Fm) -> Option<NaiveDate> { let s = fm_str(fm, "due"); (!s.is_empty()).then(|| parse_day(&s)).flatten() }
pub fn record_kind(fm: &Fm) -> RecordKind {
    match fm_str(fm, "kind").to_lowercase().as_str() {
        "note" => RecordKind::Note, "decision" => RecordKind::Decision,
        _ => if matches!(fm_str(fm, "tool").to_lowercase().as_str(), "" | "none") { RecordKind::Note } else { RecordKind::Decision },
    }
}
pub fn outcome_owed(fm: &Fm, age: i64, today: NaiveDate, default_days: i64, superseded: bool) -> bool {
    if superseded || record_kind(fm) == RecordKind::Note || !fm_str(fm, "outcome").is_empty() { return false; }
    due_date(fm).map(|d| d <= today).unwrap_or(default_days > 0 && age >= default_days)
}
pub fn has_four_elements(secs: &BTreeMap<String, String>) -> bool {
    let basis = secs.get("依据").map(String::as_str).unwrap_or("");
    ["依据", "最强反证", "什么会改判"].iter().all(|h| !secs.get(*h).map(|v| v.trim()).unwrap_or("").is_empty())
        && (basis.contains("上次") || basis.contains("records/") || basis.contains("无类似记录"))
}

pub fn validate(shape: &str, fm: Option<&Fm>, body: &str) -> Vec<String> {
    let Some(fm) = fm else { return vec!["no frontmatter".into()] };
    let (mut errs, secs) = (Vec::new(), sections(body));
    let req = |ks: &[&str], e: &mut Vec<String>| for k in ks {
        let empty = matches!(fm.get(*k), None | Some(Value::Null)) || matches!(fm.get(*k), Some(Value::String(s)) if s.trim().is_empty()) || matches!(fm.get(*k), Some(Value::Sequence(s)) if s.is_empty());
        if empty { e.push(format!("missing required field {}", k)); }
    };
    let unk = |ok: &[&str], e: &mut Vec<String>| for k in fm.keys() { if !ok.contains(&k.as_str()) { e.push(format!("unknown field {} (shape v2 does not know it)", k)); } };
    match shape {
        "entry" => {
            req(&["kind", "title"], &mut errs);
            unk(&["kind", "title", "aliases", "legacy_id", "origin", "situation", "when_not", "stance"], &mut errs);
            let k = fm_str(fm, "kind");
            if !matches!(k.as_str(), "concept" | "method" | "playbook") { errs.push(format!("kind must be concept/method/playbook, got '{}'", k)); }
            if k == "concept" && fm_list(fm, "aliases").is_empty() { errs.push("a concept needs at least one alias".into()); }
            if k == "playbook" { for f in ["situation", "when_not", "stance"] { if fm_str(fm, f).is_empty() { errs.push(format!("playbook is missing {}", f)); } } }
            if fm.get("aliases").map(|v| !v.is_sequence()).unwrap_or(false) { errs.push("aliases must be a list".into()); }
        }
        "record" => {
            if record_kind(fm) == RecordKind::Note {
                if fm_str(fm, "situation").is_empty() && fm_str(fm, "title").is_empty() && body.trim().is_empty() { errs.push("note record needs situation, title, or body".into()); }
            } else {
                req(&["tool", "by", "situation", "verdict"], &mut errs);
                unk(&["kind", "tool", "by", "situation", "verdict", "chosen", "outcome", "due", "supersedes", "extends", "topic", "tags", "status", "date"], &mut errs);
                for h in ["依据", "最强反证", "什么会改判"] { if !secs.contains_key(h) { errs.push(format!("body is missing section ## {}", h)); } }
            }
            if !fm_str(fm, "due").is_empty() && due_date(fm).is_none() { errs.push("due must be YYYY-MM-DD".into()); }
        }
        "proposal" => {
            req(&["target", "base", "from"], &mut errs);
            unk(&["target", "base", "from", "format", "kind"], &mut errs);
            for h in ["改成什么", "为什么", "最强反证"] { if !secs.contains_key(h) { errs.push(format!("body is missing section ## {}", h)); } }
        }
        "material" => {
            req(&["date"], &mut errs);
            static RD: OnceLock<Regex> = OnceLock::new();
            let d = fm_str(fm, "date");
            if !d.is_empty() && !RD.get_or_init(|| Regex::new(r"^\d{4}-\d{2}(?:-\d{2})?").unwrap()).is_match(&d) { errs.push("date must be YYYY-MM-DD".into()); }
        }
        "manual" => req(&["name", "description"], &mut errs),
        _ => {}
    }
    errs
}

pub fn parse_file(text: &str, area: &str) -> ParsedFile {
    let shape = match area { "dict" | "playbook" => Some("entry"), "record" => Some("record"), "proposal" => Some("proposal"), "material" => Some("material"), "manual" => Some("manual"), _ => None };
    let (fm_opt, body, err) = split_frontmatter(text);
    let mut errors: Vec<String> = err.into_iter().collect();
    if let Some(sh) = shape { errors.extend(validate(sh, fm_opt.as_ref(), &body)); }
    let obs = if shape == Some("entry") { parse_observations(&body) } else { Vec::new() };
    ParsedFile { fm: fm_opt.unwrap_or_default(), sections: sections(&body), links: links(&body), obs, body, errors }
}

pub fn parse_rules(text: &str) -> ParsedRules {
    static RE_HDR: OnceLock<Regex> = OnceLock::new(); static RE_RULE: OnceLock<Regex> = OnceLock::new();
    static RE_DATE: OnceLock<Regex> = OnceLock::new(); static RE_EXP: OnceLock<Regex> = OnceLock::new(); static RE_REV: OnceLock<Regex> = OnceLock::new();
    let (re_hdr, re_rule, re_date, re_exp, re_rev) = (
        RE_HDR.get_or_init(|| Regex::new(r"(model|reviewed)\s*[:：]\s*(\S+)").unwrap()),
        RE_RULE.get_or_init(|| Regex::new(r"^\s*[-*]\s*([A-Z]{1,2}\d{1,3}[a-z]?)\s*[·・:：]\s*(.*)$").unwrap()),
        RE_DATE.get_or_init(|| Regex::new(r"\d{4}-\d{2}(?:-\d{2})?").unwrap()),
        RE_EXP.get_or_init(|| Regex::new(r"到期\s*(\d{4}-\d{2}-\d{2})").unwrap()),
        RE_REV.get_or_init(|| Regex::new(r"复核\s*(\d{4}-\d{2})").unwrap()),
    );
    let (mut header, mut secs) = (BTreeMap::new(), Vec::<RuleSection>::new());
    for line in text.lines() {
        if !line.starts_with('#') { for c in re_hdr.captures_iter(line) { header.entry(c[1].into()).or_insert_with(|| c[2].into()); } }
        if let Some(name) = line.strip_prefix("## ").map(str::trim) {
            secs.push(RuleSection { name: name.into(), expires: re_exp.captures(name).map(|c| c[1].into()), review: re_rev.captures(name).map(|c| c[1].into()), lines: Vec::new() });
        } else if let (Some(cur), Some(c)) = (secs.last_mut(), re_rule.captures(line)) {
            let b = c[2].trim();
            cur.lines.push(RuleLine { id: c[1].into(), dated: re_date.is_match(b), review: re_rev.captures(b).map(|r| r[1].into()) });
        }
    }
    let ids = secs.iter().flat_map(|s| s.lines.iter().map(|l| l.id.clone())).collect();
    let retired_ids = secs.iter().filter(|s| s.name.contains("退役")).flat_map(|s| s.lines.iter().map(|l| l.id.clone())).collect();
    ParsedRules { header, sections: secs, ids, retired_ids }
}

pub fn rule_citations(text: &str, ids: &HashSet<String>) -> Vec<(String, bool)> {
    let mut pre: Vec<String> = ids.iter().map(|i| i.chars().take_while(|c| c.is_ascii_uppercase()).collect()).filter(|p: &String| !p.is_empty()).collect();
    pre.sort(); pre.dedup();
    let Ok(re) = (!pre.is_empty()).then(|| Regex::new(&format!(r"(?:^|[^A-Za-z0-9])((?:{})\d{{1,3}}[a-z]?)(?:$|[^A-Za-z0-9])", pre.join("|")))).transpose() else { return Vec::new() };
    let Some(re) = re else { return Vec::new() };
    let (mut out, mut head) = (Vec::new(), String::new());
    for line in text.lines() {
        if line.trim_start().starts_with("##") { head = line.trim_start().trim_start_matches('#').trim().into(); }
        let mut s = 0;
        while s < line.len() {
            let Some(m) = re.captures(&line[s..]).and_then(|c| c.get(1)) else { break };
            let end = s + m.end();
            out.push((m.as_str().into(), line.contains("RULES") || head.contains("规则") || line[end..].starts_with(" · ")));
            s = end;
        }
    }
    out
}
pub fn rule_refs(text: &str, ids: &HashSet<String>) -> Vec<String> { rule_citations(text, ids).into_iter().filter(|(r, c)| *c || ids.contains(r)).map(|(r, _)| r).collect() }

pub fn parse_doc(text: &str, path: &Path) -> ParsedDoc {
    static RE_SEP: OnceLock<Regex> = OnceLock::new(); static RE_HEAD: OnceLock<Regex> = OnceLock::new();
    static RE_PARA: OnceLock<Regex> = OnceLock::new(); static RE_SER: OnceLock<Regex> = OnceLock::new();
    let (re_sep, re_head, re_para, re_ser) = (
        RE_SEP.get_or_init(|| Regex::new(r"^={3,}(?:\s*(.*?)\s*={3,})?\s*$").unwrap()),
        RE_HEAD.get_or_init(|| Regex::new(r"^(?:[A-Za-z_]+|标题|来源|日期|主讲)\s*[:：]\s*(.*)$").unwrap()),
        RE_PARA.get_or_init(|| Regex::new(r"^\[(\d+:\d{2}(?::\d{2})?|¶\d+)\]\s*(.*)$").unwrap()),
        RE_SER.get_or_init(|| Regex::new(r"^(?:【([^】]+)】|(.+?)\s*[｜|·—\-：:]\s*.+)$").unwrap()),
    );
    let (fm_opt, body, _) = split_frontmatter(text);
    let lines: Vec<&str> = text.lines().collect();
    let (mut meta, mut units) = (BTreeMap::<String, String>::new(), Vec::new());
    let seps: Vec<usize> = lines.iter().enumerate().filter_map(|(i, l)| re_sep.is_match(l).then_some(i)).collect();
    if let Some(fm) = fm_opt {
        for k in ["id", "title", "date", "kind", "speaker", "series"] { let v = fm_str(&fm, k); if !v.is_empty() { meta.insert(k.into(), v); } }
        let fml = lines.len().saturating_sub(body.lines().count());
        units.push((fml + 1, lines.len().max(fml + 1), String::new(), lines[fml.min(lines.len())..].join("\n")));
    } else if !seps.is_empty() {
        for l in &lines[..seps[0]] {
            if let Some(c) = re_head.captures(l) {
                let rk = l.split(&[':', '：'][..]).next().unwrap_or("").trim().to_lowercase();
                meta.insert(match rk.as_str() { "标题" => "title", "日期" => "date", "bvid" => "id", "主讲" => "speaker", o => o }.into(), c[1].trim().into());
            }
        }
        let start = seps.iter().copied().find(|&i| re_sep.captures(lines[i]).and_then(|c| c.get(1)).map(|m| m.as_str().contains("纯文本")).unwrap_or(false)).unwrap_or(seps[0]);
        let end = seps.iter().copied().find(|&s| s > start).unwrap_or(lines.len());
        for (i, l) in lines.iter().enumerate().take(end).skip(start + 1) {
            if let Some(c) = re_para.captures(l) { if !c[2].trim().is_empty() { units.push((i + 1, i + 1, c[1].into(), c[2].trim().into())); } }
        }
        if units.is_empty() && start + 1 < end { let b = lines[start + 1..end].join("\n"); if !b.trim().is_empty() { units.push((start + 2, end, String::new(), b)); } }
        let is_lec = meta.contains_key("id") || units.first().map(|u| !u.2.is_empty()).unwrap_or(false);
        meta.entry("kind".into()).or_insert_with(|| if is_lec { "lecture" } else { "text" }.into());
    } else { units.push((1, lines.len().max(1), String::new(), lines.join("\n"))); }
    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("doc").to_string();
    let title = meta.get("title").cloned().filter(|s| !s.is_empty()).unwrap_or_else(|| lines.first().map(|l| l.trim_start_matches("# ").trim().into()).filter(|s: &String| !s.is_empty()).unwrap_or_else(|| stem.clone()));
    let id = meta.get("id").cloned().filter(|s| !s.is_empty()).unwrap_or(stem);
    let series = meta.get("series").cloned().filter(|s| !s.is_empty()).unwrap_or_else(|| re_ser.captures(&title).and_then(|c| c.get(1).or_else(|| c.get(2))).map(|m| m.as_str().trim().into()).unwrap_or_default());
    let joined = units.iter().map(|u| u.3.as_str()).collect::<Vec<_>>().join("\n");
    ParsedDoc { id, title, date: meta.remove("date").unwrap_or_default(), kind: meta.remove("kind").unwrap_or_else(|| "text".into()), speaker: meta.remove("speaker").unwrap_or_default(), series, units, text: joined }
}
