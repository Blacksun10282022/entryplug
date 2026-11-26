use crate::config::{self, Config, WalkFile};
use crate::domain::{entries, quotes, shapes, tokenize};
use crate::store;
use crate::util;
use rayon::prelude::*;
use rusqlite::{params, Connection};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs;
use std::path::Path;

const INDEX_MD_CAP: usize = 36_000;

#[derive(Debug, Clone)]
pub struct ChunkRow { pub id: String, pub doc: String, pub title: String, pub file: String, pub lstart: usize, pub lend: usize, pub pos: String, pub scope: String, pub tool: String, pub kind: String, pub date: String, pub series: String, pub excerpt: String, pub title_tokens: String, pub tokens: String }
#[derive(Debug, Clone)]
pub struct RecordRow { pub file: String, pub doc: String, pub kind: String, pub tool: String, pub by: String, pub situation: String, pub verdict: String, pub chosen: String, pub outcome: String, pub due: String, pub supersedes: String, pub topic: String, pub date: String, pub has_four: i64, pub cites_record: i64, pub rule_refs: String, pub quote_all: i64 }
#[derive(Debug, Clone)]
pub struct PreparedFile { pub file: String, pub sha1: String, pub mtime_ns: i64, pub size: i64, pub area: String, pub sub: String, pub tool: String, pub doc: String, pub chunks: Vec<ChunkRow>, pub record: Option<RecordRow>, pub edges: Vec<(String, String, String)> }
#[derive(Debug, Default)]
pub struct BuildStats { pub indexed_files: usize, pub skipped_files: usize, pub removed_files: usize, pub total_docs: usize, pub total_chunks: usize, pub books_indexed: usize, pub books_chunks: usize }

fn compact_excerpt(s: &str) -> String {
    let one = s.split_whitespace().collect::<Vec<_>>().join(" ");
    let cs: Vec<char> = one.chars().collect();
    if cs.len() <= 120 { one } else { format!("{}…", cs[..119].iter().collect::<String>()) }
}
fn infer_date(rel: &str) -> String {
    Path::new(rel).file_stem().and_then(|s| s.to_str()).and_then(|s| s.get(..10)).filter(|c| shapes::parse_day(c).is_some()).map(String::from).unwrap_or_default()
}
#[allow(clippy::too_many_arguments)]
fn push_chunk(out: &mut Vec<ChunkRow>, id: String, doc: &str, title: &str, file: &str, lstart: usize, lend: usize, pos: String, scope: &str, tool: &str, kind: &str, date: &str, series: &str, excerpt: String, title_tokens: String, tokens: String) {
    out.push(ChunkRow { id, doc: doc.into(), title: title.into(), file: file.into(), lstart, lend: lend.max(lstart), pos, scope: scope.into(), tool: tool.into(), kind: kind.into(), date: date.into(), series: series.into(), excerpt, title_tokens, tokens });
}
#[allow(clippy::too_many_arguments)]
fn chunk_lines(text: &str, base: usize, doc: &str, title: &str, file: &str, scope: &str, tool: &str, kind: &str, date: &str, series: &str, title_tok: &str, out: &mut Vec<ChunkRow>) {
    let (lines, mut cur, mut sl, mut idx): (Vec<&str>, String, usize, usize) = (text.lines().collect(), String::new(), base, 0);
    let mut flush = |c: &mut String, s: usize, e: usize| {
        let tr = c.trim();
        if !tr.is_empty() {
            idx += 1;
            push_chunk(out, format!("{}#{}", doc, idx), doc, title, file, s, e, String::new(), scope, tool, kind, date, series, compact_excerpt(tr), if idx == 1 { title_tok.into() } else { String::new() }, tokenize::tokenize_text(tr));
        }
        c.clear();
    };
    for (i, line) in lines.iter().enumerate() {
        if !cur.is_empty() && cur.len() + line.len() > 1400 { flush(&mut cur, sl, base + i - 1); sl = base + i; }
        if !cur.is_empty() { cur.push('\n'); }
        cur.push_str(line);
    }
    if !lines.is_empty() { flush(&mut cur, sl, base + lines.len() - 1); }
}

