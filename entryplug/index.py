# What: `plug index` — walk content → shape validation → chunking → tokens (jieba + CJK bigrams) → one FTS5 table;
#       incremental by hash; writes index.md, playbooks/INDEX.md, and mirrors SKILL.md into pilot skills dirs.
# In:   cfg (config.load); full=True forces a complete rebuild.
# Out:  .kb/index.sqlite (fts + files + meta) · index.md · tools/<t>/playbooks/INDEX.md · skills mirrors; stats dict.
# Not:  no reranking, no LLM, no vectors; unchanged files are never re-tokenised (D47); work/ and workshop/ skipped.
# Who:  cli (plug index) · search (auto-rebuild, D76) · status (stale lag, D83) · check (hashes_stale) · tests.
# Note: paragraphs >800 chars split into 600/100 windows with 1-based line numbers; clean beats raw per corpus doc id;
#       pending proposals index 为什么 / 最强反证 only and drop completely when target is excluded (D84).
# Deps: stdlib sqlite3 (FTS5) · jieba · PyYAML (via shapes).
import hashlib, json, re, sqlite3, time
import jieba
from . import __version__, SHAPE_VERSION, config, shapes
from .mirror import mirror_skills, model_invocation_disabled, write_openai_yaml  # noqa: F401
from .pages import (CHUNK, MAX_UNIT, OVERLAP, REASONS, excerpt, paragraphs,       # noqa: F401
                    reason_units, row_title, windows, write_index_md, write_playbook_index)

jieba.setLogLevel(60)
CJK = re.compile(r"[一-鿿]+")
INDEX_RULES = 2          # bump when an unchanged proposal would yield new rows (2 = D84); build re-indexes proposals once
SCHEMA = [
    "create virtual table if not exists fts using fts5(tokens, id unindexed, doc unindexed, title unindexed, tool unindexed,"
    " kind unindexed, scope unindexed, file unindexed, lstart unindexed, lend unindexed, pos unindexed, excerpt unindexed,"
    " tokenize='unicode61')",
    "create table if not exists files(rel text primary key, hash text, mtime real)",
    "create table if not exists meta(key text primary key, value text)",
]


def tokens(text):
    """jieba words (>=2 chars) + latin words (lowercased) + every CJK bigram, space-joined.
    A two-character word like 责任 then matches directly."""
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


def rules_stamp(cfg):
    """What stored rows were built under: INDEX_RULES plus the exclude globs (adding one can hide a pending
    proposal whose own file never moved). build() re-indexes proposals once when the stored stamp differs or is absent."""
    globs = json.dumps(sorted(str(g) for g in cfg.get("exclude") or []), ensure_ascii=False)
    return "%d exclude:%s" % (INDEX_RULES, hashlib.sha1(globs.encode("utf-8")).hexdigest()[:12])


def indexable(cfg):
    """Files that belong to the index (checks and non-pending proposals never enter the index)."""
    return [f for f in config.walk(cfg) if f["area"] != "checks" and not (f["area"] == "proposal" and f["sub"] != "pending")]


