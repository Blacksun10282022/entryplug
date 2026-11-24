use crate::domain::shapes::{self, Fm};
use regex::Regex;
use std::sync::OnceLock;

#[derive(Debug, Clone)]
pub enum ProposalPatch { UnifiedDiff(String), FullText(String), Retire }

#[derive(Debug, Clone)]
pub struct ParsedProposal { pub fm: Fm, pub patch: Option<ProposalPatch>, pub errors: Vec<String> }

pub fn extract_fenced_block(section: &str) -> Option<(String, String)> {
    static OPEN: OnceLock<Regex> = OnceLock::new();
    static CLOSE: OnceLock<Regex> = OnceLock::new();
    let open = OPEN.get_or_init(|| Regex::new(r"^(`{3,})([^`]*)$").unwrap());
    let close = CLOSE.get_or_init(|| Regex::new(r"^(`{3,})[ \t]*$").unwrap());
    let (mut fence, mut info, mut buf) = (0usize, String::new(), Vec::new());
    for line in section.lines() {
        if fence == 0 {
            if let Some(c) = open.captures(line) { fence = c[1].len(); info = c[2].trim().to_lowercase(); }
        } else if close.captures(line).map(|c| c[1].len() >= fence).unwrap_or(false) {
            return Some((info, buf.join("\n")));
        } else { buf.push(line); }
    }
    None
}

pub fn parse_proposal(text: &str) -> ParsedProposal {
    let p = shapes::parse_file(text, "proposal");
    let body = p.sections.get("改成什么").cloned().unwrap_or_default();
    let first = body.lines().map(str::trim).find(|l| !l.is_empty()).unwrap_or("");
    let mut errors = p.errors;
    if first.eq_ignore_ascii_case("retire") || first == "退役" {
        return ParsedProposal { fm: p.fm, patch: Some(ProposalPatch::Retire), errors };
    }
    let patch = if let Some((info, inner)) = extract_fenced_block(&body) {
        let is_diff = matches!(info.as_str(), "diff" | "patch" | "udiff") || inner.lines().any(|l| l.starts_with("@@ -") && l.contains(" @@"));
        Some(if is_diff { ProposalPatch::UnifiedDiff(inner) } else { ProposalPatch::FullText(format!("{}\n", inner)) })
    } else {
        errors.push("「改成什么」holds no Unified Diff or fenced code block (```…```) and is not `retire`".into());
        None
    };
    ParsedProposal { fm: p.fm, patch, errors }
}

pub fn apply_unified_diff(original: &str, diff_text: &str) -> Result<String, String> {
    static RE_HUNK: OnceLock<Regex> = OnceLock::new();
    let re = RE_HUNK.get_or_init(|| Regex::new(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@").unwrap());
    let mut hunks: Vec<(usize, Vec<(char, String)>)> = Vec::new();
    for raw in diff_text.lines() {
        if let Some(c) = re.captures(raw) { hunks.push((c[1].parse().unwrap_or(1), Vec::new())); }
        else if let Some((_, ls)) = hunks.last_mut() {
            if raw.starts_with(r"\ No newline") { continue; }
            match raw.chars().next().unwrap_or(' ') {
                t @ (' ' | '+' | '-') => ls.push((t, raw[1..].into())),
                _ if raw.is_empty() => ls.push((' ', String::new())),
                _ => return Err(format!("malformed diff line: {}", raw)),
            }
        }
    }
    if hunks.is_empty() { return Err("unified diff contains no @@ hunks".into()); }
    let orig = original.replace("\r\n", "\n");
    let (mut lines, mut off): (Vec<String>, isize) = (orig.lines().map(String::from).collect(), 0);
    for (hi, (old_start, hlines)) in hunks.iter().enumerate() {
        let exp: Vec<&str> = hlines.iter().filter(|(t, _)| *t != '+').map(|(_, s)| s.as_str()).collect();
        let rep: Vec<String> = hlines.iter().filter(|(t, _)| *t != '-').map(|(_, s)| s.clone()).collect();
        let base = ((old_start.saturating_sub(1)) as isize + off).max(0) as usize;
        let ok_at = |i: usize, cur: &[String]| i + exp.len() <= cur.len() && exp.iter().enumerate().all(|(j, e)| cur[i + j] == *e);
        let pos = if ok_at(base, &lines) { base } else {
            let cands: Vec<usize> = (base.saturating_sub(40)..=(base + 40).min(lines.len())).filter(|&i| ok_at(i, &lines)).collect();
            if cands.len() == 1 { cands[0] } else { return Err(format!("hunk #{} context mismatch at line {}", hi + 1, old_start)); }
        };
        off += rep.len() as isize - exp.len() as isize;
        lines.splice(pos..pos + exp.len(), rep);
    }
    let mut out = lines.join("\n");
    if !out.is_empty() { out.push('\n'); }
    Ok(out)
}

pub fn render_unified_diff(old: &str, new: &str, rel: &str) -> String {
    let (on, nn) = (old.replace("\r\n", "\n"), new.replace("\r\n", "\n"));
    let (a, b): (Vec<&str>, Vec<&str>) = (on.lines().collect(), nn.lines().collect());
    if a == b { return "(identical content)".into(); }
    let (mut pre, mut suf) = (0, 0);
    while pre < a.len() && pre < b.len() && a[pre] == b[pre] { pre += 1; }
    while suf + pre < a.len() && suf + pre < b.len() && a[a.len() - 1 - suf] == b[b.len() - 1 - suf] { suf += 1; }
    let (cs, ae, be) = (pre.saturating_sub(3), (a.len() - suf + 3).min(a.len()), (b.len() - suf + 3).min(b.len()));
    let mut out = vec![format!("--- a/{}", rel), format!("+++ b/{}", rel), format!("@@ -{},{} +{},{} @@", cs + 1, ae - cs, cs + 1, be - cs)];
    out.extend(a[cs..pre].iter().map(|l| format!(" {}", l)));
    out.extend(a[pre..a.len() - suf].iter().map(|l| format!("-{}", l)));
    out.extend(b[pre..b.len() - suf].iter().map(|l| format!("+{}", l)));
    out.extend(a[a.len() - suf..ae].iter().map(|l| format!(" {}", l)));
    out.join("\n")
}
