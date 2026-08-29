# 做什么：同步率（数字页）——从驾驶日志（记录）算「机械准」与「判断准」，写成一页 markdown；永远分开算、永远没有总分。
# 输入：cfg · 已解析的记录列表（check.run 给的：fm · sections · rel · age）· today · 教材 docs（锚句核对）· 锚点集合 · 规则 id 集合。
# 输出：page() → markdown 文本（check 写到 self/数字.md，并附在报告末尾）。
# 不做什么：不打总分；不让 LLM 判；n<10 只写「几分之几」；不当控制信号（只报告）。
# 谁调用：check.run。
# 机械准（机器算，第一条起）：引文可核率 · 规则引用真实率 · 四要素齐全率 · 引记录率（≥10 条后）。
# 判断准（数据只来自主人）：同意率（盲判有效的记录，Wilson 95% 区间）· 分歧后谁对（outcome 里的 它对 / 我对 / 说不清 计数）。
# 盲判有效（D10）：git 里该文件首次入库的版本 verdict 非空且 chosen 为空；一次写入就带 chosen 的标「非盲」不计；未入库的不计入分母。
# 同意（D09）：chosen 规范化后等于 verdict，或以「同意 / 同 / 按它」开头。n≥30 且同意率 >95% 自动标「疑似附和」。
# 依赖：stdlib（subprocess 只问 git）· shapes.split_frontmatter。
import math, re, subprocess
from . import __version__, shapes

AGREE_PREFIX = ("同意", "同 ", "按它", "按 verdict")
RE_QUOTE = re.compile(r"\(src:\s*([A-Za-z0-9][\w\-\.]*)(?:#[\w\-:\.]+)?\s+\"([^\"]+)\"\s*\)|([A-Za-z0-9][\w\-\.]*)@[\d:\.]+「([^」]+)」")


def wilson(k, n):
    if not n:
        return 0, 0
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(100 * (c - h)), round(100 * (c + h))


def first_version(root, rel):
    """文件首次入库时的全文；不在 git 里 → None。"""
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
    return bool(c) and (c == v or c.startswith(AGREE_PREFIX))


def ratio(k, n, pct=True):
    if not n:
        return "-"
    if n < 10 or not pct:
        return "%d/%d" % (k, n)
    lo, hi = wilson(k, n)
    return "%d/%d  %d%% [%d,%d]" % (k, n, round(100 * k / n), lo, hi)


def tool_stats(cfg, recs, docs, anchors, rule_ids):
    s = {"n": len(recs), "unanswered": 0, "pending": 0, "valid": 0, "nonblind": 0, "untracked": 0, "agree": 0,
         "right": {"它对": 0, "我对": 0, "说不清": 0}, "q_ok": 0, "q_all": 0, "r_ok": 0, "r_all": 0, "four": 0, "cite": 0}
    prefixes = "|".join(sorted({re.match(r"[A-Z]+", i).group(0) for i in rule_ids})) if rule_ids else None
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
            doc, q = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            s["q_all"] += 1
            s["q_ok"] += any(re.sub(r"\s+", "", q) in re.sub(r"\s+", "", t) for t in docs.get(doc, []))
        for a in set(re.findall(r"\^p\d+", r["body"])):
            s["q_all"] += 1
            s["q_ok"] += a in anchors
        if prefixes:
            for rid in re.findall(r"(?<![A-Za-z0-9])((?:%s)\d{1,3})(?![A-Za-z0-9])" % prefixes, basis):
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
    head = "# 同步率（数字页）· %s · 机器 entryplug %s · 记录 %d（%s）· 未答 %d · 待填结果 %d" % (
        today, __version__, len(records), " · ".join("%s %d" % (t, stats[t]["n"]) for t in tools) or "无装备",
        sum(s["unanswered"] for s in stats.values()), sum(s["pending"] for s in stats.values()))
    rows = [("同意率（盲判有效）", lambda s: ratio(s["agree"], s["valid"]) + ("  疑似附和" if s["valid"] >= 30 and s["agree"] / s["valid"] > 0.95 else "") + ("（非盲 %d 已剔）" % s["nonblind"] if s["nonblind"] else "") + ("（未入库 %d 不计）" % s["untracked"] if s["untracked"] else "")),
            ("分歧后谁对", lambda s: " · ".join("%s %d" % kv for kv in s["right"].items()) if any(s["right"].values()) else "0 条可判"),
            ("引文可核率", lambda s: ratio(s["q_ok"], s["q_all"], pct=s["q_all"] >= 10)),
            ("规则引用真实率", lambda s: ratio(s["r_ok"], s["r_all"], pct=False)),
            ("四要素齐全率", lambda s: ratio(s["four"], s["n"], pct=False)),
            ("引记录率", lambda s: ratio(s["cite"], s["n"], pct=False) if s["n"] >= 10 else "n<10 不报（%d/%d）" % (s["cite"], s["n"]))]
    lines = [head, "", "| 指标 | " + " | ".join(tools) + " |", "|---|" + "---|" * len(tools)]
    lines += ["| %s | %s |" % (name, " | ".join(fn(stats[t]) for t in tools)) for name, fn in rows]
    lines += ["", "机械准由机器算（第一条起可信）；判断准只来自主人的 chosen / outcome。按装备分开；n<10 只写几分之几；永远没有总分。"]
    return "\n".join(lines) + "\n"
