use crate::config::Config;
use crate::domain::tokenize;
use crate::store::{self, index, telemetry};
use rusqlite::{params_from_iter, types::Value as SqlVal, Connection};
use serde::Serialize;
use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone)]
pub struct SearchOpts { pub queries: Vec<String>, pub scope: String, pub tool: Option<String>, pub kind: Option<String>, pub date_from: Option<String>, pub date_to: Option<String>, pub series: Option<String>, pub history: bool, pub view: String, pub k: usize, pub per_doc: usize, pub check_stale: bool, pub record_telemetry: bool }
impl Default for SearchOpts { fn default() -> Self { Self { queries: Vec::new(), scope: "tools".into(), tool: None, kind: None, date_from: None, date_to: None, series: None, history: false, view: "compact".into(), k: 8, per_doc: 2, check_stale: true, record_telemetry: false } } }
#[derive(Debug, Clone, Serialize)]
pub struct SearchRow { pub id: String, pub doc: String, pub title: String, pub file: String, pub lstart: i64, pub lend: i64, pub pos: String, pub scope: String, pub tool: String, pub kind: String, pub date: String, pub series: String, pub excerpt: String, pub verdict: String, pub outcome: String, pub supersedes: String }
#[derive(Debug, Clone, Serialize)]
pub struct SearchResult { pub rows: Vec<SearchRow>, pub total: usize, pub stale: Option<String>, pub view: String }

fn load_aliases(con: &Connection) -> HashMap<String, Vec<String>> { con.query_row("SELECT value FROM meta WHERE key='aliases'", [], |r| r.get::<_, String>(0)).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default() }

fn run_single_db(con: &Connection, fts_expr: &str, opts: &SearchOpts, is_books: bool, limit: usize) -> Result<Vec<SearchRow>, String> {
    let mut sql = if is_books {
        "SELECT c.id, c.doc, c.title, c.file, c.lstart, c.lend, c.pos, c.scope, c.tool, c.kind, c.date, c.series, c.excerpt, '', '', '' FROM fts JOIN chunks c ON c.rowid = fts.rowid WHERE fts MATCH ?".to_string()
    } else {
        "SELECT c.id, c.doc, c.title, c.file, c.lstart, c.lend, c.pos, c.scope, c.tool, c.kind, c.date, c.series, c.excerpt, COALESCE(r.verdict,''), COALESCE(r.outcome,''), COALESCE(r.supersedes,'') FROM fts JOIN chunks c ON c.rowid = fts.rowid LEFT JOIN records r ON r.file = c.file WHERE fts MATCH ?".to_string()
    };
    let mut vals: Vec<SqlVal> = vec![SqlVal::Text(fts_expr.into())];
    if !is_books {
        if opts.scope == "memory" { sql.push_str(" AND (c.kind = 'memory' OR c.kind LIKE 'memory:%')"); }
        else if opts.scope != "all" { sql.push_str(" AND c.scope = ?"); vals.push(SqlVal::Text(opts.scope.clone())); }
        if !opts.history { sql.push_str(" AND (r.superseded_by IS NULL OR r.superseded_by = '')"); }
    }
    for (col, val) in [("c.tool = ?", &opts.tool), ("c.kind = ?", &opts.kind), ("c.date >= ?", &opts.date_from), ("c.date != '' AND c.date <= ?", &opts.date_to)] {
        if let Some(v) = val.as_deref().filter(|s| !s.is_empty()) { sql.push_str(" AND "); sql.push_str(col); vals.push(SqlVal::Text(v.into())); }
    }
    if let Some(s) = opts.series.as_deref().filter(|s| !s.is_empty()) { sql.push_str(" AND c.series LIKE ?"); vals.push(SqlVal::Text(format!("%{}%", s))); }
    if is_books || opts.scope == "corpus" { sql.push_str(" ORDER BY bm25(fts, 20.0, 1.0) LIMIT ?"); }
    else { sql.push_str(" ORDER BY bm25(fts, 20.0, 1.0) * (CASE WHEN c.scope='tools' AND c.kind IN ('memory:verified','memory:caution','rules','manual') THEN 1.35 WHEN c.scope='tools' AND (c.kind='memory' OR c.kind LIKE 'memory:%') THEN 1.20 ELSE 1.0 END) * (CASE WHEN c.scope IN ('tools','logs') AND c.date >= date('now','-30 days') THEN 1.10 WHEN c.scope IN ('tools','logs') AND c.date >= date('now','-90 days') THEN 1.04 ELSE 1.0 END) LIMIT ?"); }
    vals.push(SqlVal::Integer(limit as i64));

    let mut st = con.prepare(&sql).map_err(|e| format!("search prepare: {}", e))?;
    let rows = st.query_map(params_from_iter(vals), |r| Ok(SearchRow {
        id: r.get(0)?, doc: r.get(1)?, title: r.get(2)?, file: r.get(3)?, lstart: r.get(4)?, lend: r.get(5)?,
        pos: r.get(6)?, scope: r.get(7)?, tool: r.get(8)?, kind: r.get(9)?, date: r.get(10)?, series: r.get(11)?,
        excerpt: r.get(12)?, verdict: r.get(13)?, outcome: r.get(14)?, supersedes: r.get(15)?,
    })).map_err(|e| format!("search query: {}", e))?.filter_map(Result::ok).collect();
    Ok(rows)
}

