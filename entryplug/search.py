# What: the single query function shared by `plug search` and MCP `search` — take one or more queries →
#       deterministic alias expansion → FTS5 OR query → round-robin merge of each query's list → per-doc cap →
#       grouped by doc → compact index lines + a tail line "showing k/N".
# In:   cfg · queries (str or list) · scope (tools default / corpus / all) · tool · kind · k (8 → max 60) · per_doc (2 → max 5).
# Out:  {"rows": [...], "shown", "total", "queries"}; format_rows() renders text:
#       id · source · file#Lstart-Lend [pos] · kind · excerpt (<=120 chars).
# Not:  no reranking, no scoring, no window reading (that is the pilot's job, §8.1); physically cannot write
#       content (read-only connection); never calls an LLM.
# Who:  cli (plug search) · mcp (tools/call search) · eval (recall@10) · contact (first contact, step 2).
# Note: query construction (D22) — split on whitespace/punctuation; CJK runs of <=4 chars become a bigram phrase,
#       longer runs use jieba words of >=2 chars; a single character becomes a prefix "X"*; latin words lowercased.
#       dense_candidates is the interface stub for entryplug[dense]: same row shape, empty in this version.
# Deps: stdlib sqlite3 · jieba (via index.tokens).
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
    """Alias expansion: if the query contains any member of a group (>=2 chars, or exactly equals a
    one-character title), add every member of that group."""
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
        raise FileNotFoundError("no index at %s: run plug index first" % cfg["index"])
    return sqlite3.connect("file:%s?mode=ro" % cfg["index_path"].as_posix(), uri=True)


def dense_candidates(cfg, queries, scope):
    """Interface stub for entryplug[dense]: returns candidate rows in the same shape as FTS (empty here)."""
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
        lines.append("%s · %s · %s · %s · %s%s" % (r["id"], r["source"], loc, r["kind"], r["excerpt"],
                                                   " · title hit, the whole page is worth reading" if r["title_hit"] else ""))
    tail = "showing %d/%d" % (res["shown"], res["total"])
    if not res["total"]:                    # 0/0 must not stay mute: name the scope and the index time
        hint = {"tools": " (default scope only covers dict · playbooks · records; add scope=corpus for the corpus)",
                "corpus": " (corpus only; use scope=tools for dict · playbooks · records)"}.get(res.get("scope"), "")
        tail += " · no hit in scope %s%s · index built %s" % (res.get("scope"), hint, res.get("built_at") or "never (run plug index)")
    lines.append(tail)
    return "\n".join(lines)
