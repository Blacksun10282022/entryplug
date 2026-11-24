pub mod index;
pub mod search;
pub mod telemetry;

use rusqlite::{Connection, OpenFlags};
use std::path::Path;

pub const SCHEMA_VERSION: &str = "2";

pub fn open_rw(path: &Path) -> Result<Connection, String> {
    if let Some(p) = path.parent() { std::fs::create_dir_all(p).map_err(|e| e.to_string())?; }
    let existed = path.is_file();
    let con = Connection::open(path).map_err(|e| format!("open sqlite {}: {}", path.display(), e))?;
    let pragmas = if existed {
        "PRAGMA busy_timeout=1000; PRAGMA synchronous=NORMAL; PRAGMA mmap_size=67108864; PRAGMA temp_store=MEMORY;"
    } else {
        "PRAGMA busy_timeout=1000; PRAGMA auto_vacuum=FULL; PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA mmap_size=67108864; PRAGMA temp_store=MEMORY;"
    };
    con.execute_batch(pragmas).map_err(|e| format!("pragma failed: {}", e))?;
    Ok(con)
}

pub fn open_ro(path: &Path) -> Result<Connection, String> {
    if !path.is_file() { return Err(format!("index missing: {} (run plug index)", path.display())); }
    let con = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
        .map_err(|e| format!("open ro sqlite {}: {}", path.display(), e))?;
    let _ = con.execute_batch("PRAGMA busy_timeout=150; PRAGMA mmap_size=67108864; PRAGMA query_only=ON;");
    Ok(con)
}

pub fn is_v2_schema(con: &Connection) -> bool {
    con.query_row("SELECT value FROM meta WHERE key='schema_version'", [], |r| r.get::<_, String>(0))
        .map(|v| v == SCHEMA_VERSION).unwrap_or(false)
}

pub fn create_chunk_indexes(con: &Connection) -> Result<(), String> {
    con.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file);
         CREATE INDEX IF NOT EXISTS idx_chunks_scope_tool_kind ON chunks(scope, tool, kind);
         CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc);
         CREATE INDEX IF NOT EXISTS idx_chunks_date ON chunks(date);",
    ).map_err(|e| e.to_string())
}

pub fn init_schema(con: &Connection, include_state_tables: bool, with_indexes: bool) -> Result<(), String> {
    con.execute_batch(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS files (file TEXT PRIMARY KEY, sha1 TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, area TEXT NOT NULL, sub TEXT NOT NULL, tool TEXT NOT NULL, doc TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS chunks (rowid INTEGER PRIMARY KEY, id TEXT NOT NULL, doc TEXT NOT NULL, title TEXT NOT NULL, file TEXT NOT NULL, lstart INTEGER NOT NULL, lend INTEGER NOT NULL, pos TEXT NOT NULL, scope TEXT NOT NULL, tool TEXT NOT NULL, kind TEXT NOT NULL, date TEXT NOT NULL, series TEXT NOT NULL, excerpt TEXT NOT NULL);
         CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(title_tokens, tokens, content='', contentless_delete=1, tokenize='unicode61');",
    ).map_err(|e| format!("init schema: {}", e))?;
    if include_state_tables {
        con.execute_batch(
            "CREATE TABLE IF NOT EXISTS records (file TEXT PRIMARY KEY, doc TEXT NOT NULL, kind TEXT NOT NULL, tool TEXT NOT NULL, by TEXT NOT NULL, situation TEXT NOT NULL, verdict TEXT NOT NULL, chosen TEXT NOT NULL, outcome TEXT NOT NULL, due TEXT NOT NULL, supersedes TEXT NOT NULL, superseded_by TEXT NOT NULL, topic TEXT NOT NULL, date TEXT NOT NULL, has_four INTEGER NOT NULL, cites_record INTEGER NOT NULL, rule_refs TEXT NOT NULL, quote_ok INTEGER NOT NULL, quote_all INTEGER NOT NULL);
             CREATE TABLE IF NOT EXISTS edges (src TEXT NOT NULL, dst TEXT NOT NULL, kind TEXT NOT NULL);
             CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
             CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
             CREATE TABLE IF NOT EXISTS topic_pulse (topic TEXT PRIMARY KEY, sessions_since INTEGER NOT NULL, fragments_since INTEGER NOT NULL, last_seen TEXT NOT NULL, last_reviewed TEXT NOT NULL);",
        ).map_err(|e| format!("init state tables: {}", e))?;
    }
    if with_indexes { create_chunk_indexes(con)?; }
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?1)", [SCHEMA_VERSION]).map_err(|e| e.to_string())?;
    Ok(())
}
