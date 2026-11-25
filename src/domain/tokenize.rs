use crate::config::Config;
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::path::Path;

pub fn is_cjk(c: char) -> bool { ('\u{4E00}'..='\u{9FFF}').contains(&c) }
pub fn has_cjk(s: &str) -> bool { s.chars().any(is_cjk) }

/// Pure CJK 2-gram + lowercased ASCII tokenizer (zero external segmenter).
pub fn tokenize_text(text: &str) -> String {
    let (mut out, mut cjk, mut asc) = (String::with_capacity(text.len() * 2), Vec::<char>::new(), String::new());
    let flush_cjk = |run: &mut Vec<char>, out: &mut String| {
        if run.len() == 1 { if !out.is_empty() { out.push(' '); } out.push(run[0]); }
        else { for w in run.windows(2) { if !out.is_empty() { out.push(' '); } out.push(w[0]); out.push(w[1]); } }
        run.clear();
    };
    let flush_asc = |run: &mut String, out: &mut String| {
        if !run.is_empty() { if !out.is_empty() { out.push(' '); } out.push_str(run); run.clear(); }
    };
    for ch in text.chars() {
        if is_cjk(ch) { flush_asc(&mut asc, &mut out); cjk.push(ch); }
        else if ch.is_ascii_alphanumeric() { flush_cjk(&mut cjk, &mut out); asc.push(ch.to_ascii_lowercase()); }
        else { flush_cjk(&mut cjk, &mut out); flush_asc(&mut asc, &mut out); }
    }
    flush_cjk(&mut cjk, &mut out); flush_asc(&mut asc, &mut out);
    out
}

pub fn phrase_for_fts(term: &str) -> Option<String> {
    let toks = tokenize_text(term);
    let parts: Vec<&str> = toks.split_whitespace().collect();
    (!parts.is_empty()).then(|| format!("\"{}\"", parts.join(" ")))
}

const Q_SUFFIX: &[&str] = &["到底是什么意思", "是什么意思", "是什么概念", "到底是什么", "讲的是啥", "具体讲了啥", "到底在讲什么", "是什么", "怎么回事", "怎么办", "怎么理解", "原话是什么", "原话怎么讲的"];
const STOP_WORDS: &[&str] = &[
    "就是", "但是", "因为", "所以", "如果", "而且", "还是", "或者", "觉得", "感觉", "其实", "时候", "一个",
    "没有", "可以", "这个", "那个", "怎么", "什么", "为什么", "是不是", "已经", "可能", "应该", "真的",
    "特别", "非常", "有点", "好像", "直接", "最后", "今天", "两天", "平时", "回来", "总是", "一直", "现在",
    "自己", "别人", "大家", "东西", "问题", "地方", "这样", "那样", "这么", "那么", "一下", "一点", "一些",
    "然后", "接着", "后来", "以前", "之后", "之前", "虽然", "不过", "只是", "甚至", "不是", "不会", "不能",
    "不要", "不想", "不知道", "的话", "来说", "大概", "一般", "经常", "到底", "那期", "那本", "那句", "具体",
    "讲过", "讲的", "原话", "教材", "这套", "多人", "这件事", "有一讲", "那种", "算不算", "几个", "哪些",
];
const STOP_CHARS: &[char] = &[
    '的', '了', '是', '我', '你', '他', '她', '它', '们', '在', '有', '和', '就', '都', '也', '还', '很', '太',
    '吧', '啊', '呢', '吗', '嘛', '呀', '哦', '嗯', '把', '被', '让', '给', '对', '到', '从', '向', '着', '过',
    '这', '那', '个', '里', '上', '下', '来', '去', '会', '能', '要', '想', '说', '看', '听', '问', '做', '弄',
    '才', '又', '再', '更', '最', '没', '不', '挺', '老', '讲',
];

