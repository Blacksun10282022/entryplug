# 做什么：`plug index`——走内容仓库 → 形状校验 → 分块 → tokens（jieba 词 + 字二元组）→ 一张 FTS5 表；
#         按文件哈希增量；顺手生成人读的 index.md、每件装备的 playbooks/INDEX.md，并把 SKILL.md 镜像到各驾驶员的 skills 目录。
# 输入：cfg（config.load）；full=True 强制全量重建。
# 输出：.kb/index.sqlite（表 fts + 记账表 files / meta）· index.md · tools/<t>/playbooks/INDEX.md · <skills>/<t>/SKILL.md；返回统计 dict。
# 不做什么：不重排、不调 LLM、不做向量；不改任何内容文件；教材只取纯文本段（带时间戳段是副本，不进索引）。
# 谁调用：cli（plug index）· gates/precommit（提交前重建）· tests。
# 分块：教材按段落为单位（清洗稿一段一行、带 [m:ss] 位置），段落 >800 字再切 600/100 滑窗；行号 1 起，供 Read/sed 用。
# 行 id：条目 = 文件 stem；教材 = doc#段号（单段文档 = doc#窗口号）；记录 / 资料 / 提议 = 文件 stem。
# 同一 doc id 同时有 corpus/clean 与 corpus/raw 时只索引 clean（raw 是真相，clean 是视图；锚句核对在 check 两边都查）。
# 依赖：stdlib sqlite3（FTS5）· jieba · PyYAML（经 shapes）。
import hashlib, json, re, shutil, sqlite3, time
import jieba
from . import __version__, SHAPE_VERSION, config, shapes

jieba.setLogLevel(60)
CJK = re.compile(r"[一-鿿]+")
CHUNK, OVERLAP, MAX_UNIT = 600, 100, 800
SCHEMA = [
    "create virtual table if not exists fts using fts5(tokens, id unindexed, doc unindexed, title unindexed, tool unindexed,"
    " kind unindexed, scope unindexed, file unindexed, lstart unindexed, lend unindexed, pos unindexed, excerpt unindexed,"
    " tokenize='unicode61')",
    "create table if not exists files(rel text primary key, hash text, mtime real)",
    "create table if not exists meta(key text primary key, value text)",
]


def tokens(text):
    """jieba 词（≥2 字）+ 拉丁词（小写）+ 所有中文字二元组，空格拼好。两字词「责任」直接命中。"""
    out = []
    for w in jieba.lcut(text):
        w = w.strip()
        if CJK.fullmatch(w) and len(w) >= 2:
            out.append(w)
        elif re.fullmatch(r"[A-Za-z0-9]+", w):
            out.append(w.lower())
    for run in CJK.findall(text):
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return out


def paragraphs(unit):
    """一个 unit(lstart, lend, pos, text) → 按空行切成段落，行号精确。"""
    lstart, _, pos, text = unit
    out, buf, first = [], [], None
    for i, line in enumerate(text.split("\n")):
        if line.strip():
            if first is None:
                first = i
            buf.append(line)
        elif buf:
            out.append((lstart + first, lstart + i - 1, pos, "\n".join(buf)))
            buf, first = [], None
    if buf:
        out.append((lstart + first, lstart + first + len(buf) - 1, pos, "\n".join(buf)))
    return out


def windows(par):
    """段落 ≤800 字整段一块；更长的切 600/100 滑窗，行号按字符位置折算。"""
    lstart, lend, pos, text = par
    if len(text) <= MAX_UNIT:
        return [par]
    starts, acc = [], 0
    for line in text.split("\n"):
        starts.append(acc)
        acc += len(line) + 1
    def line_at(off):
        return lstart + max(i for i, s in enumerate(starts) if s <= off)
    out, i = [], 0
    while i < len(text):
        piece = text[i:i + CHUNK]
        out.append((line_at(i), line_at(min(i + len(piece) - 1, len(text) - 1)), pos, piece))
        i += CHUNK - OVERLAP
    return out


def excerpt(text, n=120):
    return re.sub(r"\s+", " ", text).strip()[:n]


