use crate::config::Config;
use crate::store::search::{self, SearchOpts};
use crate::util;
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

fn tool_schema() -> Value {
    json!({
        "name": "search",
        "description": "Read-only retrieval over tools, corpus, books, logs, memory, or all. Supports multi-angle queries (merged round-robin), Active Heads default (history=true for superseded), date/series filters, and view=compact|spine.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "scope": {"type": "string", "enum": ["tools", "corpus", "books", "logs", "memory", "all"], "default": "tools"},
                "tool": {"type": "string"}, "kind": {"type": "string"}, "date_from": {"type": "string"},
                "date_to": {"type": "string"}, "series": {"type": "string"},
                "history": {"type": "boolean", "default": false},
                "view": {"type": "string", "enum": ["compact", "spine"], "default": "compact"},
                "k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 60},
                "per_doc": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5}
            },
            "required": ["query"]
        }
    })
}

pub fn handle_message(cfg: &Config, msg: &Value) -> (Option<Value>, Option<Value>) {
    let m = msg.get("method").and_then(|v| v.as_str()).unwrap_or("");
    let p = msg.get("params").cloned().unwrap_or_else(|| json!({}));
    match m {
        "initialize" => (Some(json!({"protocolVersion": p.get("protocolVersion").and_then(|v| v.as_str()).unwrap_or("2025-06-18"), "capabilities": {"tools": {}}, "serverInfo": {"name": "entryplug", "version": util::VERSION}})), None),
        x if x.starts_with("notifications/") => (None, None),
        "ping" => (Some(json!({})), None),
        "tools/list" => (Some(json!({"tools": [tool_schema()]})), None),
        "tools/call" => {
            if p.get("name").and_then(|v| v.as_str()) != Some("search") {
                return (None, Some(json!({"code": -32602, "message": "there is only one tool: search"})));
            }
            let a = p.get("arguments").cloned().unwrap_or_else(|| json!({}));
            let queries: Vec<String> = match a.get("query") {
                Some(Value::String(s)) if !s.trim().is_empty() => vec![s.trim().into()],
                Some(Value::Array(arr)) => arr.iter().filter_map(|v| v.as_str().map(|s| s.trim().into())).filter(|s: &String| !s.is_empty()).collect(),
                _ => Vec::new(),
            };
            if queries.is_empty() { return (Some(json!({"content": [{"type": "text", "text": "query must not be empty"}], "isError": true})), None); }
            let gs = |k: &str| a.get(k).and_then(|v| v.as_str()).map(String::from);
            let opts = SearchOpts {
                queries, scope: gs("scope").unwrap_or_else(|| "tools".into()), tool: gs("tool"), kind: gs("kind"),
                date_from: gs("date_from"), date_to: gs("date_to"), series: gs("series"),
                history: a.get("history").and_then(|v| v.as_bool()).unwrap_or(false),
                view: gs("view").unwrap_or_else(|| "compact".into()),
                k: a.get("k").and_then(|v| v.as_u64()).unwrap_or(8) as usize,
                per_doc: a.get("per_doc").and_then(|v| v.as_u64()).unwrap_or(2) as usize,
                check_stale: true, record_telemetry: true,
            };
            match search::search(cfg, &opts) {
                Ok(res) => (Some(json!({"content": [{"type": "text", "text": search::format_rows(&res)}], "isError": false})), None),
                Err(e) => (Some(json!({"content": [{"type": "text", "text": e}], "isError": true})), None),
            }
        }
        other => (None, Some(json!({"code": -32601, "message": format!("no such method: {}", other)}))),
    }
}

pub fn serve(cfg: &Config) -> i32 {
    let (stdin, stdout) = (io::stdin(), io::stdout());
    let (mut reader, mut out, mut line) = (stdin.lock(), io::BufWriter::new(stdout.lock()), String::new());
    while reader.read_line(&mut line).unwrap_or(0) > 0 {
        let trimmed = line.trim();
        if !trimmed.is_empty() {
            match serde_json::from_str::<Value>(trimmed) {
                Err(_) => { let _ = writeln!(out, "{}", json!({"jsonrpc": "2.0", "id": null, "error": {"code": -32700, "message": "not JSON"}})); }
                Ok(msg) => {
                    let (res, err) = handle_message(cfg, &msg);
                    if let Some(id) = msg.get("id").filter(|v| !v.is_null()) {
                        let resp = if let Some(e) = err { json!({"jsonrpc": "2.0", "id": id, "error": e}) } else { json!({"jsonrpc": "2.0", "id": id, "result": res.unwrap_or_else(|| json!({}))}) };
                        let _ = writeln!(out, "{}", resp);
                    }
                }
            }
            let _ = out.flush();
        }
        line.clear();
    }
    0
}