pub fn prepare_file(cfg: &Config, wf: &WalkFile, rule_ids: &HashSet<String>) -> Option<PreparedFile> {
    let text = fs::read_to_string(&wf.path).ok()?;
    let (mtime_ns, size, sha1) = (wf.mtime_ns, wf.size, util::sha1_hex(text.as_bytes()));
    let stem = wf.path.file_stem().and_then(|s| s.to_str()).unwrap_or("doc").to_string();
    let (mut chunks, mut record, mut edges) = (Vec::new(), None, Vec::new());

    if wf.area == "corpus" || wf.area == "book" {
        let d = shapes::parse_doc(&text, &wf.path);
        let scope = if wf.area == "book" { "books" } else { "corpus" };
        let ttok = tokenize::tokenize_text(&if wf.area == "book" { format!("{} {} {} {}", d.title, stem, d.series, d.speaker) } else { format!("{} {} {}", d.title, d.series, d.speaker) });
        if d.units.len() > 1 {
            let (mut cur, mut ls, mut le, mut fpos, mut seq) = (String::new(), 0, 0, String::new(), 0usize);
            let mut flush = |c: &mut String, fp: &mut String, ls: usize, le: usize| {
                let t = c.trim();
                if !t.is_empty() {
                    seq += 1;
                    let id = format!("{}#{}", d.id, if fp.is_empty() { seq.to_string() } else { fp.clone() });
                    push_chunk(&mut chunks, id, &d.id, &d.title, &wf.rel, ls, le, fp.clone(), scope, &wf.tool, &d.kind, &d.date, &d.series, compact_excerpt(t), if seq == 1 { ttok.clone() } else { String::new() }, tokenize::tokenize_text(t));
                }
                c.clear(); fp.clear();
            };
            for (uls, ule, upos, ut) in &d.units {
                if !cur.is_empty() && cur.len() + ut.len() > 1100 { flush(&mut cur, &mut fpos, ls, le); }
                if cur.is_empty() { ls = *uls; fpos = upos.clone(); }
                le = *ule; if !cur.is_empty() { cur.push('\n'); } cur.push_str(ut);
            }
            flush(&mut cur, &mut fpos, ls, le);
        } else {
            chunk_lines(&d.text, d.units.first().map(|u| u.0).unwrap_or(1), &d.id, &d.title, &wf.rel, scope, &wf.tool, &d.kind, &d.date, &d.series, &ttok, &mut chunks);
        }
        return Some(PreparedFile { file: wf.rel.clone(), sha1, mtime_ns, size, area: wf.area.clone(), sub: wf.sub.clone(), tool: wf.tool.clone(), doc: d.id, chunks, record, edges });
    }
    if wf.area == "log" {
        let (date, ls) = (infer_date(&wf.rel), text.lines().collect::<Vec<_>>());
        let title = format!("流水 {}", date);
        for (i, (h, st, bls)) in shapes::section_blocks(&ls).into_iter().enumerate() {
            let b = bls.join("\n");
            if !b.trim().is_empty() || !h.is_empty() {
                let tt = tokenize::tokenize_text(&if i == 0 { format!("{} {}", title, h) } else { h.clone() });
                chunk_lines(&b, st + 1, &stem, &title, &wf.rel, "logs", "", "log", &date, &h, &tt, &mut chunks);
            }
        }
        return Some(PreparedFile { file: wf.rel.clone(), sha1, mtime_ns, size, area: wf.area.clone(), sub: wf.sub.clone(), tool: String::new(), doc: stem, chunks, record, edges });
    }

    let p = shapes::parse_file(&text, &wf.area);
    if wf.area == "proposal" && cfg.is_excluded(&shapes::fm_str(&p.fm, "target")) {
        return Some(PreparedFile { file: wf.rel.clone(), sha1, mtime_ns, size, area: wf.area.clone(), sub: wf.sub.clone(), tool: String::new(), doc: stem, chunks, record, edges });
    }
    let doc = if wf.area == "manual" || wf.area == "reading" { format!("{}/{}", wf.tool, stem) } else { stem };
    let fm_sit = shapes::fm_str(&p.fm, "situation");
    let title = [shapes::fm_str(&p.fm, "title"), fm_sit.clone(), shapes::fm_str(&p.fm, "name")].into_iter().find(|s| !s.is_empty()).unwrap_or_else(|| doc.clone());
    let kind = match wf.area.as_str() {
        "dict" | "playbook" => { let k = shapes::fm_str(&p.fm, "kind"); if k.is_empty() { wf.area.clone() } else { k } }
        "record" => if shapes::record_kind(&p.fm) == shapes::RecordKind::Note { "note".into() } else { "record".into() },
        "memory" => { let st = shapes::fm_str(&p.fm, "status"); if st.is_empty() { "memory".into() } else { format!("memory:{}", st) } }
        o => o.into(),
    };
    let tool = if !wf.tool.is_empty() { wf.tool.clone() } else { shapes::fm_str(&p.fm, "tool") };
    let date = { let d = shapes::fm_str(&p.fm, "date"); if !d.is_empty() { d } else { infer_date(&wf.rel) } };
    let topic = shapes::fm_str(&p.fm, "topic");
    if wf.area == "dict" || wf.area == "playbook" { edges.extend(p.links.iter().map(|l| (wf.rel.clone(), l.clone(), "link".into()))); }
    else if wf.area == "record" {
        let (sup, ext) = (shapes::fm_str(&p.fm, "supersedes"), shapes::fm_str(&p.fm, "extends"));
        if !sup.is_empty() { edges.push((wf.rel.clone(), sup.clone(), "supersedes".into())); }
        if !ext.is_empty() { edges.push((wf.rel.clone(), ext, "extends".into())); }
        let basis = p.sections.get("依据").map(String::as_str).unwrap_or("");
        record = Some(RecordRow {
            file: wf.rel.clone(), doc: doc.clone(), kind: if shapes::record_kind(&p.fm) == shapes::RecordKind::Note { "note".into() } else { "decision".into() },
            tool: tool.clone(), by: shapes::fm_str(&p.fm, "by"), situation: fm_sit.clone(), verdict: shapes::fm_str(&p.fm, "verdict"),
            chosen: shapes::fm_str(&p.fm, "chosen"), outcome: shapes::fm_str(&p.fm, "outcome"), due: shapes::fm_str(&p.fm, "due"),
            supersedes: sup, topic: topic.clone(), date: date.clone(), has_four: i64::from(shapes::has_four_elements(&p.sections)),
            cites_record: i64::from(basis.contains("records/")), rule_refs: serde_json::to_string(&shapes::rule_refs(basis, rule_ids)).unwrap_or_else(|_| "[]".into()), quote_all: quotes::extract_quotes(&p.body).len() as i64,
        });
    }
    let (fm_lines, body_ls, mut seq) = (text.lines().count().saturating_sub(p.body.lines().count()), p.body.lines().collect::<Vec<_>>(), 0usize);
    let scope = if wf.area == "proposal" { "proposals" } else { "tools" };
    let htt = tokenize::tokenize_text(&format!("{} {} {} {} {}", title, shapes::fm_list(&p.fm, "aliases").join(" "), fm_sit, shapes::fm_str(&p.fm, "verdict"), topic));
    for (h, sb, ls) in shapes::section_blocks(&body_ls) {
        if wf.area == "proposal" && h != "为什么" && h != "最强反证" { continue; }
        let bs = ls.join("\n"); let tr = bs.trim();
        if tr.is_empty() && h.is_empty() { continue; }
        seq += 1;
        let lstart = fm_lines + sb + 1;
        let ex = if h.is_empty() { tr.into() } else { format!("{} · {}", h, tr) };
        push_chunk(&mut chunks, format!("{}#{}", doc, seq), &doc, &title, &wf.rel, lstart, lstart + ls.len().saturating_sub(1), h.clone(), scope, &tool, &kind, &date, &topic, compact_excerpt(&ex), if seq == 1 { htt.clone() } else { String::new() }, tokenize::tokenize_text(&format!("{}\n{}", h, tr)));
    }
    if chunks.is_empty() && wf.area != "proposal" { push_chunk(&mut chunks, format!("{}#1", doc), &doc, &title, &wf.rel, 1, text.lines().count().max(1), String::new(), scope, &tool, &kind, &date, &topic, compact_excerpt(&title), htt.clone(), htt); }
    Some(PreparedFile { file: wf.rel.clone(), sha1, mtime_ns, size, area: wf.area.clone(), sub: wf.sub.clone(), tool, doc, chunks, record, edges })
}