def file_rows(f, parsed, tool):
    """一个内容文件 → 若干行 (tokens, id, doc, title, tool, kind, scope, file, lstart, lend, pos, excerpt)。"""
    rel, area, fm, body = f["rel"], f["area"], parsed["fm"], parsed["body"]
    stem = f["path"].stem
    kind = {"dict": fm.get("kind", "concept"), "playbook": "playbook", "record": "record", "material": "material",
            "manual": "manual", "rules": "rule", "facts": "fact", "style": "style", "reading": "reading",
            "proposal": "proposal"}[area]
    title = str(fm.get("title") or fm.get("situation") or fm.get("name") or fm.get("target") or stem)
    prefix = " ".join([title] + [str(a) for a in fm.get("aliases") or []] + [str(fm.get("verdict") or "")])
    text = f["path"].read_text(encoding="utf-8")
    body_start = text[:len(text) - len(body)].count("\n") + 1 + (len(body) - len(body.lstrip("\n")))
    body_lines = body.strip("\n").split("\n")
    page = (body_start, body_start + len(body_lines) - 1, "", "\n".join(body_lines))   # 一页一块；>800 字才切窗
    scope = "proposals" if area == "proposal" else "tools"
    return [(" ".join(tokens(prefix + " " + w[3])), stem, stem, title, tool or "", kind, scope, rel, w[0], w[1], w[2], excerpt(w[3]))
            for w in windows(page)]


def doc_rows(f, doc, tool):
    pars = [p for u in doc["units"] for p in paragraphs(u)]
    rows, single = [], len(pars) == 1
    for n, par in enumerate(pars, 1):
        ws = windows(par)
        for m, w in enumerate(ws, 1):
            seq = str(m) if single else (str(n) if len(ws) == 1 else "%d.%d" % (n, m))
            rows.append((" ".join(tokens(w[3])), "%s#%s" % (doc["id"], seq), doc["id"], doc["title"], tool, "corpus",
                         "corpus", f["rel"], w[0], w[1], w[2], excerpt(w[3])))
    return rows


