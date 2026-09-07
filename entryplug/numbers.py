# What: the sync rate (numbers page) — computes "mechanical accuracy" and "judgment accuracy" from the flight log
#       (records) and writes one page of markdown. The two are always reported apart and there is never a total.
# In:   cfg · the parsed record list (from check.run: fm · sections · rel · age) · today · corpus docs (for anchor
#       checking) · the anchor set · the set of rule ids.
# Out:  page() → markdown text (check writes it to the numbers page and appends it to the report).
# Not:  no total score; no LLM judging; below n=10 only "k of n" is printed; it is a report, never a control signal.
# Who:  check.run.
# Note: mechanical accuracy (machine-computed, trustworthy from the first record): quotes verifiable · rule
#       references real · four elements present · cites earlier records (only once there are >=10).
#       Judgment accuracy (data comes from the owner only): agreement rate over blind-valid records with a Wilson
#       95% interval · who was right after a disagreement (counted from the markers in `outcome`).
#       Blind-valid (D10): in the version where git first saw the file, verdict was set and chosen was empty; a
#       record written with chosen already filled is "non-blind" and excluded; untracked files are out of the
#       denominator. Agreement (D09): chosen normalises to verdict, or starts with one of the owner's assent words.
#       n>=30 with an agreement rate above 95% is automatically flagged as likely sycophancy.
#       The Chinese literals below are content vocabulary (record sections and the owner's own wording), not prose.
# Deps: stdlib (subprocess only to ask git) · shapes.split_frontmatter.
import math, re, subprocess
from . import __version__, shapes

AGREE_PREFIX = ("同意", "同 ", "按它", "按 verdict")
RIGHT_MARKERS = {"它对": "it was right", "我对": "I was right", "说不清": "unclear"}
RE_QUOTE = re.compile(r"\(src:\s*([A-Za-z0-9][\w\-\.]*)(?:#[\w\-:\.]+)?\s+\"([^\"]+)\"\s*\)|([A-Za-z0-9][\w\-\.]*)@[\d:\.]+「([^」]+)」"
                      r"|《([^》\n]+)》\s*\[(?:\d+:\d{2}(?::\d{2})?|¶\d+)\]\s*「([^」]+)」")


def wilson(k, n):
    if not n:
        return 0, 0
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(100 * (c - h)), round(100 * (c + h))


def first_version(root, rel):
    """The full text of a file as git first saw it; None when it is not in git."""
    try:
        sha = subprocess.run(["git", "log", "--diff-filter=A", "--format=%H", "--", rel], cwd=str(root),
                             capture_output=True, text=True, encoding="utf-8").stdout.split()
        if not sha:
            return None
        return subprocess.run(["git", "show", "%s:%s" % (sha[-1], rel)], cwd=str(root), capture_output=True, text=True, encoding="utf-8").stdout
    except OSError:
        return None


def agrees(fm):
    c, v = str(fm.get("chosen") or "").strip(), str(fm.get("verdict") or "").strip()
    option = r"(?:推荐\s*)?([A-Z])(?=$|[\s（(：:、.。])"
    co, vo = (re.match(option, s.strip("*` ")) for s in (c, v))
    return bool(c) and (c == v or c.startswith(AGREE_PREFIX) or bool(co and vo and co[1] == vo[1]))


def ratio(k, n, pct=True):
    if not n:
        return "-"
    if n < 10 or not pct:
        return "%d/%d" % (k, n)
    lo, hi = wilson(k, n)
    return "%d/%d  %d%% [%d,%d]" % (k, n, round(100 * k / n), lo, hi)