fn delete_file_rows(con: &Connection, rel: &str, st_tbl: bool) -> Result<(), String> {
    let mut st = con.prepare("SELECT rowid FROM chunks WHERE file = ?1").map_err(|e| e.to_string())?;
    let rids: Vec<i64> = st.query_map([rel], |r| r.get(0)).map_err(|e| e.to_string())?.filter_map(Result::ok).collect();
    drop(st);
    for rid in rids { con.execute("DELETE FROM fts WHERE rowid = ?1", [rid]).map_err(|e| e.to_string())?; }
    con.execute("DELETE FROM chunks WHERE file = ?1", [rel]).map_err(|e| e.to_string())?;
    con.execute("DELETE FROM files WHERE file = ?1", [rel]).map_err(|e| e.to_string())?;
    if st_tbl {
        con.execute("DELETE FROM records WHERE file = ?1", [rel]).map_err(|e| e.to_string())?;
        con.execute("DELETE FROM edges WHERE src = ?1", [rel]).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn insert_prepared(con: &Connection, pf: &PreparedFile, st_tbl: bool) -> Result<(), String> {
    con.execute("INSERT OR REPLACE INTO files(file, sha1, mtime_ns, size, area, sub, tool, doc) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
        params![pf.file, pf.sha1, pf.mtime_ns, pf.size, pf.area, pf.sub, pf.tool, pf.doc]).map_err(|e| e.to_string())?;
    let mut ic = con.prepare_cached("INSERT INTO chunks(id, doc, title, file, lstart, lend, pos, scope, tool, kind, date, series, excerpt) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)").map_err(|e| e.to_string())?;
    let mut ifts = con.prepare_cached("INSERT INTO fts(rowid, title_tokens, tokens) VALUES(?1, ?2, ?3)").map_err(|e| e.to_string())?;
    for c in &pf.chunks {
        ic.execute(params![c.id, c.doc, c.title, c.file, c.lstart as i64, c.lend as i64, c.pos, c.scope, c.tool, c.kind, c.date, c.series, c.excerpt]).map_err(|e| e.to_string())?;
        ifts.execute(params![con.last_insert_rowid(), c.title_tokens, c.tokens]).map_err(|e| e.to_string())?;
    }
    if st_tbl {
        if let Some(r) = &pf.record {
            con.execute("INSERT OR REPLACE INTO records(file, doc, kind, tool, by, situation, verdict, chosen, outcome, due, supersedes, superseded_by, topic, date, has_four, cites_record, rule_refs, quote_ok, quote_all) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,'',?12,?13,?14,?15,?16,0,?17)",
                params![r.file, r.doc, r.kind, r.tool, r.by, r.situation, r.verdict, r.chosen, r.outcome, r.due, r.supersedes, r.topic, r.date, r.has_four, r.cites_record, r.rule_refs, r.quote_all]).map_err(|e| e.to_string())?;
        }
        let mut ie = con.prepare_cached("INSERT INTO edges(src, dst, kind) VALUES(?1,?2,?3)").map_err(|e| e.to_string())?;
        for (s, d, k) in &pf.edges { ie.execute(params![s, d, k]).map_err(|e| e.to_string())?; }
    }
    Ok(())
}

fn resolve_supersedes(con: &Connection) -> Result<(), String> {
    con.execute("UPDATE records SET superseded_by = ''", []).map_err(|e| e.to_string())?;
    let mut st = con.prepare("SELECT file, supersedes FROM records WHERE supersedes != ''").map_err(|e| e.to_string())?;
    let pairs: Vec<(String, String)> = st.query_map([], |r| Ok((r.get(0)?, r.get(1)?))).map_err(|e| e.to_string())?.filter_map(Result::ok).collect();
    drop(st);
    for (newer, target) in pairs {
        let stem = Path::new(&target).file_stem().and_then(|s| s.to_str()).unwrap_or(&target);
        let _ = con.execute("UPDATE records SET superseded_by = ?1 WHERE file = ?2 OR doc = ?3", params![newer, target, stem]);
    }
    Ok(())
}

fn update_meta_counts(con: &Connection) -> Result<(usize, usize), String> {
    let docs: i64 = con.query_row("SELECT COUNT(DISTINCT doc) FROM chunks", [], |r| r.get(0)).unwrap_or(0);
    let chunks: i64 = con.query_row("SELECT COUNT(*) FROM chunks", [], |r| r.get(0)).unwrap_or(0);
    for (k, v) in [("docs_count", docs.to_string()), ("chunks_count", chunks.to_string()), ("built_at", util::now_iso()), ("engine_version", util::VERSION.into())] {
        con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?1, ?2)", params![k, v]).map_err(|e| e.to_string())?;
    }
    Ok((docs as usize, chunks as usize))
}

fn dedup_corpus(files: Vec<WalkFile>) -> Vec<WalkFile> {
    let (mut best, mut keep) = (HashMap::<String, usize>::new(), vec![true; files.len()]);
    for (i, f) in files.iter().enumerate() {
        if f.area != "corpus" { continue; }
        let st = f.path.file_stem().and_then(|s| s.to_str()).unwrap_or(&f.rel);
        let key = st.rsplit('_').next().filter(|s| s.starts_with("BV1") && s.len() == 12).unwrap_or(st).to_string();
        if let Some(&prev) = best.get(&key) {
            if f.sub == "clean" && files[prev].sub == "raw" { keep[prev] = false; best.insert(key, i); } else { keep[i] = false; }
        } else { best.insert(key, i); }
    }
    files.into_iter().enumerate().filter_map(|(i, f)| keep[i].then_some(f)).collect()
}

fn sync_db(cfg: &Config, db_path: &Path, files: Vec<WalkFile>, rule_ids: &HashSet<String>, st_tbl: bool, full: bool, saved_pulse: Vec<store::telemetry::TopicPulseRow>) -> Result<(Connection, usize, usize, usize, usize, usize), String> {
    let need_full = full || !db_path.exists() || !store::open_ro(db_path).map(|c| store::is_v2_schema(&c)).unwrap_or(false);
    if need_full && db_path.exists() {
        let _ = fs::remove_file(db_path);
        let _ = fs::remove_file(db_path.with_extension("sqlite-wal"));
        let _ = fs::remove_file(db_path.with_extension("sqlite-shm"));
    }
    let mut con = store::open_rw(db_path)?;
    if need_full { let _ = con.execute_batch("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;"); }
    store::init_schema(&con, st_tbl, !need_full)?;
    for tp in saved_pulse {
        let _ = con.execute("INSERT OR IGNORE INTO topic_pulse(topic, sessions_since, fragments_since, last_seen, last_reviewed) VALUES(?1,?2,?3,?4,?5)",
            params![tp.topic, tp.sessions_since, tp.fragments_since, tp.last_seen, tp.last_reviewed]);
    }
    let existing: HashMap<String, (i64, i64)> = if need_full { HashMap::new() } else {
        let mut st = con.prepare("SELECT file, mtime_ns, size FROM files").map_err(|e| e.to_string())?;
        let r = st.query_map([], |r| Ok((r.get(0)?, (r.get(1)?, r.get(2)?)))).map_err(|e| e.to_string())?.filter_map(Result::ok).collect();
        r
    };
    let live: HashSet<String> = files.iter().map(|f| f.rel.clone()).collect();
    let removed: Vec<String> = existing.keys().filter(|k| !live.contains(*k)).cloned().collect();
    let (mut to_parse, mut skipped) = (Vec::new(), 0);
    for wf in files { if existing.get(&wf.rel) == Some(&(wf.mtime_ns, wf.size)) { skipped += 1; } else { to_parse.push(wf); } }
    let pool = rayon::ThreadPoolBuilder::new().num_threads(std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(8)).build().map_err(|e| e.to_string())?;
    let prepared: Vec<PreparedFile> = pool.install(|| to_parse.par_iter().filter_map(|wf| prepare_file(cfg, wf, rule_ids)).collect());

    let tx = con.transaction().map_err(|e| e.to_string())?;
    for rel in &removed { delete_file_rows(&tx, rel, st_tbl)?; }
    for pf in &prepared { if !need_full { delete_file_rows(&tx, &pf.file, st_tbl)?; } insert_prepared(&tx, pf, st_tbl)?; }
    if st_tbl { resolve_supersedes(&tx)?; }
    if need_full { store::create_chunk_indexes(&tx)?; }
    let (docs, chunks) = update_meta_counts(&tx)?;
    tx.commit().map_err(|e| e.to_string())?;
    if need_full {
        let _ = con.execute("INSERT INTO fts(fts) VALUES('optimize')", []);
        let _ = con.execute_batch("VACUUM; PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;");
    }
    Ok((con, prepared.len(), skipped, removed.len(), docs, chunks))
}

fn walk_indexable(cfg: &Config) -> Vec<WalkFile> {
    dedup_corpus(config::walk(cfg).into_iter().filter(|f| f.area != "checks" && (f.area != "proposal" || f.sub == "pending")).collect())
}

pub fn build(cfg: &Config, full: bool, include_books_full: bool) -> Result<BuildStats, String> {
    if !cfg.shape_ok() { return Err(format!("unknown shape_version {} (supported: {:?})", cfg.shape_version, config::SUPPORTED_SHAPES)); }
    let saved_pulse = if (full || !cfg.index_path().exists()) && cfg.index_path().exists() { store::telemetry::list_topic_pulse(cfg) } else { Vec::new() };
    let rule_ids = fs::read_to_string(cfg.self_dir().join("RULES.md")).map(|t| shapes::parse_rules(&t).ids).unwrap_or_default();
    let (con, indexed, skipped, removed, total_docs, total_chunks) = sync_db(cfg, &cfg.index_path(), walk_indexable(cfg), &rule_ids, true, full, saved_pulse)?;

    let mut amap = tokenize::load_standalone_aliases(cfg);
    for t in &cfg.tools {
        for ent in fs::read_dir(t.dir.join("dict")).ok().into_iter().flatten().flatten() {
            if ent.path().extension().and_then(|s| s.to_str()) == Some("md") {
                if let Some(fm) = fs::read_to_string(ent.path()).ok().and_then(|s| shapes::split_frontmatter(&s).0) {
                    let mut g = vec![shapes::fm_str(&fm, "title")]; g.extend(shapes::fm_list(&fm, "aliases"));
                    tokenize::merge_alias_group(&mut amap, &g);
                }
            }
        }
    }
    let aj: BTreeMap<String, Vec<String>> = amap.into_iter().map(|(k, v)| (k, v.into_iter().collect())).collect();
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('aliases', ?1)", [serde_json::to_string(&aj).unwrap_or_else(|_| "{}".into())]).map_err(|e| e.to_string())?;
    let (bi, bc) = if !cfg.books.is_empty() && (include_books_full || !cfg.books_index_path().exists() || !full) {
        let (_, i, _, _, _, c) = sync_db(cfg, &cfg.books_index_path(), config::walk_books(cfg), &HashSet::new(), false, include_books_full, Vec::new())?; (i, c)
    } else { (0, 0) };
    write_index_md(cfg, &con)?; write_playbooks_indices(cfg)?; mirror_skills(cfg)?;
    Ok(BuildStats { indexed_files: indexed, skipped_files: skipped, removed_files: removed, total_docs, total_chunks, books_indexed: bi, books_chunks: bc })
}

pub fn index_one_file(cfg: &Config, rel: &str) -> Result<bool, String> {
    let Some((area, sub, tool)) = config::classify_rel(cfg, rel) else { return Ok(false) };
    if !cfg.index_path().is_file() { return Ok(false); }
    let mut con = store::open_rw(&cfg.index_path())?;
    if !store::is_v2_schema(&con) { return Ok(false); }
    let tx = con.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(|e| e.to_string())?;
    delete_file_rows(&tx, rel, true)?;
    let path = cfg.root.join(rel);
    if let Ok(m) = fs::metadata(&path) {
        if m.is_file() {
            let (mtime_ns, size) = config::meta_stat(&m);
            let rids = fs::read_to_string(cfg.self_dir().join("RULES.md")).map(|t| shapes::parse_rules(&t).ids).unwrap_or_default();
            if let Some(pf) = prepare_file(cfg, &WalkFile { path, rel: rel.into(), area, sub, tool, mtime_ns, size }, &rids) {
                insert_prepared(&tx, &pf, true)?;
                if pf.record.is_some() { resolve_supersedes(&tx)?; }
            }
        }
    }
    let _ = update_meta_counts(&tx)?; tx.commit().map_err(|e| e.to_string())?;
    Ok(true)
}

fn write_index_md(cfg: &Config, con: &Connection) -> Result<(), String> {
    let mut lines = vec![format!("# {} — Active-Heads Index · entryplug {}", cfg.root.file_name().and_then(|s| s.to_str()).unwrap_or("repo"), util::VERSION), String::new()];
    let mut used = lines[0].len() + 2;
    let mut push = |l: String, force: bool| -> bool {
        if !force && used + l.len() + 1 > INDEX_MD_CAP { return false; }
        used += l.len() + 1; lines.push(l); true
    };
    let mut st = con.prepare("SELECT f.area, f.file, COALESCE(c.title, f.doc), COALESCE(c.kind, f.area) FROM files f LEFT JOIN chunks c ON c.file = f.file AND c.rowid = (SELECT MIN(rowid) FROM chunks WHERE file = f.file) WHERE f.area IN ('dict','playbook','manual','memory') ORDER BY f.area, f.file").map_err(|e| e.to_string())?;
    let rows: Vec<(String, String, String, String)> = st.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?))).map_err(|e| e.to_string())?.filter_map(Result::ok).collect();
    if !rows.is_empty() {
        push("## Knowledge & Equipment".into(), true);
        for (a, f, t, k) in rows { if !push(format!("- [{}]({}) `{}`", t, f, k), a != "memory") { break; } }
        push(String::new(), true);
    }
    let mut rst = con.prepare("SELECT file, date, tool, kind, situation, verdict FROM records WHERE superseded_by = '' ORDER BY date DESC, file DESC").map_err(|e| e.to_string())?;
    let recs: Vec<(String, String, String, String, String, String)> = rst.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?))).map_err(|e| e.to_string())?.filter_map(Result::ok).collect();
    if !recs.is_empty() {
        push(format!("## Active Records ({} heads)", recs.len()), true);
        let mut shown = 0;
        for (f, d, t, k, s, v) in &recs {
            if !push(format!("- {} `{}` [{}] ({}) — {}", d, f, t, k, compact_excerpt(if v.is_empty() { s } else { v })), false) { break; }
            shown += 1;
        }
        if shown < recs.len() { lines.push(format!("\n_... +{} older active records in `{}` (query via `plug search` / MCP)_", recs.len() - shown, cfg.index_rel)); }
    }
    lines.push(String::new());
    util::write_lf(&cfg.index_md_path(), &lines.join("\n")).map_err(|e| e.to_string())
}

