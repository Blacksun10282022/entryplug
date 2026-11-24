mod cmd;
mod config;
mod domain;
mod gates;
mod pilots;
mod store;
mod util;

use crate::store::search::{self, SearchOpts};
use std::path::{Path, PathBuf};
use std::process;

fn load_cfg(root_arg: Option<&str>) -> Result<config::Config, String> {
    let root = match root_arg {
        Some(r) => PathBuf::from(r),
        None => std::env::var("PLUG_ROOT").ok().filter(|s| !s.trim().is_empty()).map(PathBuf::from).map(Ok).unwrap_or_else(|| config::find_root(None))?,
    };
    config::load(&root)
}

fn flag_val<'a>(args: &'a [String], names: &[&str]) -> Option<&'a str> {
    args.iter().position(|a| names.contains(&a.as_str())).and_then(|i| args.get(i + 1)).map(String::as_str)
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    if raw.is_empty() || raw[0] == "-h" || raw[0] == "--help" {
        println!("plug {} — single-binary local cognitive kernel\nUsage: plug [--root <dir>] <index|search|mcp|status|check|apply|init|eval|hash|trace|review|gate> [args]", util::VERSION);
        return;
    }
    if raw[0] == "-V" || raw[0] == "--version" { println!("entryplug {}", util::VERSION); return; }

    let (mut root_arg, mut args, mut i) = (None, Vec::new(), 0);
    while i < raw.len() {
        if raw[i] == "--root" && i + 1 < raw.len() { root_arg = Some(raw[i + 1].clone()); i += 2; }
        else { args.push(raw[i].clone()); i += 1; }
    }
    if args.is_empty() { return; }
    let (verb, rest) = (args[0].as_str(), &args[1..]);

    let code = match verb {
        "outbound" => gates::run_pretool(),
        "gate" => match rest.first().map(String::as_str) {
            Some("pretool") | Some("outbound") => gates::run_pretool(),
            Some("posttool") => gates::run_posttool(),
            Some("prompt") => gates::run_prompt(),
            Some("precommit") => gates::run_precommit(),
            Some("precompact") => gates::run_precompact(rest.iter().any(|a| a == "--emit")),
            Some("stop") => gates::run_stop(),
            other => { eprintln!("gate: unknown gate {:?}", other); 1 }
        },
        "hash" => match rest.first().map(std::fs::read) {
            Some(Ok(b)) => { println!("{}", util::blob_short_hash(&b)); 0 }
            Some(Err(e)) => { eprintln!("hash: {}", e); 1 }
            None => { eprintln!("usage: plug hash <file>"); 1 }
        },
        _ => {
            let cfg = match load_cfg(root_arg.as_deref()) { Ok(c) => c, Err(e) => { eprintln!("plug: {}", e); process::exit(1); } };
            match verb {
                "index" => match store::index::build(&cfg, rest.iter().any(|a| a == "--full"), rest.iter().any(|a| a == "--books")) {
                    Ok(st) => {
                        let bk = if st.books_chunks > 0 { format!(" · books {} ({} chunks)", st.books_indexed, st.books_chunks) } else { String::new() };
                        println!("indexed {} file(s) (skipped {}, removed {}) · total {} docs / {} chunks{}", st.indexed_files, st.skipped_files, st.removed_files, st.total_docs, st.total_chunks, bk);
                        0
                    }
                    Err(e) => { eprintln!("index: {}", e); 1 }
                },
                "search" => {
                    let (mut opts, mut as_json, mut j) = (SearchOpts { record_telemetry: true, ..Default::default() }, false, 0);
                    while j < rest.len() {
                        match rest[j].as_str() {
                            "--scope" if j + 1 < rest.len() => { opts.scope = rest[j + 1].clone(); j += 2; }
                            "--tool" if j + 1 < rest.len() => { opts.tool = Some(rest[j + 1].clone()); j += 2; }
                            "--kind" if j + 1 < rest.len() => { opts.kind = Some(rest[j + 1].clone()); j += 2; }
                            "--date-from" if j + 1 < rest.len() => { opts.date_from = Some(rest[j + 1].clone()); j += 2; }
                            "--date-to" if j + 1 < rest.len() => { opts.date_to = Some(rest[j + 1].clone()); j += 2; }
                            "--series" if j + 1 < rest.len() => { opts.series = Some(rest[j + 1].clone()); j += 2; }
                            "--view" if j + 1 < rest.len() => { opts.view = rest[j + 1].clone(); j += 2; }
                            "-k" | "--k" if j + 1 < rest.len() => { opts.k = rest[j + 1].parse().unwrap_or(8); j += 2; }
                            "--per-doc" if j + 1 < rest.len() => { opts.per_doc = rest[j + 1].parse().unwrap_or(2); j += 2; }
                            "--history" => { opts.history = true; j += 1; }
                            "--no-stale" => { opts.check_stale = false; j += 1; }
                            "--json" => { as_json = true; j += 1; }
                            q => { opts.queries.push(q.into()); j += 1; }
                        }
                    }
                    if opts.queries.is_empty() { eprintln!("usage: plug search <query...>"); process::exit(1); }
                    match search::search(&cfg, &opts) {
                        Ok(res) => { println!("{}", if as_json { serde_json::to_string_pretty(&res).unwrap() } else { search::format_rows(&res) }); 0 }
                        Err(e) => { eprintln!("search: {}", e); 1 }
                    }
                }
                "mcp" => cmd::mcp::serve(&cfg),
                "status" => {
                    let emit = rest.iter().position(|a| a == "--emit").map(|idx| rest.get(idx + 1).filter(|s| !s.starts_with('-')).map(String::as_str).unwrap_or("claude-code"));
                    cmd::status::run(&cfg, emit, rest.iter().any(|a| a == "--json"))
                }
                "check" => cmd::check::run(&cfg, rest.iter().any(|a| a == "--quiet"), rest.iter().any(|a| a == "--no-expire"), flag_val(rest, &["--contact"])),
                "apply" => {
                    let prop = rest.iter().enumerate().find(|(idx, a)| !a.starts_with('-') && (*idx == 0 || rest[idx - 1] != "--reject")).map(|(_, a)| a.as_str());
                    match prop {
                        Some(p) => cmd::apply::run(&cfg, p, flag_val(rest, &["--reject"]), rest.iter().any(|a| a == "--dry-run"), rest.iter().any(|a| a == "--owner")),
                        None => { eprintln!("usage: plug apply <proposal>"); 1 }
                    }
                }
                "init" => cmd::init::run(&cfg, flag_val(rest, &["--pilot"]).unwrap_or("all"), rest.iter().any(|a| a == "--link-skills"), rest.iter().any(|a| a == "--print")),
                "eval" => {
                    let k = flag_val(rest, &["-k", "--k"]).and_then(|s| s.parse().ok()).unwrap_or(10);
                    let gs = rest.iter().enumerate().find(|(idx, a)| !a.starts_with('-') && (*idx == 0 || !matches!(rest[idx - 1].as_str(), "-k" | "--k"))).map(|(_, a)| a.as_str());
                    match gs { Some(p) => cmd::eval::run(&cfg, Path::new(p), k), None => { eprintln!("usage: plug eval <goldset>"); 1 } }
                }
                "trace" => match pilots::trace::sync(&cfg, flag_val(rest, &["--pilot"]).unwrap_or("all"), rest.iter().any(|a| a == "--dry-run")) {
                    Ok(st) => { println!("trace sync: scanned {} file(s), {} turns across {} day(s), masked {} secret(s)", st.files_scanned, st.turns_written, st.days_touched, st.masked_hits); 0 }
                    Err(e) => { eprintln!("trace: {}", e); 1 }
                },
                "review" => cmd::review::run(&cfg, flag_val(rest, &["--since"]).unwrap_or("7d"), flag_val(rest, &["--topic"]), rest.iter().any(|a| a == "--json"), rest.iter().any(|a| a == "--mark-reviewed")),
                other => { eprintln!("plug: unknown command '{}'", other); 1 }
            }
        }
    };
    process::exit(code);
}