pub fn search(cfg: &Config, opts: &SearchOpts) -> Result<SearchResult, String> {
    if !cfg.shape_ok() { return Err(format!("unknown shape_version {} — refusing to run", cfg.shape_version)); }
    let (k, per_doc) = (opts.k.clamp(1, 60), opts.per_doc.clamp(1, 5));
    let lim = (k * 25).max(200);
    let stale = (opts.check_stale && opts.scope != "books").then(|| index::stale_lag(cfg)).flatten();
    let state_con = (opts.scope != "books").then(|| store::open_ro(&cfg.index_path())).transpose()?;
    let aliases = state_con.as_ref().map(load_aliases).unwrap_or_else(|| store::open_ro(&cfg.index_path()).ok().map(|c| load_aliases(&c)).unwrap_or_default());
    let books_con = if opts.scope == "books" { Some(store::open_ro(&cfg.books_index_path())?) }
        else if opts.scope == "all" && cfg.books_index_path().is_file() { store::open_ro(&cfg.books_index_path()).ok() } else { None };

    let mut lists = Vec::new();
    for raw_q in &opts.queries {
        let (Some(p_expr), fb) = tokenize::build_fts_queries(raw_q, &aliases) else { continue };
        let mut hits = Vec::new();
        for (con_opt, is_b) in [(&state_con, false), (&books_con, true)] {
            if let Some(con) = con_opt {
                let mut r = run_single_db(con, &p_expr, opts, is_b, lim)?;
                if r.len() < k { if let Some(f) = &fb { r.extend(run_single_db(con, f, opts, is_b, lim)?); } }
                hits.extend(r);
            }
        }
        lists.push(hits);
    }

    let (mut seen, mut doc_cnt, mut total, mut merged, mut curs) = (HashSet::new(), HashMap::<String, usize>::new(), 0, Vec::new(), vec![0; lists.len()]);
    loop {
        let mut moved = false;
        for (qi, list) in lists.iter().enumerate() {
            while curs[qi] < list.len() {
                let row = &list[curs[qi]]; curs[qi] += 1; moved = true;
                if !seen.insert(format!("{}:{}", row.file, row.id)) { continue; }
                total += 1;
                if merged.len() < k {
                    let c = doc_cnt.entry(row.doc.clone()).or_insert(0);
                    if *c < per_doc { *c += 1; merged.push(row.clone()); break; }
                }
            }
        }
        if !moved { break; }
    }
    if total == 0 && opts.record_telemetry && cfg.kb_dir().is_dir() {
        telemetry::log_event(cfg, "zero_hit", &format!("scope={} q={}", opts.scope, opts.queries.join(" | ")), "", "");
    }
    Ok(SearchResult { rows: merged, total, stale, view: opts.view.clone() })
}

pub fn format_rows(res: &SearchResult) -> String {
    let mut lines = Vec::new();
    if let Some(s) = &res.stale { lines.push(format!("WARNING index stale ({}) — run plug index then search again", s)); }
    if res.view == "spine" {
        let mut sorted = res.rows.clone();
        sorted.sort_by(|a, b| a.date.cmp(&b.date).then(a.file.cmp(&b.file)));
        let mut seen = HashSet::new();
        for r in sorted {
            if !seen.insert(r.doc.clone()) { continue; }
            let core: String = (if !r.verdict.is_empty() { &r.verdict } else { &r.excerpt }).chars().take(68).collect();
            let mut tail = String::new();
            if !r.outcome.is_empty() { tail.push_str(&format!(" | outcome: {}", r.outcome.chars().take(32).collect::<String>())); }
            if !r.supersedes.is_empty() { tail.push_str(&format!(" | supersedes: {}", r.supersedes)); }
            lines.push(format!("{} | {} [{}] | {}{}", if r.date.is_empty() { "----------" } else { &r.date }, r.file, r.tool, core, tail));
        }
        lines.push(format!("spine showing {}/{}", res.rows.len(), res.total));
        return lines.join("\n");
    }
    for r in &res.rows {
        let pos = if r.pos.is_empty() { String::new() } else { format!(" [{}]", r.pos) };
        lines.push(format!("{} · {} · {}#L{}-L{}{} · {} · {}", r.id, if r.title.is_empty() { &r.doc } else { &r.title }, r.file, r.lstart, r.lend, pos, r.kind, r.excerpt));
    }
    lines.push(format!("showing {}/{}", res.rows.len(), res.total));
    lines.join("\n")
}