fn write_playbooks_indices(cfg: &Config) -> Result<(), String> {
    let pending: Vec<String> = fs::read_dir(cfg.proposals_dir().join("pending")).ok().into_iter().flatten().flatten()
        .map(|e| e.path()).filter(|p| p.extension().and_then(|s| s.to_str()) == Some("md")).map(|p| cfg.rel(&p)).collect();
    for t in &cfg.tools {
        let pdir = t.dir.join("playbooks");
        if !pdir.is_dir() { continue; }
        let mut ps: Vec<_> = fs::read_dir(&pdir).ok().into_iter().flatten().flatten().map(|e| e.path()).collect();
        ps.sort();
        let rows: Vec<_> = ps.into_iter().filter_map(|p| {
            let n = p.file_name()?.to_str()?.to_string();
            if !n.ends_with(".md") || n == "INDEX.md" { return None; }
            let fm = shapes::split_frontmatter(&fs::read_to_string(&p).ok()?).0.unwrap_or_default();
            let title = shapes::fm_str(&fm, "title");
            Some((n.clone(), if title.is_empty() { n } else { title }, shapes::fm_str(&fm, "stance"), shapes::fm_str(&fm, "situation")))
        }).collect();
        util::write_lf(&pdir.join("INDEX.md"), &entries::render_playbooks_index(&t.name, &rows, &pending)).map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn mirror_skills(cfg: &Config) -> Result<Vec<String>, String> {
    let dirs: BTreeSet<String> = cfg.pilots.values().filter(|p| !p.skills.is_empty()).map(|p| p.skills.trim_end_matches('/').to_string()).collect();
    let sp = cfg.kb_dir().join("mirrored.json");
    let prev: BTreeSet<String> = fs::read_to_string(&sp).ok().and_then(|s| serde_json::from_str::<Vec<String>>(&s).ok()).map(|v| v.into_iter().collect()).unwrap_or_default();
    let mut cur = BTreeSet::new();
    for dir in &dirs {
        for t in &cfg.tools {
            let src = t.dir.join("SKILL.md");
            if !src.is_file() { continue; }
            let dst_dir = cfg.root.join(dir).join(&t.name);
            let dst = dst_dir.join("SKILL.md");
            let bytes = fs::read(&src).map_err(|e| e.to_string())?;
            fs::create_dir_all(&dst_dir).map_err(|e| e.to_string())?;
            if fs::read(&dst).ok().as_deref() != Some(bytes.as_slice()) { fs::write(&dst, &bytes).map_err(|e| e.to_string())?; }
            if dir.contains(".agents/skills") {
                let oa = dst_dir.join("agents").join("openai.yaml");
                let allow = shapes::split_frontmatter(&String::from_utf8_lossy(&bytes)).0.map(|f| !shapes::fm_str(&f, "disable-model-invocation").eq_ignore_ascii_case("true")).unwrap_or(true);
                if !fs::read_to_string(&oa).ok().map(|s| s.contains(&format!("allow_implicit_invocation: {}", allow))).unwrap_or(false) { let _ = util::write_lf(&oa, &format!("policy:\n  allow_implicit_invocation: {}\n", allow)); }
            }
            cur.insert(format!("{}/{}", dir, t.name));
        }
    }
    for old in prev.difference(&cur) { let p = cfg.root.join(old); if p.is_dir() { let _ = fs::remove_dir_all(p); } }
    let _ = util::write_lf(&sp, &serde_json::to_string_pretty(&cur.iter().collect::<Vec<_>>()).unwrap_or_else(|_| "[]".into()));
    Ok(dirs.into_iter().collect())
}

pub fn stale_lag(cfg: &Config) -> Option<String> {
    let con = store::open_ro(&cfg.index_path()).ok()?;
    if !store::is_v2_schema(&con) { return Some("schema v1 (needs rebuild)".into()); }
    let mut st = con.prepare("SELECT file, mtime_ns, size, sha1 FROM files").ok()?;
    let idx: HashMap<String, (i64, i64, String)> = st.query_map([], |r| Ok((r.get(0)?, (r.get(1)?, r.get(2)?, r.get(3)?)))).ok()?.filter_map(Result::ok).collect();
    let live = walk_indexable(cfg);
    let seen: HashSet<&str> = live.iter().map(|w| w.rel.as_str()).collect();
    let changed = live.iter().filter(|wf| match idx.get(&wf.rel) {
        Some((om, os, _)) if *om == wf.mtime_ns && *os == wf.size => false,
        Some((_, _, osha)) => fs::read(&wf.path).map(|b| util::sha1_hex(&b) != *osha).unwrap_or(true),
        None => true,
    }).count();
    let removed = idx.keys().filter(|k| !seen.contains(k.as_str())).count();
    (changed + removed > 0).then(|| format!("{} file(s) changed/removed since last index", changed + removed))
}
