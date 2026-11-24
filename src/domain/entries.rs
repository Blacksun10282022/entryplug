use regex::Regex;
use std::sync::OnceLock;

#[derive(Debug, Clone)]
pub struct Observation {
    pub line: usize,
    pub unreviewed: bool,
    pub anchor: Option<String>,
    pub refs: Vec<String>,
    pub doc: Option<String>,
    pub seq: Option<String>,
    pub quote: Option<String>,
    pub unanchored: bool,
    pub missing_src: bool,
}

/// Optional entry-observation parser (Sunzi-style dict/playbooks; zero-cost when absent).
pub fn parse_observations(body: &str) -> Vec<Observation> {
    static RE_ITEM: OnceLock<Regex> = OnceLock::new();
    static RE_SRC: OnceLock<Regex> = OnceLock::new();
    static RE_ANC: OnceLock<Regex> = OnceLock::new();
    static RE_Q: OnceLock<Regex> = OnceLock::new();
    static RE_DOC: OnceLock<Regex> = OnceLock::new();
    let re_item = RE_ITEM.get_or_init(|| Regex::new(r"^\s*-\s+").unwrap());
    let re_src = RE_SRC.get_or_init(|| Regex::new(r"\(src:\s*(.*?)\)\s*$").unwrap());
    let re_anc = RE_ANC.get_or_init(|| Regex::new(r"\^p\d+").unwrap());
    let re_q = RE_Q.get_or_init(|| Regex::new(r#""([^"]+)"|「([^」]+)」"#).unwrap());
    let re_doc = RE_DOC.get_or_init(|| Regex::new(r"([A-Za-z0-9][\w\-\.]*)(?:#([\w\-:\.]+))?").unwrap());
    let (mut out, mut in_obs) = (Vec::new(), false);
    for (idx, line) in body.lines().enumerate() {
        if let Some(h) = line.strip_prefix("## ") { in_obs = h.trim().starts_with("观察"); continue; }
        if !in_obs || !re_item.is_match(line) { continue; }
        let mut txt = line.trim().strip_prefix('-').unwrap_or("").trim();
        let unreviewed = txt.starts_with("[?]");
        if unreviewed { txt = txt[3..].trim(); }
        let mut item = Observation { line: idx + 1, unreviewed, anchor: None, refs: Vec::new(), doc: None, seq: None, quote: None, unanchored: false, missing_src: false };
        if let Some(m) = re_src.captures(txt) {
            let (src, head) = (m[1].trim(), &txt[..m.get(0).unwrap().start()]);
            item.anchor = re_anc.find_iter(head).last().map(|x| x.as_str().into());
            item.refs = re_anc.find_iter(src).map(|x| x.as_str().into()).collect();
            item.unanchored = src.contains("[未锚]");
            item.quote = re_q.captures(src).and_then(|q| q.get(1).or_else(|| q.get(2))).map(|x| x.as_str().trim().into());
            let rest = re_anc.replace_all(src, " ");
            if let Some(d) = re_doc.captures(&rest) { item.doc = Some(d[1].into()); item.seq = d.get(2).map(|x| x.as_str().into()); }
        } else { item.missing_src = true; }
        out.push(item);
    }
    out
}

pub fn render_playbooks_index(tool_name: &str, rows: &[(String, String, String, String)], pending: &[String]) -> String {
    let mut lines = vec![format!("# {} · playbooks index", tool_name), String::new()];
    for (rel, title, stance, sit) in rows { lines.push(format!("- [{}]({}) [{}] — {}", title, rel, stance, sit)); }
    if !pending.is_empty() {
        lines.push(String::new());
        lines.push("## Pending proposals".into());
        for p in pending { lines.push(format!("- {}", p)); }
    }
    lines.push(String::new());
    lines.join("\n")
}
