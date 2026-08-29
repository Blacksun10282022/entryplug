# 做什么：`plug check`——体检清单（ERROR / WARNING，逐项带核验时间戳，永不聚合成分）+ 头部自检（形状版本 · 索引新旧 · 钩子上次触发 · 挂了哪些装备）
#         + 跑每件装备自带的 checks/（通用挂点）+ 30 天没批的改装申请移到 rejected/ + 一页报告（本周记录 · 分歧 · 待批 · 待填结果 · 过期资料 · 孤立词条 · 同步率）。
# 输入：cfg；expire=False 时不移提议（pre-commit 里用）；today 可注入（测试用）。
# 输出：run() → dict{errors, warnings, header, moved, records, proposals, materials, entries, orphans, numbers}；report() → 一页文本；同时写 self/数字.md。
# 不做什么：不改任何内容文件（唯一的写入是移过期提议与写数字页）；不打分；不调 LLM；不定时。
# 谁调用：cli（plug check）· gates/precommit（0 ERROR 才放行）· apply（落地前后）· tests。
# ERROR（§6.4）：形状 · [[链接]] 不解析 · 观察行缺 src · 锚句找不到 · ^p 不解析 · 记录点名的 R-id 不存在 · 跨未声明依赖的链接 · 形状版本不认识 · 挂点退出码 2。
# WARNING：页太长 · 标题/别名撞车 · 概念别名 <2 · 新条目入链 <3 · 提议重复 · 记录 30 天没结果 · 资料过期 · index.md 不全/过大 · 路径与命令不解析 ·
#          规则没日期 · 规则到期/待复核 · 说明书 description 超预算 · 钩子没触发 · [?] 对账不符 · warning 打法给了指向对方的动作 · 机器版本钉不对 · 索引过期。
# 依赖：stdlib（subprocess 只用来问 git 与跑挂点）· shapes · config · numbers。
import hashlib, os, re, sqlite3, subprocess, sys, time
from datetime import date
from . import __version__, SHAPE_VERSION, config, shapes

HOOKS = ("precommit", "outbound", "precompact")
PATHISH = re.compile(r"(?<![\w/`.])((?:self|tools|proposals|playbooks|dict|corpus|materials|records|checks)/[\w\-./]*\w)")
OTHER_PARTY = re.compile(r"^\s*[-*]\s*(让|叫|要求|告诉|向|逼|劝)对方")
DESC_ONE, DESC_TOTAL, EXPIRE_DAYS, HOOK_DAYS, NEW_DAYS = 1536, 4000, 30, 30, 30


def git_added(root):
    """{rel: 首次入库日期}；不是 git 仓库时 {}。"""
    try:
        out = subprocess.run(["git", "log", "--diff-filter=A", "--format=@%cs", "--name-only"], cwd=str(root),
                             capture_output=True, text=True, encoding="utf-8").stdout
    except OSError:
        return {}
    added, d = {}, None
    for line in out.splitlines():
        if line.startswith("@"):
            d = line[1:]
        elif line.strip() and d:
            added.setdefault(line.strip(), d)
    return added