fn expand_term(term: &str, aliases: &HashMap<String, Vec<String>>) -> Option<String> {
    let (mut forms, low) = (vec![term.to_string()], term.to_lowercase());
    for key in [term, low.as_str()] { if let Some(alts) = aliases.get(key) { for a in alts { if !forms.contains(a) { forms.push(a.clone()); } } } }
    let mut phrases = Vec::new();
    for f in forms.into_iter().take(12) { if let Some(p) = phrase_for_fts(&f) { if !phrases.contains(&p) { phrases.push(p); } } }
    match phrases.len() { 0 => None, 1 => Some(phrases.remove(0)), _ => Some(format!("({})", phrases.join(" OR "))) }
}

pub fn build_fts_queries(raw: &str, aliases: &HashMap<String, Vec<String>>) -> (Option<String>, Option<String>) {
    let mut q = raw.trim().to_string();
    if q.is_empty() { return (None, None); }
    for suf in Q_SUFFIX { if q.ends_with(suf) && q.len() > suf.len() + 1 { q = q[..q.len() - suf.len()].trim().to_string(); } }
    let q_low = q.to_lowercase();
    if aliases.contains_key(&q) || aliases.contains_key(&q_low) { return (expand_term(&q, aliases), None); }

    let (mut short_terms, mut long_runs, mut cjk, mut asc) = (Vec::new(), Vec::new(), String::new(), String::new());
    let flush = |c: &mut String, a: &mut String, sh: &mut Vec<String>, lg: &mut Vec<String>| {
        if !c.is_empty() { if c.chars().count() <= 4 { sh.push(std::mem::take(c)); } else { lg.push(std::mem::take(c)); } }
        if !a.is_empty() { sh.push(std::mem::take(a)); }
    };
    for ch in q.chars() {
        if is_cjk(ch) { if !asc.is_empty() { short_terms.push(std::mem::take(&mut asc)); } cjk.push(ch); }
        else if ch.is_ascii_alphanumeric() { if !cjk.is_empty() { flush(&mut cjk, &mut String::new(), &mut short_terms, &mut long_runs); } asc.push(ch.to_ascii_lowercase()); }
        else { flush(&mut cjk, &mut asc, &mut short_terms, &mut long_runs); }
    }
    flush(&mut cjk, &mut asc, &mut short_terms, &mut long_runs);
    if long_runs.is_empty() {
        let mut parts: Vec<String> = Vec::new();
        let mut covered = String::new();
        for k in aliases.keys().filter(|k| k.contains(' ') && q_low.contains(&k.to_lowercase())) {
            if let Some(e) = expand_term(k, aliases) { if !parts.contains(&e) { parts.push(e); covered.push(' '); covered.push_str(&k.to_lowercase()); } }
        }
        let non_stop: Vec<&String> = short_terms.iter().filter(|t| !STOP_WORDS.contains(&t.as_str()) && !covered.split_whitespace().any(|w| w == t.as_str())).collect();
        for t in if !non_stop.is_empty() || !parts.is_empty() { non_stop } else { short_terms.iter().collect() } {
            if let Some(e) = expand_term(t, aliases) { if !parts.contains(&e) { parts.push(e); } }
        }
        return if parts.is_empty() { (None, None) } else { (Some(parts.join(" ")), (parts.len() > 1).then(|| parts.join(" OR "))) };
    }
    let mut bag: Vec<String> = Vec::new();
    let mut push_exp = |t: &str| { if let Some(e) = expand_term(t, aliases) { if !bag.contains(&e) { bag.push(e); } } };
    for k in aliases.keys().filter(|k| k.chars().count() >= 2 && (q.contains(k.as_str()) || q_low.contains(&k.to_lowercase()))) { push_exp(k); }
    for t in short_terms.iter().filter(|t| t.chars().count() >= 2 || t.chars().all(|c| c.is_ascii_alphanumeric())) { push_exp(t); }
    let stop_set: HashSet<&str> = STOP_WORDS.iter().copied().collect();
    for run in &long_runs {
        let cleaned = STOP_WORDS.iter().fold(run.clone(), |acc, sw| if acc.contains(sw) { acc.replace(sw, " ") } else { acc });
        let mut isl = Vec::new();
        let push_isl = |isl: &mut Vec<char>, bag: &mut Vec<String>| {
            for w in isl.windows(2) {
                let bg: String = w.iter().collect();
                if !stop_set.contains(bg.as_str()) { let tok = expand_term(&bg, aliases).unwrap_or_else(|| format!("\"{}\"", bg)); if !bag.contains(&tok) { bag.push(tok); } }
            }
            isl.clear();
        };
        for ch in cleaned.chars() { if is_cjk(ch) && !STOP_CHARS.contains(&ch) { isl.push(ch); } else { push_isl(&mut isl, &mut bag); } }
        push_isl(&mut isl, &mut bag);
        if bag.is_empty() { for w in run.chars().collect::<Vec<_>>().windows(2) { bag.push(format!("\"{}\"", w.iter().collect::<String>())); } }
    }
    bag.truncate(40);
    ((!bag.is_empty()).then(|| bag.join(" OR ")), None)
}