def build(cfg, full=False):
    """增量建索引。返回 {files, chunks, changed, removed, entries, docs, errors}。"""
    cfg["index_path"].parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(cfg["index_path"])
    for s in SCHEMA:
        con.execute(s)
    known = dict(con.execute("select rel, hash from files")) if not full else {}
    if full:
        con.execute("delete from fts"), con.execute("delete from files")
    files = [f for f in config.walk(cfg) if f["area"] != "checks"]
    docs, seen, aliases, entries, playbooks, stats = {}, set(), {}, [], {}, {"changed": 0, "chunks": 0, "errors": []}
    for f in [x for x in files if x["area"] == "corpus"]:           # clean 先于 raw；同 id 只留 clean
        d = shapes.parse_doc(f["path"].read_text(encoding="utf-8"), f["path"], f["sub"])
        if d["id"] not in docs or (f["sub"] == "clean" and docs[d["id"]][0]["sub"] == "raw"):
            docs[d["id"]] = (f, d)
    corpus_files = {id(v[0]) for v in docs.values()}
    for f in files:
        if f["area"] == "corpus" and id(f) not in corpus_files:
            continue
        text = f["path"].read_text(encoding="utf-8")
        seen.add(f["rel"])
        if f["area"] == "corpus":
            d = docs[[k for k, v in docs.items() if v[0] is f][0]][1]
            rows = doc_rows(f, d, f["tool"])
            entries.append((f["tool"], "corpus", f["rel"], d["id"], d["title"], d["kind"], d["date"]))
        elif f["area"] == "proposal" and f["sub"] != "pending":
            continue
        else:
            p = shapes.parse_file(text, f["area"])
            stats["errors"] += ["%s: %s" % (f["rel"], e) for e in p["errors"]]
            rows = file_rows(f, p, f["tool"])
            fm = p["fm"]
            if f["area"] in ("dict", "playbook"):
                aliases[str(fm.get("title"))] = [str(a) for a in fm.get("aliases") or []]
            if f["area"] == "playbook":
                playbooks.setdefault(f["tool"], []).append((f["path"].stem, fm.get("stance"), fm.get("situation"), fm.get("when_not")))
            if f["area"] == "proposal":
                playbooks.setdefault("_pending", []).append((f["rel"], str(fm.get("target"))))
            extra = fm.get("date") or fm.get("by") or ", ".join(str(a) for a in fm.get("aliases") or []) or fm.get("stance") or ""
            entries.append((f["tool"], f["area"], f["rel"], f["path"].stem, rows[0][3] if rows else f["path"].stem,
                            fm.get("kind") or f["area"], str(extra)))
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        stats["chunks"] += len(rows)
        if known.get(f["rel"]) == h:
            continue
        stats["changed"] += 1
        con.execute("delete from fts where file=?", (f["rel"],))
        con.executemany("insert into fts values (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("insert or replace into files values (?,?,?)", (f["rel"], h, time.time()))
    gone = [r for r in known if r not in seen]
    for r in gone:
        con.execute("delete from fts where file=?", (r,)), con.execute("delete from files where rel=?", (r,))
    titles = {d["id"]: d["title"] for _, d in docs.values()}
    for k, v in {"aliases": json.dumps(aliases, ensure_ascii=False), "titles": json.dumps(titles, ensure_ascii=False),
                 "built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "version": __version__, "shape_version": str(SHAPE_VERSION)}.items():
        con.execute("insert or replace into meta values (?,?)", (k, v))
    con.commit(), con.close()
    write_index_md(cfg, entries, stats)
    write_playbook_index(cfg, playbooks)
    mirror_skills(cfg)
    stats.update(files=len(seen), removed=len(gone), entries=len(entries), docs=len(docs))
    return stats


def write_index_md(cfg, entries, stats):
    """人读索引：一页一行。"""
    lines = ["# index · %s · %d 文件 · %d 块 · entryplug %s" % (time.strftime("%Y-%m-%d %H:%M"), len(entries), stats["chunks"], __version__)]
    for tool in [t["name"] for t in cfg["tools"]] + [None]:
        rows = [e for e in entries if e[0] == tool]
        if rows:
            lines.append("## %s" % (("tools/" + tool) if tool else "self · proposals"))
            lines += ["- %s · %s · %s · %s" % (e[2], e[4], e[5], e[6]) for e in rows]
    cfg["index_md_path"].write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_playbook_index(cfg, playbooks):
    """打法目录 INDEX.md：id | stance | situation | when_not；末尾列 pending 里指向新打法的提议。≤60 行。"""
    for t in cfg["tools"]:
        rows = playbooks.get(t["name"], [])
        if not (t["dir"] / "playbooks").is_dir():
            continue
        lines = ["# 打法目录 · %s · 由 plug index 生成，勿手改" % t["name"], "命中不是义务。选不出就报无打法，照常分析。", "",
                 "| id | stance | situation | when_not |", "|---|---|---|---|"]
        lines += ["| %s | %s | %s | %s |" % r for r in rows]
        new = [(rel, tg) for rel, tg in playbooks.get("_pending", []) if "/playbooks/" in tg and not (cfg["root"] / tg).exists()]
        if new:
            lines += ["", "## 待批的「无打法」提议"] + ["- %s → %s" % x for x in new]
        (t["dir"] / "playbooks" / "INDEX.md").write_text("\n".join(lines[:60]) + "\n", encoding="utf-8", newline="\n")


def mirror_skills(cfg):
    """把每件装备的 SKILL.md 复制到各驾驶员的 skills 目录（内容相同则不动）。"""
    for name, pilot in cfg["pilots"].items():
        for t in cfg["tools"]:
            src = t["dir"] / "SKILL.md"
            if src.exists():
                dst = cfg["root"] / pilot["skills"] / t["name"] / "SKILL.md"
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists() or dst.read_bytes() != src.read_bytes():
                    shutil.copyfile(src, dst)
                if name == "codex" and not (dst.parent / "agents" / "openai.yaml").exists():   # Codex 的隐式调用开关不在 frontmatter
                    (dst.parent / "agents").mkdir(exist_ok=True)
                    (dst.parent / "agents" / "openai.yaml").write_text("policy:\n  allow_implicit_invocation: true\n", encoding="utf-8", newline="\n")
