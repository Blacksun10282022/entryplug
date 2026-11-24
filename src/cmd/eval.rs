use crate::config::Config;
use crate::domain::tokenize;
use crate::store::search::{self, SearchOpts};
use regex::Regex;
use serde::Deserialize;
use std::collections::HashSet;
use std::fs;
use std::path::Path;

#[derive(Debug, Deserialize)]
struct YamlGoldset { #[serde(default = "d_scope")] scope: String, #[serde(default)] cases: Vec<YamlCase> }
fn d_scope() -> String { "corpus".into() }

#[derive(Debug, Deserialize)]
struct YamlCase { id: Option<String>, q: serde_yaml::Value, #[serde(default)] expect: Vec<String>, lang: Option<String>, scope: Option<String>, per_doc: Option<usize> }

struct EvalCase { id: String, queries: Vec<String>, expect: Vec<String>, any_match: bool, lang: String, scope: String, per_doc: usize }

fn load_cases(path: &Path) -> Result<Vec<EvalCase>, String> {
    let raw = fs::read_to_string(path).map_err(|e| format!("read {}: {}", path.display(), e))?;
    if path.extension().and_then(|s| s.to_str()).map(|s| s.eq_ignore_ascii_case("md")).unwrap_or(false) {
        let re_bv = Regex::new(r"BV1[0-9A-Za-z]{9}").unwrap();
        return Ok(raw.lines().filter_map(|line| {
            let t = line.trim();
            if !t.starts_with('|') { return None; }
            let c: Vec<&str> = t.trim_matches('|').split('|').map(str::trim).collect();
            if c.len() < 4 || !c[0].starts_with('G') || c[0].len() < 2 || !c[0][1..].chars().all(|ch| ch.is_ascii_digit()) { return None; }
            let expect: Vec<String> = re_bv.find_iter(c[3]).map(|m| m.as_str().into()).collect();
            if c[2].is_empty() || expect.is_empty() { return None; }
            let any_match = expect.len() > 1 || c[3].contains("任一") || c[3].contains("另有");
            Some(EvalCase { id: c[0].into(), queries: vec![c[2].into()], expect, any_match, lang: if tokenize::has_cjk(c[2]) { "zh" } else { "en" }.into(), scope: "corpus".into(), per_doc: 1 })
        }).collect());
    }
    let gs: YamlGoldset = serde_yaml::from_str(&raw).map_err(|e| format!("parse {}: {}", path.display(), e))?;
    Ok(gs.cases.into_iter().filter_map(|c| {
        let queries: Vec<String> = match c.q {
            serde_yaml::Value::String(s) => vec![s],
            serde_yaml::Value::Sequence(seq) => seq.into_iter().filter_map(|v| v.as_str().map(String::from)).collect(),
            _ => Vec::new(),
        };
        if queries.is_empty() { return None; }
        let joined = queries.join(" ");
        Some(EvalCase {
            id: c.id.unwrap_or_else(|| joined.chars().take(24).collect()),
            lang: c.lang.unwrap_or_else(|| if tokenize::has_cjk(&joined) { "zh" } else { "en" }.into()),
            scope: c.scope.unwrap_or_else(|| gs.scope.clone()),
            per_doc: c.per_doc.unwrap_or(1), expect: c.expect, any_match: false, queries,
        })
    }).collect())
}

pub fn run(cfg: &Config, goldset: &Path, k: usize) -> i32 {
    let cases = match load_cases(goldset) {
        Ok(c) if !c.is_empty() => c,
        Ok(_) => { println!("eval: the gold set has no cases"); return 1; }
        Err(e) => { eprintln!("eval: {}", e); return 1; }
    };
    let mut results = Vec::new();
    for c in cases {
        let opts = SearchOpts { queries: c.queries, scope: c.scope, k, per_doc: c.per_doc, check_stale: false, record_telemetry: false, ..Default::default() };
        let res = match search::search(cfg, &opts) { Ok(r) => r, Err(e) => { println!("eval: {}", e); return 1; } };
        let hits: HashSet<String> = res.rows.iter().flat_map(|r| [r.doc.clone(), r.id.clone()]).collect();
        let exp: HashSet<String> = c.expect.into_iter().collect();
        let matched = exp.iter().filter(|e| hits.contains(*e) || hits.iter().any(|h| h.contains(e.as_str()))).count();
        let rec = if exp.is_empty() { 0.0 } else if c.any_match { if matched > 0 { 1.0 } else { 0.0 } } else { matched as f64 / exp.len() as f64 };
        println!("{:<24} {}  recall@{} {:.2}  candidates {}", &c.id.chars().take(24).collect::<String>(), c.lang, k, rec, res.total);
        results.push((c.lang, rec));
    }
    let mean = |xs: &[f64]| (!xs.is_empty()).then(|| xs.iter().sum::<f64>() / xs.len() as f64);
    let all: Vec<f64> = results.iter().map(|r| r.1).collect();
    let zh_v: Vec<f64> = results.iter().filter(|r| r.0 == "zh").map(|r| r.1).collect();
    let en_v: Vec<f64> = results.iter().filter(|r| r.0 == "en").map(|r| r.1).collect();
    let (zh, en) = (mean(&zh_v), mean(&en_v));
    println!("recall@{} {:.2} · n={} · zh {} (n={}) · en {} (n={})", k, mean(&all).unwrap_or(0.0), results.len(),
        zh.map(|v| format!("{:.2}", v)).unwrap_or_else(|| "-".into()), zh_v.len(), en.map(|v| format!("{:.2}", v)).unwrap_or_else(|| "-".into()), en_v.len());
    if zh == Some(0.0) { println!("ERROR recall on Chinese queries is zero — tokenizer or index is broken"); return 1; }
    if let (Some(z), Some(e)) = (zh, en) { if z < 0.5 * e { println!("WARNING Chinese recall is far below English ({:.2} vs {:.2})", z, e); } }
    0
}