pub fn merge_alias_group(map: &mut BTreeMap<String, BTreeSet<String>>, terms: &[String]) {
    let clean: Vec<String> = terms.iter().map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
    if clean.len() < 2 { return; }
    for a in &clean {
        for key in [a.clone(), a.to_lowercase()] {
            let e = map.entry(key).or_default();
            for b in &clean { if a != b { e.insert(b.clone()); } }
        }
    }
}

pub fn load_standalone_aliases(cfg: &Config) -> BTreeMap<String, BTreeSet<String>> {
    let mut map = BTreeMap::new();
    for (k, vs) in &cfg.inline_aliases {
        let mut g = vec![k.clone()]; g.extend(vs.iter().cloned()); merge_alias_group(&mut map, &g);
    }
    for rel in &cfg.aliases_paths { load_alias_file(&cfg.root.join(rel), &mut map); }
    map
}

fn load_alias_file(path: &Path, map: &mut BTreeMap<String, BTreeSet<String>>) {
    let Ok(text) = std::fs::read_to_string(path) else { return };
    match path.extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase().as_str() {
        "tsv" => for line in text.lines().skip(1) {
            let c: Vec<&str> = line.split('\t').collect();
            if c.len() >= 4 && (c[3].trim() == "确定" || c.get(6).copied().unwrap_or("").contains("检索别名")) {
                merge_alias_group(map, &[c[0].trim().into(), c[1].trim().into()]);
            }
        },
        "yaml" | "yml" => if let Ok(v) = serde_yaml::from_str::<serde_yaml::Value>(&text) {
            if let Some(m) = v.as_mapping() {
                for (k, val) in m {
                    if let Some(ks) = k.as_str() {
                        let mut g = vec![ks.to_string()];
                        if let Some(seq) = val.as_sequence() { g.extend(seq.iter().filter_map(|x| x.as_str().map(String::from))); }
                        else if let Some(s) = val.as_str() { g.push(s.into()); }
                        merge_alias_group(map, &g);
                    }
                }
            } else if let Some(seq) = v.as_sequence() {
                for it in seq { if let Some(g) = it.as_sequence() { merge_alias_group(map, &g.iter().filter_map(|x| x.as_str().map(String::from)).collect::<Vec<_>>()); } }
            }
        },
        "md" => for line in text.lines() {
            for seg in line.split(&['；', ';', '（', '）', '(', ')'][..]) {
                if seg.contains('=') {
                    let ps: Vec<String> = seg.split('=').map(|s| s.trim().into()).filter(|s: &String| !s.is_empty() && s.chars().count() <= 16).collect();
                    merge_alias_group(map, &ps);
                } else if let Some((a, b)) = seg.split_once('→') {
                    let (a, b) = (a.trim(), b.split_whitespace().next().unwrap_or("").trim());
                    if !a.is_empty() && !b.is_empty() && a.chars().count() <= 12 && b.chars().count() <= 12 { merge_alias_group(map, &[a.into(), b.into()]); }
                }
            }
        },
        _ => {}
    }
}