def file_rows(f, parsed, tool, text=None):
    """One content file → rows (tokens, id, doc, title, tool, kind, scope, file, lstart, lend, pos, excerpt).
    A pending proposal contributes its reasons only (D84); everything else is one page, cut only above 800 chars."""
    rel, area, fm, body = f["rel"], f["area"], parsed["fm"], parsed["body"]
    stem = f["path"].stem
    if f["sub"] == "kit":
        stem = "kit/" + rel.split("/kit/", 1)[1].rsplit(".", 1)[0]
    kind = {"dict": fm.get("kind", "concept"), "playbook": "playbook", "record": "record", "material": "material",
            "manual": "manual", "rules": "rule", "facts": "fact", "style": "style", "reading": "reading",
            "proposal": "proposal"}[area]
    title = row_title(fm, stem)
    prefix = " ".join([title] + [str(a) for a in fm.get("aliases") or []] + [str(fm.get("verdict") or "")])
    text = f["path"].read_text(encoding="utf-8") if text is None else text
    first_line = text[:len(text) - len(body)].count("\n") + 1
    body_start = first_line + (len(body) - len(body.lstrip("\n")))
    body_lines = body.strip("\n").split("\n")
    units = reason_units(body, first_line) if area == "proposal" else \
        [(body_start, body_start + len(body_lines) - 1, "", "\n".join(body_lines))]
    scope = "proposals" if area == "proposal" else "tools"
    return [(" ".join(tokens(prefix + " " + w[3])), stem, stem, title, tool or "", kind, scope, rel, w[0], w[1], w[2], excerpt(w[3]))
            for u in units for w in windows(u)]


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
    """Incremental build. Returns {files, chunks, changed, removed, entries, docs, errors}. A stored `index_rules` other
    than rules_stamp (absent counts) re-indexes proposals once, never everything: search rebuilds on read (D76, D84)."""
    cfg["index_path"].parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(cfg["index_path"], timeout=10)
    try:
        for s in SCHEMA:
            con.execute(s)
        stamp = rules_stamp(cfg)
        refresh = not full and dict(con.execute("select key, value from meta")).get("index_rules") != stamp
        known = dict(con.execute("select rel, hash from files")) if not full else {}
        counts = dict(con.execute("select file, count(*) from fts group by file")) if known else {}
        if full:
            con.execute("delete from fts"), con.execute("delete from files")
        elif refresh:
            con.execute("delete from fts where scope='proposals'")
        files = indexable(cfg)
        docs, seen, aliases, entries, playbooks, writes = {}, set(), {}, [], {}, []
        stats = {"changed": 0, "chunks": 0, "errors": []}
        for f in [x for x in files if x["area"] == "corpus"]:       # clean beats raw: one doc id keeps clean only
            text = f["path"].read_text(encoding="utf-8")
            d = shapes.parse_doc(text, f["path"], f["sub"])
            if d["id"] not in docs or (f["sub"] == "clean" and docs[d["id"]][0]["sub"] == "raw"):
                docs[d["id"]] = (f, d, text)
        corpus_docs = {id(v[0]): (v[1], v[2]) for v in docs.values()}
        for f in files:
            if f["area"] == "corpus":
                if id(f) not in corpus_docs:
                    continue
                d, text = corpus_docs[id(f)]
            else:
                text = f["path"].read_text(encoding="utf-8")
            seen.add(f["rel"])
            h = hashlib.sha1(text.encode("utf-8")).hexdigest()
            fresh = known.get(f["rel"]) == h and not (refresh and f["area"] == "proposal")
            if f["area"] == "corpus":
                rows = [] if fresh else doc_rows(f, d, f["tool"])
                entries.append((f["tool"], "corpus", f["rel"], d["id"], d["title"], d["kind"], d["date"]))
            else:
                plain_kit = f["sub"] == "kit" and not text.startswith("---")
                p = shapes.parse_file(text, None if plain_kit else f["area"])
                if plain_kit:
                    heading = re.search(r"(?m)^#[ \t]+(.+)$", text)
                    p["fm"]["title"] = heading.group(1).strip() if heading else f["path"].stem
                stats["errors"] += ["%s: %s" % (f["rel"], e) for e in p["errors"]]
                fm = p["fm"]
                hidden = f["area"] == "proposal" and config.excluded(cfg, str(fm.get("target") or ""))
                rows = [] if fresh or hidden else file_rows(f, p, f["tool"], text)
                if f["area"] in ("dict", "playbook"):
                    aliases[str(fm.get("title"))] = [str(a) for a in fm.get("aliases") or []]
                if f["area"] == "playbook":
                    playbooks.setdefault(f["tool"], []).append((f["path"].stem, fm.get("stance"), fm.get("situation"), fm.get("when_not")))
                if f["area"] == "proposal":
                    playbooks.setdefault("_pending", []).append((f["rel"], str(fm.get("target"))))
                extra = fm.get("date") or fm.get("by") or ", ".join(str(a) for a in fm.get("aliases") or []) or fm.get("stance") or ""
                entries.append((f["tool"], f["area"], f["rel"], f["path"].stem, row_title(fm, f["path"].stem),
                                fm.get("kind") or f["area"], str(extra)))
            if fresh:
                stats["chunks"] += counts.get(f["rel"], 0)
                continue
            stats["chunks"] += len(rows)
            stats["changed"] += 1
            writes.append((f["rel"], h, rows))
        gone = [r for r in known if r not in seen]
        drop = [r for r, _, _ in writes if r in known] + gone       # batch delete: one FTS scan instead of N
        for i in range(0, len(drop), 400):
            batch = drop[i:i + 400]
            con.execute("delete from fts where file in (%s)" % ",".join("?" * len(batch)), batch)
        now = time.time()
        for rel, h, rows in writes:
            if rows:
                con.executemany("insert into fts values (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            con.execute("insert or replace into files values (?,?,?)", (rel, h, now))
        for r in gone:
            con.execute("delete from files where rel=?", (r,))
        titles = {d["id"]: d["title"] for _, d, _ in docs.values()}
        for k, v in {"aliases": json.dumps(aliases, ensure_ascii=False), "titles": json.dumps(titles, ensure_ascii=False),
                     "built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "built_epoch": repr(time.time()), "walked": str(len(files)),
                     "version": __version__, "shape_version": str(SHAPE_VERSION), "index_rules": stamp}.items():
            con.execute("insert or replace into meta values (?,?)", (k, v))
        con.commit()
    finally:
        con.close()
    write_index_md(cfg, entries, stats)
    write_playbook_index(cfg, playbooks)
    mirror_skills(cfg)
    stats.update(files=len(seen), removed=len(gone), entries=len(entries), docs=len(docs))
    return stats


def stale(cfg):
    """Is the index older than the content? Cheap on purpose (D76): checks index_rules, mtime and walked count;
    no hashing, no tokenising. Absent or unreadable = stale. Returns "" when fresh, else how far behind (D83)."""
    if not cfg["index_path"].exists():
        return "no index"
    try:
        con = sqlite3.connect(cfg["index_path"], timeout=10)
        try:
            meta = dict(con.execute("select key, value from meta"))
        finally:
            con.close()
    except sqlite3.Error:
        return "index unreadable"
    if meta.get("index_rules") != rules_stamp(cfg):
        return "index rules or exclude globs changed since the index built %s" % meta.get("built_at", "?")
    built, walked = float(meta.get("built_epoch", 0)), int(meta.get("walked", -1))
    files = indexable(cfg)
    newer = sum(f["path"].stat().st_mtime > built for f in files)
    if not newer and len(files) == walked:
        return ""
    moved = "" if len(files) == walked else ", %d → %d files" % (walked, len(files))
    return "%d file(s) newer than the index built %s%s" % (newer, meta.get("built_at", "?"), moved)


def hashes_stale(cfg, expected):
    """Exact hash comparison for plug check: returns (built_at, is_stale, error_or_None)."""
    if not cfg["index_path"].exists():
        return None, True, None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % cfg["index_path"].as_posix(), uri=True, timeout=10)
        try:
            meta, indexed = dict(con.execute("select key, value from meta")), dict(con.execute("select rel, hash from files"))
        finally:
            con.close()
    except sqlite3.Error as e:
        return None, True, e
    bad = (meta.get("index_rules") != rules_stamp(cfg)
           or any(indexed.get(rel) != h for rel, h in expected.items())
           or any(rel not in expected for rel in indexed))
    return meta.get("built_at"), bad, None
