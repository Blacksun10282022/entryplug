# 做什么：`plug search` 与 MCP `search` 共用的唯一查询函数——收一条或多条查询 → 别名扩展（确定性）→ FTS5 OR 查询
#         → 各查询结果 round-robin 合并去重 → 每讲座限额 → 按讲座分组 → 紧凑索引行 + 尾行「已显示 k/N」。
# 输入：cfg · queries（str 或 list）· scope（tools 默认 / corpus / all）· tool · kind · k（8 → 最多 60）· per_doc（2 → 5）。
# 输出：{"rows": [...], "shown", "total", "queries"}；format() 给出文本：id · 出处 · 文件#L起-L止 [位置] · kind · ≤120 字摘录。
# 不做什么：不重排、不打分、不读窗口（那是驾驶员的事，§8.1）；物理上写不了内容（只读连接）；不调 LLM。
# 谁调用：cli（plug search）· mcp（tools/call search）· eval（recall@10）· contact（初期接触第 2 步）。
# 查询构造（D22）：按空白 / 标点切词；≤4 字中文用字二元组短语，>4 字用 jieba 切出的 ≥2 字词；单字用前缀 "X"*；拉丁词小写。
# dense_candidates 是 entryplug[dense] 的接口桩：同形候选行，本版本返回空列表。
# 依赖：stdlib sqlite3 · jieba（经 index.tokens）。
import json, re, sqlite3
import jieba
from .index import CJK

MAX_K, MAX_PER_DOC, MAX_CANDIDATES, PER_QUERY = 60, 5, 60, 200
SPLIT = re.compile(r"[\s,，。；;、/|·:：()（）「」\"'“”?？!！]+")
COLS = "id, doc, title, tool, kind, file, lstart, lend, pos, excerpt"


def phrase(run):
    return '"' + " ".join(run[i:i + 2] for i in range(len(run) - 1)) + '"'


def term_parts(term):
    out = []
    for run in CJK.findall(term):
        if len(run) == 1:
            out.append('"%s"*' % run)
        elif len(run) <= 4:
            out.append(phrase(run))
        else:
            out += [phrase(w) for w in jieba.lcut(run) if len(w) >= 2] or [phrase(run)]
    out += ['"%s"' % w.lower() for w in re.findall(r"[A-Za-z0-9]+", term) if len(w) >= 2]
    return out


def expand(query, groups):
    """别名扩展：查询里出现某组的任一成员（≥2 字，或恰等于单字标题）→ 加入该组全部成员。"""
    q, extra = query.strip(), []
    for group in groups:
        if any((len(m) >= 2 and m in q) or (len(m) == 1 and m == q) for m in group):
            extra += [m for m in group if m not in q]
    return extra


def fts_query(query, groups):
    parts = []
    for term in SPLIT.split(query):
        parts += term_parts(term) if term else []
    for alias in expand(query, groups):
        parts += term_parts(alias)
    parts = list(dict.fromkeys(parts))
    return " OR ".join(parts) if parts else None


def open_ro(cfg):
    if not cfg["index_path"].exists():
        raise FileNotFoundError("没有索引 %s：先 plug index" % cfg["index"])
    return sqlite3.connect("file:%s?mode=ro" % cfg["index_path"].as_posix(), uri=True)


def dense_candidates(cfg, queries, scope):
    """entryplug[dense] 接口桩：返回与 FTS 同形的候选行列表（本版本无实现，恒为空）。"""
    return []


def search(cfg, queries, scope="tools", tool=None, kind=None, k=8, per_doc=2):
    if isinstance(queries, str):
        queries = [queries]
    queries = [q for q in queries if q and q.strip()]
    k, per_doc = max(1, min(int(k or 8), MAX_K)), max(1, min(int(per_doc or 2), MAX_PER_DOC))
    con = open_ro(cfg)
    meta = dict(con.execute("select key, value from meta"))
    groups = [[t] + a for t, a in json.loads(meta.get("aliases", "{}")).items()]
    titles = json.loads(meta.get("titles", "{}"))
    where, args = [], []
    if scope in ("tools", "corpus"):
        where.append("scope=?"), args.append(scope)
    if tool:
        where.append("tool=?"), args.append(tool)
    if kind:
        where.append("kind=?"), args.append(kind)
    lists, used = [], []
    for q in queries:
        fq = fts_query(q, groups)
        if not fq:
            continue
        used.append(fq)
        sql = "select %s from fts where fts match ? %s order by rank limit %d" % (COLS, "".join(" and " + w for w in where), PER_QUERY)
        lists.append(con.execute(sql, [fq] + args).fetchall())
    lists.append(dense_candidates(cfg, queries, scope))
    con.close()
    merged, seen = [], set()
    for i in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if i < len(l) and l[i][0] not in seen:
                seen.add(l[i][0]), merged.append(l[i])
    per, cands = {}, []
    for r in merged:
        if per.get(r[1], 0) < per_doc:
            per[r[1]] = per.get(r[1], 0) + 1
            cands.append(r)
        if len(cands) >= MAX_CANDIDATES:
            break
    order = list(dict.fromkeys(r[1] for r in cands[:k]))
    shown = sorted(cands[:k], key=lambda r: order.index(r[1]))
    qtext = " ".join(queries)
    rows = [{"id": r[0], "doc": r[1], "source": r[2], "tool": r[3], "kind": r[4], "file": r[5], "lstart": r[6], "lend": r[7],
             "pos": r[8], "excerpt": r[9], "title_hit": any(len(q) >= 2 and q in titles.get(r[1], r[2]) for q in queries + expand(qtext, groups))}
            for r in shown]
    return {"rows": rows, "shown": len(rows), "total": len(cands), "queries": used, "scope": scope, "built_at": meta.get("built_at")}


def format_rows(res):
    lines = []
    for r in res["rows"]:
        loc = "%s#L%s-L%s" % (r["file"], r["lstart"], r["lend"]) + (" [%s]" % r["pos"] if r["pos"] else "")
        lines.append("%s · %s · %s · %s · %s%s" % (r["id"], r["source"], loc, r["kind"], r["excerpt"], " · 标题命中，可整讲读" if r["title_hit"] else ""))
    tail = "已显示 %d/%d" % (res["shown"], res["total"])
    if not res["total"]:                    # 0/0 不能哑着：说清范围与索引时间
        hint = {"tools": "（默认只查词典 · 打法 · 记录；查教材加 scope=corpus）", "corpus": "（只查了教材；查词典 · 打法 · 记录用 scope=tools）"}.get(res.get("scope"), "")
        tail += " · 范围 %s 无命中%s · 索引建于 %s" % (res.get("scope"), hint, res.get("built_at") or "未知（先 plug index）")
    lines.append(tail)
    return "\n".join(lines)