def age_days(f, fm, added, today):
    """文件年龄：文件名前缀日期 → by 字段日期 → git 入库日 → mtime。"""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", f["path"].name) or re.search(r"(\d{4}-\d{2}-\d{2})", str(fm.get("by") or ""))
    s = m.group(1) if m else added.get(f["rel"])
    try:
        return (today - date.fromisoformat(s)).days if s else int((time.time() - f["path"].stat().st_mtime) // 86400)
    except ValueError:
        return 0


def quote_in(docs, doc_id, quote):
    q = re.sub(r"\s+", "", quote)
    return any(q in re.sub(r"\s+", "", t) for t in docs.get(doc_id, []))


def run(cfg, expire=True, tool_checks=True, today=None):
    today, at, root = today or date.today(), time.strftime("%Y-%m-%d %H:%M"), cfg["root"]
    E, W, moved = [], [], []
    err = lambda code, f, msg: E.append({"level": "ERROR", "code": code, "file": f, "msg": msg, "at": at})
    warn = lambda code, f, msg: W.append({"level": "WARNING", "code": code, "file": f, "msg": msg, "at": at})
    shape_ok, machine_ok = config.version_ok(cfg)
    header = {"at": at, "machine": __version__, "machine_pin": cfg["machine_pin"], "shape_version": cfg.get("shape_version"),
              "shape_ok": shape_ok, "tools": [t["name"] for t in cfg["tools"]], "hooks": {}, "index_built": None, "index_stale": None}
    out = {"errors": E, "warnings": W, "header": header, "moved": moved, "records": [], "proposals": [], "materials": [],
           "entries": {}, "orphans": [], "numbers": "", "rules": None}
    if not shape_ok:
        err("shape_version", "plug.yaml", "形状版本 %r 机器不认识（本机 v%d）——机器拒跑" % (cfg.get("shape_version"), SHAPE_VERSION))
        return out
    if not machine_ok:
        warn("machine_pin", "plug.yaml", "钉住的机器版本「%s」≠ 当前 %s" % (cfg["machine_pin"], __version__))
    for t in cfg["tools"]:
        if not t["dir"].is_dir():
            err("tool_path", "plug.yaml", "挂载的装备目录不存在：%s" % t["path"])
    added, docs, entries, records, proposals, materials, manuals, rules, hashes = git_added(root), {}, {}, [], [], [], [], None, {}
    tool_of = {t["name"]: t for t in cfg["tools"]}
    for f in config.walk(cfg):
        if f["area"] == "checks":
            continue
        text = f["path"].read_text(encoding="utf-8")
        hashes[f["rel"]] = (hashlib.sha1(text.encode("utf-8")).hexdigest(), f["area"])
        if f["area"] == "corpus":
            d = shapes.parse_doc(text, f["path"], f["sub"])
            docs.setdefault(d["id"], []).append(d["text"])
            continue
        if f["area"] == "rules":
            rules = shapes.parse_rules(text)
            rules["text"] = text
            continue
        if f["area"] in ("style", "facts", "reading"):
            continue
        p = shapes.parse_file(text, f["area"])
        p.update(f, age=age_days(f, p["fm"], added, today), text=text)
        for e in p["errors"]:
            err("shape", f["rel"], e)
        {"dict": entries, "playbook": entries}.get(f["area"], {}).__setitem__(f["rel"], p) if f["area"] in ("dict", "playbook") else \
            {"record": records, "proposal": proposals, "material": materials, "manual": manuals}[f["area"]].append(p)
    out.update(records=records, proposals=proposals, materials=materials, entries=entries, rules=rules)
    # —— 条目：标题 / 别名 · 链接 · 观察行 ——
    names, anchors, inbound = {}, set(), {rel: 0 for rel, p in entries.items() if p["area"] == "dict"}
    for rel, p in entries.items():
        for nm in [p["fm"].get("title")] + list(p["fm"].get("aliases") or []):
            key = (p["tool"], str(nm))
            if key in names and names[key] != rel:
                warn("collision", rel, "标题 / 别名「%s」与 %s 撞车" % (nm, names[key]))
            names.setdefault(key, rel)
        anchors |= {o["anchor"] for o in p["obs"] if o["anchor"]}
    for rel, p in entries.items():
        tool, fm = p["tool"], p["fm"]
        for link in p["links"]:
            t2, _, name = link.rpartition("/")
            t2 = t2 or tool
            if t2 != tool and t2 not in tool_of.get(tool, {}).get("depends", []):
                err("cross_tool", rel, "[[%s]] 指向未声明依赖的装备 %s" % (link, t2))
            elif (t2, name) not in names:
                err("link", rel, "[[%s]] 解析不到任何标题或别名" % link)
            elif names[(t2, name)] != rel and names[(t2, name)] in inbound:
                inbound[names[(t2, name)]] += 1
        for o in p["obs"]:
            where = "%s:%d" % (rel, o["line"])
            if o["missing_src"]:
                err("obs_src", where, "观察行缺 (src: …)")
                continue
            for ref in o["refs"]:
                if ref not in anchors:
                    err("pid", where, "%s 不解析（没有这个锚点）" % ref)
            if o["quote"] is not None and o["doc"]:
                if o["doc"] not in docs:
                    err("anchor", where, "教材里没有 doc「%s」" % o["doc"])
                elif not quote_in(docs, o["doc"], o["quote"]):
                    err("anchor", where, "锚句在 %s 里找不到：「%s」" % (o["doc"], o["quote"][:30]))
            elif not o["refs"] and not o["unanchored"]:
                err("obs_src", where, "src 既无锚句也无 ^p 引用（无原句请标 [未锚]）")
        if len(p["body"]) > 4000 or len(p["obs"]) > 25:
            warn("long", rel, "页太长（%d 字 · 观察 %d 行）" % (len(p["body"]), len(p["obs"])))
        if fm.get("kind") == "concept" and len(fm.get("aliases") or []) < 2:
            warn("aliases", rel, "概念别名 <2")
        if fm.get("stance") in ("warning", "diagnostic"):
            for sec in ("动作", "练习"):
                for line in p["sections"].get(sec, "").splitlines():
                    if OTHER_PARTY.match(line):
                        warn("warning_action", rel, "stance=%s 的打法给了指向对方的动作：%s" % (fm["stance"], line.strip()[:40]))
    for rel in inbound:
        if inbound[rel] < 3 and entries[rel]["age"] <= NEW_DAYS:
            warn("inbound", rel, "新条目入链 %d（<3）" % inbound[rel])
    out["orphans"] = sorted(rel for rel, n in inbound.items() if n == 0)
    for t in cfg["tools"]:
        if t.get("unreviewed") is not None:
            n = sum(o["unreviewed"] for rel, p in entries.items() if p["tool"] == t["name"] for o in p["obs"])
            if n != t["unreviewed"]:
                warn("unreviewed", t["path"], "[?] 行数 %d 与对账 %d 不符" % (n, t["unreviewed"]))
    # —— 规则 · 记录 · 提议 · 资料 · 说明书 ——
    ids = rules["ids"] if rules else set()
    if rules:
        for k in ("model", "reviewed"):
            if not rules["header"].get(k):
                warn("rules_header", "self/RULES.md", "文件头缺 %s:" % k)
        for s in rules["sections"]:
            if s["expires"] and s["expires"] < today.isoformat():
                warn("rules_expired", "self/RULES.md", "小节「%s」已到期，整节失效，须重写" % s["name"])
            for l in s["lines"]:
                if not l["dated"] and "退役" not in s["name"]:
                    warn("rule_date", "self/RULES.md", "%s 没带日期" % l["id"])
                for rv in filter(None, (l["review"], s["review"])):
                    if rv < today.strftime("%Y-%m"):
                        warn("rules_review", "self/RULES.md", "%s 复核 %s 已过" % (l["id"], rv))
    prefixes = "|".join(sorted({re.match(r"[A-Z]+", i).group(0) for i in ids})) if ids else None
    for r in records:
        if prefixes:
            for rid in re.findall(r"(?<![A-Za-z0-9])((?:%s)\d{1,3})(?![A-Za-z0-9])" % prefixes, r["sections"].get("依据", "")):
                if rid not in ids:
                    err("rid", r["rel"], "依据点名的 %s 在 RULES.md 里不存在" % rid)
        if not r["fm"].get("outcome") and r["age"] >= 30:
            warn("outcome", r["rel"], "记录 %d 天没填结果" % r["age"])
    seen_p = {}
    for p in [x for x in proposals if x["sub"] == "pending"]:
        key = (str(p["fm"].get("target")), str(p["fm"].get("from")))
        if key in seen_p:
            warn("dup", p["rel"], "提议重复（同 target + 同 from）：%s" % seen_p[key])
        seen_p.setdefault(key, p["rel"])
        if expire and p["age"] > EXPIRE_DAYS:
            dst = cfg["proposals_dir"] / "rejected" / p["path"].name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(p["text"].rstrip("\n") + "\n\nrejected: %s · expired（%d 天未批，plug check 自动移入）\n" % (today, p["age"]), encoding="utf-8")
            p["path"].unlink()
            moved.append(p["rel"])
    for m in materials:
        ttl = tool_of.get(m["tool"], {}).get("ttl_days", {})
        days = ttl.get(str(m["fm"].get("kind")), ttl.get("default", 90))
        if m["age"] > days:
            warn("expired", m["rel"], "资料超过保质期（%s：%d 天 > %d）" % (m["fm"].get("kind"), m["age"], days))
            m["expired"] = True
    total = 0
    for m in manuals:
        d = str(m["fm"].get("description") or "") + str(m["fm"].get("when_to_use") or "")
        total += len(d)
        if len(d) > DESC_ONE:
            warn("desc", m["rel"], "description %d 字符 > %d，列表里会被截" % (len(d), DESC_ONE))
    if total > DESC_TOTAL:
        warn("desc", "tools", "说明书 description 总长 %d > 列表预算 %d" % (total, DESC_TOTAL))
    # —— 路径与命令 · index.md · 钩子 · 索引新旧 · 挂点 ——
    for rel, text, base in ([("self/RULES.md", rules["text"], root)] if rules else []) + \
            [(m["rel"], m["text"], m["path"].parent) for m in manuals] + \
            [(n, (root / n).read_text(encoding="utf-8"), root) for n in ("CLAUDE.md", "AGENTS.md") if (root / n).exists()]:
        for tok in set(PATHISH.findall(text)):
            if "<" not in tok and not any((b / tok).exists() for b in (root, base, cfg["self_dir"])):
                warn("path", rel, "路径解析不到现存对象：%s" % tok)
        for verb in set(re.findall(r"\bplug\s+([a-z]+)", text)):
            if verb not in ("index", "check", "apply", "eval", "search", "mcp", "hash"):
                warn("path", rel, "命令 plug %s 不存在" % verb)
    md = cfg["index_md_path"]
    if not md.exists():
        warn("index_md", cfg["index_md"], "index.md 不存在（先 plug index）")
    else:
        lines = md.read_text(encoding="utf-8")
        missing = [rel for rel in entries if rel not in lines]
        if missing:
            warn("index_md", cfg["index_md"], "index.md 不完整，缺 %d 页（如 %s）" % (len(missing), missing[0]))
        if len(lines) > 200_000:
            warn("index_md", cfg["index_md"], "index.md 过大（%d 字符）" % len(lines))
    for h in HOOKS:
        stamp = cfg["hooks_dir"] / h
        last = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else None
        header["hooks"][h] = last
        if not last or (today - date.fromisoformat(last[:10])).days > HOOK_DAYS:
            warn("hook", ".kb/hooks/" + h, "钩子 %s %s" % (h, "从没触发过" if not last else "上次触发 %s，超过 %d 天" % (last, HOOK_DAYS)))
    if cfg["index_path"].exists():
        con = sqlite3.connect("file:%s?mode=ro" % cfg["index_path"].as_posix(), uri=True)
        meta, indexed = dict(con.execute("select key, value from meta")), dict(con.execute("select rel, hash from files"))
        con.close()
        header["index_built"] = meta.get("built_at")
        header["index_stale"] = any(indexed.get(rel, h if area in ("corpus", "proposal") else None) != h for rel, (h, area) in hashes.items()) \
            or any(rel not in hashes for rel in indexed)
    else:
        header["index_stale"] = True
    if header["index_stale"]:
        warn("index_stale", cfg["index"], "索引比内容旧（或不存在），先 plug index")
    if tool_checks:
        for t in cfg["tools"]:
            for s in sorted((t["dir"] / "checks").glob("*.py")) if (t["dir"] / "checks").is_dir() else []:
                rel, env = config.rel(cfg, s), dict(os.environ, PLUG_ROOT=str(root), PLUG_TOOL=t["name"], PLUG_TOOL_DIR=str(t["dir"]), PYTHONIOENCODING="utf-8")
                try:
                    r = subprocess.run([sys.executable, str(s)], cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
                except subprocess.TimeoutExpired:
                    warn("tool_check", rel, "挂点超时 60 s")
                    continue
                for line in r.stdout.splitlines():
                    (err if r.returncode == 2 else warn)("tool_check", rel, line.strip())
                if r.returncode not in (0, 2):
                    warn("tool_check", rel, "挂点退出码 %d：%s" % (r.returncode, r.stderr.strip()[-160:]))
    from . import numbers
    out["numbers"] = numbers.page(cfg, records, today, docs, anchors, ids)
    cfg["numbers_path"].parent.mkdir(parents=True, exist_ok=True)
    cfg["numbers_path"].write_text(out["numbers"], encoding="utf-8")
    return out


def format_findings(r):
    lines = ["%s %s · %s · %s · 核验 %s" % (f["level"], f["code"], f["file"], f["msg"], f["at"]) for f in r["errors"] + r["warnings"]]
    return "\n".join(lines + ["ERROR %d · WARNING %d" % (len(r["errors"]), len(r["warnings"]))])


def report(cfg, r):
    """一页报告：头部自检 → 清单 → 本周记录 / 分歧 / 待批 / 待填结果 / 过期资料 / 孤立词条 → 同步率。永远没有总分。"""
    h = r["header"]
    L = ["# plug check · %s · entryplug %s（钉 %s）· 形状 v%s %s" % (h["at"], h["machine"], h["machine_pin"] or "-", h["shape_version"], "✓" if h["shape_ok"] else "✗ 机器拒跑"),
         "索引：%s%s · 钩子：%s · 装备：%s" % (h["index_built"] or "无", "（过期）" if h["index_stale"] else "", " ".join("%s=%s" % (k, (v or "从未")[:16]) for k, v in h["hooks"].items()), ", ".join(h["tools"]) or "无"),
         "", format_findings(r)]
    if r["moved"]:
        L.append("移到 rejected/（30 天未批）：" + ", ".join(r["moved"]))
    recs = r["records"]
    week = [x["rel"] for x in recs if x["age"] <= 7]
    dis = [x["rel"] for x in recs if x["fm"].get("chosen") and not (x["fm"].get("chosen") or "").startswith(("同意", "同 ", "按它")) and str(x["fm"].get("chosen")).strip() != str(x["fm"].get("verdict")).strip()]
    L += ["", "本周记录 %d：%s" % (len(week), ", ".join(week) or "-"), "分歧（verdict ≠ chosen）%d：%s" % (len(dis), ", ".join(dis) or "-"),
          "待批提议 %d：%s" % (len([p for p in r["proposals"] if p["sub"] == "pending"]), ", ".join(p["rel"] for p in r["proposals"] if p["sub"] == "pending") or "-"),
          "待填结果（≥30 天）%d：%s" % (len([x for x in recs if not x["fm"].get("outcome") and x["age"] >= 30]), ", ".join(x["rel"] for x in recs if not x["fm"].get("outcome") and x["age"] >= 30) or "-"),
          "过期资料 %d：%s" % (len([m for m in r["materials"] if m.get("expired")]), ", ".join(m["rel"] for m in r["materials"] if m.get("expired")) or "-"),
          "孤立词条（无入链）%d：%s" % (len(r["orphans"]), ", ".join(r["orphans"]) or "-"), "", r["numbers"]]
    return "\n".join(L)
