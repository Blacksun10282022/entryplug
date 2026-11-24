use regex::Regex;
use std::collections::HashMap;
use std::sync::OnceLock;

#[derive(Debug, Clone)]
pub struct QuoteRef { pub doc_hint: String, pub quote: String }

pub fn compact_ws(s: &str) -> String { s.chars().filter(|c| !c.is_whitespace()).collect() }

pub fn norm_title(s: &str) -> String {
    s.chars().filter(|c| !c.is_whitespace() && !matches!(c, '《' | '》' | '【' | '】' | '"' | '\'' | '“' | '”' | '·' | '-' | '_' | '—' | '｜' | '|' | '：' | ':' | '？' | '?' | '！' | '!' | '，' | ',' | '。' | '.'))
        .flat_map(|c| c.to_lowercase()).collect()
}

pub fn extract_quotes(text: &str) -> Vec<QuoteRef> {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(
        r#"\(src:\s*([A-Za-z0-9][\w\-\.]*)(?:#[\w\-:\.]+)?\s+"([^"]+)"\s*\)|([A-Za-z0-9][\w\-\.]*)@[\d:\.]+「([^」]+)」|《([^》\n]+)》\s*\[(?:\d+:\d{2}(?::\d{2})?|¶\d+)\]\s*「([^」]+)」"#
    ).unwrap());
    re.captures_iter(text).filter_map(|c| {
        if let Some(d) = c.get(1) { Some(QuoteRef { doc_hint: d.as_str().trim().into(), quote: c[2].trim().into() }) }
        else if let Some(d) = c.get(3) { Some(QuoteRef { doc_hint: d.as_str().trim().into(), quote: c[4].trim().into() }) }
        else { c.get(5).map(|d| QuoteRef { doc_hint: d.as_str().trim().into(), quote: c[6].trim().into() }) }
    }).collect()
}

pub fn quote_matches_text(quote: &str, norm_doc: &str) -> bool {
    let q = compact_ws(quote);
    if q.is_empty() { return false; }
    let norm = q.replace("……", "\x00").replace("...", "\x00").replace('…', "\x00");
    let segs: Vec<&str> = norm.split('\x00').filter(|s| s.chars().count() >= 2).collect();
    if segs.is_empty() { return norm_doc.contains(&q); }
    let mut cur = 0;
    for seg in segs {
        let Some(idx) = norm_doc[cur..].find(seg) else { return false };
        cur += idx + seg.len();
    }
    true
}

pub fn verify_quote_in_map(q: &QuoteRef, docs_norm: &HashMap<String, Vec<String>>) -> bool {
    if docs_norm.get(&q.doc_hint).map(|ts| ts.iter().any(|t| quote_matches_text(&q.quote, t))).unwrap_or(false) { return true; }
    let hn = norm_title(&q.doc_hint);
    hn.chars().count() >= 2 && docs_norm.iter().any(|(k, ts)| {
        let kn = norm_title(k);
        (kn.contains(&hn) || (kn.chars().count() >= 4 && hn.contains(&kn))) && ts.iter().any(|t| quote_matches_text(&q.quote, t))
    })
}