def tool_stats(cfg, recs, docs, anchors, rule_ids):
    s = {"n": len(recs), "unanswered": 0, "pending": 0, "valid": 0, "nonblind": 0, "untracked": 0, "agree": 0,
         "right": {k: 0 for k in RIGHT_MARKERS}, "q_ok": 0, "q_all": 0, "r_ok": 0, "r_all": 0, "four": 0, "cite": 0}
    for r in recs:
        fm, basis = r["fm"], r["sections"].get("依据", "")
        chosen, outcome = str(fm.get("chosen") or "").strip(), str(fm.get("outcome") or "").strip()
        s["unanswered"] += not chosen
        s["pending"] += (not outcome) and r["age"] >= 30
        if chosen:
            v = first_version(cfg["root"], r["rel"])
            if v is None:
                s["untracked"] += 1
            else:
                f0, _, _ = shapes.split_frontmatter(v)
                if f0 and f0.get("verdict") and not f0.get("chosen"):
                    s["valid"] += 1
                    s["agree"] += agrees(fm)
                else:
                    s["nonblind"] += 1
            if not agrees(fm) and outcome:
                for k in s["right"]:
                    if k in outcome or (k == "我对" and "你对" in outcome):
                        s["right"][k] += 1
        for m in RE_QUOTE.finditer(r["body"]):
            doc, q = m.group(1) or m.group(3) or m.group(5), m.group(2) or m.group(4) or m.group(6)
            s["q_all"] += 1
            s["q_ok"] += any(re.sub(r"\s+", "", q) in re.sub(r"\s+", "", t) for t in docs.get(doc, []))
        for a in set(re.findall(r"\^p\d+", r["body"])):
            s["q_all"] += 1
            s["q_ok"] += a in anchors
        for rid in shapes.rule_refs(basis, rule_ids):
            s["r_all"] += 1
            s["r_ok"] += rid in rule_ids
        sec = r["sections"]
        s["four"] += all(sec.get(h, "").strip() for h in ("依据", "最强反证", "什么会改判")) and ("上次" in basis or "records/" in basis)
        s["cite"] += "records/" in basis
    return s


def page(cfg, records, today, docs=None, anchors=None, rule_ids=None):
    docs, anchors, rule_ids = docs or {}, anchors or set(), rule_ids or set()
    tools = [t["name"] for t in cfg["tools"]] or sorted({r["fm"].get("tool") for r in records})
    stats = {t: tool_stats(cfg, [r for r in records if r["fm"].get("tool") == t], docs, anchors, rule_ids) for t in tools}
    head = "# Sync rate (numbers page) · %s · machine entryplug %s · records %d (%s) · unanswered %d · outcome pending %d" % (
        today, __version__, len(records), " · ".join("%s %d" % (t, stats[t]["n"]) for t in tools) or "no equipment",
        sum(s["unanswered"] for s in stats.values()), sum(s["pending"] for s in stats.values()))
    rows = [("agreement rate (blind-valid)", lambda s: ratio(s["agree"], s["valid"]) + ("  likely sycophancy" if s["valid"] >= 30 and s["agree"] / s["valid"] > 0.95 else "") + ("  (%d non-blind excluded)" % s["nonblind"] if s["nonblind"] else "") + ("  (%d untracked, not counted)" % s["untracked"] if s["untracked"] else "")),
            ("who was right after a disagreement", lambda s: " · ".join("%s %d" % (RIGHT_MARKERS[k], v) for k, v in s["right"].items()) if any(s["right"].values()) else "0 decidable"),
            ("quotes verifiable", lambda s: ratio(s["q_ok"], s["q_all"], pct=s["q_all"] >= 10)),
            ("rule references real", lambda s: ratio(s["r_ok"], s["r_all"], pct=False)),
            ("four elements present", lambda s: ratio(s["four"], s["n"], pct=False)),
            ("cites earlier records", lambda s: ratio(s["cite"], s["n"], pct=False) if s["n"] >= 10 else "n<10, not reported (%d/%d)" % (s["cite"], s["n"]))]
    lines = [head, "", "| metric | " + " | ".join(tools) + " |", "|---|" + "---|" * len(tools)]
    lines += ["| %s | %s |" % (name, " | ".join(fn(stats[t]) for t in tools)) for name, fn in rows]
    lines += ["", "Mechanical accuracy is computed by the machine (trustworthy from the first record); judgment accuracy "
                  "comes only from the owner's chosen / outcome. Reported per equipment; below n=10 only k of n; never a total."]
    return "\n".join(lines) + "\n"
