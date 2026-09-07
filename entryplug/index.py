# What: `plug index` — walk the content repo → shape validation → chunking → tokens (jieba words + CJK bigrams)
#       → one FTS5 table; incremental by file hash; also writes the human-readable index.md, each equipment's
#       playbooks/INDEX.md, and mirrors SKILL.md into every pilot's skills directory.
# In:   cfg (config.load); full=True forces a complete rebuild.
# Out:  .kb/index.sqlite (table fts + bookkeeping tables files / meta) · index.md · tools/<t>/playbooks/INDEX.md
#       · <skills>/<t>/SKILL.md; returns a stats dict.
# Not:  no reranking, no LLM, no vectors; never edits content; an unchanged file is never tokenised again
#       (the hash is compared first and its chunk count read back from the table); corpus takes only the plain-text section
#       (the timestamped copy is a duplicate and stays out of the index); work/ and workshop/ are never indexed.
# Who:  cli (plug index) · search (rebuilds a stale index before answering, D76) · tests.
# Note: chunking is per paragraph (a cleaned transcript is one paragraph per line, carrying [m:ss]); a paragraph
#       over 800 chars is cut into 600/100 windows. Line numbers are 1-based so Read/sed can use them.
#       Row ids: entry = file stem; corpus = doc#seq (single-paragraph doc = doc#window); record / material /
#       proposal = file stem. When one doc id has both corpus/clean and corpus/raw only clean is indexed
#       (raw is the truth, clean is the view; check greps both when verifying anchor sentences).
# Deps: stdlib sqlite3 (FTS5) · jieba · PyYAML (via shapes).
import hashlib, json, re, sqlite3, time
import jieba
from . import __version__, SHAPE_VERSION, config, shapes
from .mirror import mirror_skills, model_invocation_disabled, write_openai_yaml  # noqa: F401  (moved out, D76 line budget)

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


def paragraphs(unit):
    """One unit(lstart, lend, pos, text) → paragraphs split on blank lines, line numbers exact."""
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
    """A paragraph <=800 chars is one chunk; longer ones are cut into 600/100 windows, line numbers by offset."""
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


def row_title(fm, stem):
    """The title a row carries. Split out so index.md can name an unchanged file without tokenising it again."""
    return str(fm.get("title") or fm.get("situation") or fm.get("name") or fm.get("target") or stem)


def file_rows(f, parsed, tool):
    """One content file → rows (tokens, id, doc, title, tool, kind, scope, file, lstart, lend, pos, excerpt)."""
    rel, area, fm, body = f["rel"], f["area"], parsed["fm"], parsed["body"]
    stem = f["path"].stem
    if f["sub"] == "kit":
        stem = "kit/" + rel.split("/kit/", 1)[1].rsplit(".", 1)[0]
    kind = {"dict": fm.get("kind", "concept"), "playbook": "playbook", "record": "record", "material": "material",
            "manual": "manual", "rules": "rule", "facts": "fact", "style": "style", "reading": "reading",
            "proposal": "proposal"}[area]
    title = row_title(fm, stem)
    prefix = " ".join([title] + [str(a) for a in fm.get("aliases") or []] + [str(fm.get("verdict") or "")])
    text = f["path"].read_text(encoding="utf-8")
    body_start = text[:len(text) - len(body)].count("\n") + 1 + (len(body) - len(body.lstrip("\n")))
    body_lines = body.strip("\n").split("\n")
    page = (body_start, body_start + len(body_lines) - 1, "", "\n".join(body_lines))   # one page, one chunk; cut only above 800 chars
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
    """Incremental build. Returns {files, chunks, changed, removed, entries, docs, errors}."""
    cfg["index_path"].parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(cfg["index_path"])
    for s in SCHEMA:
        con.execute(s)
    known = dict(con.execute("select rel, hash from files")) if not full else {}
    counts = dict(con.execute("select file, count(*) from fts group by file")) if known else {}   # one grouped scan: fts.file is unindexed, so `where file=?` scans the table
    if full:
        con.execute("delete from fts"), con.execute("delete from files")
    files = [f for f in config.walk(cfg) if f["area"] != "checks"]
    docs, seen, aliases, entries, playbooks, stats = {}, set(), {}, [], {}, {"changed": 0, "chunks": 0, "errors": []}
    for f in [x for x in files if x["area"] == "corpus"]:           # clean beats raw: one doc id keeps clean only
        d = shapes.parse_doc(f["path"].read_text(encoding="utf-8"), f["path"], f["sub"])
        if d["id"] not in docs or (f["sub"] == "clean" and docs[d["id"]][0]["sub"] == "raw"):
            docs[d["id"]] = (f, d)
    corpus_files = {id(v[0]) for v in docs.values()}
    for f in files:
        if f["area"] == "corpus" and id(f) not in corpus_files:
            continue
        text = f["path"].read_text(encoding="utf-8")
        seen.add(f["rel"])
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        fresh = known.get(f["rel"]) == h        # unchanged: its rows are already in the table, never tokenise twice
        if f["area"] == "corpus":
            d = docs[[k for k, v in docs.items() if v[0] is f][0]][1]
            rows = [] if fresh else doc_rows(f, d, f["tool"])
            entries.append((f["tool"], "corpus", f["rel"], d["id"], d["title"], d["kind"], d["date"]))
        elif f["area"] == "proposal" and f["sub"] != "pending":
            continue
        else:
            plain_kit = f["sub"] == "kit" and not text.startswith("---")
            p = shapes.parse_file(text, None if plain_kit else f["area"])
            if plain_kit:
                heading = re.search(r"(?m)^#[ \t]+(.+)$", text)
                p["fm"]["title"] = heading.group(1).strip() if heading else f["path"].stem
            stats["errors"] += ["%s: %s" % (f["rel"], e) for e in p["errors"]]
            rows = [] if fresh else file_rows(f, p, f["tool"])
            fm = p["fm"]
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
        con.execute("delete from fts where file=?", (f["rel"],))
        con.executemany("insert into fts values (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("insert or replace into files values (?,?,?)", (f["rel"], h, time.time()))
    gone = [r for r in known if r not in seen]
    for r in gone:
        con.execute("delete from fts where file=?", (r,)), con.execute("delete from files where rel=?", (r,))
    titles = {d["id"]: d["title"] for _, d in docs.values()}
    for k, v in {"aliases": json.dumps(aliases, ensure_ascii=False), "titles": json.dumps(titles, ensure_ascii=False),
                 "built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "built_epoch": repr(time.time()), "walked": str(len(files)),
                 "version": __version__, "shape_version": str(SHAPE_VERSION)}.items():
        con.execute("insert or replace into meta values (?,?)", (k, v))
    con.commit(), con.close()
    write_index_md(cfg, entries, stats)
    write_playbook_index(cfg, playbooks)
    mirror_skills(cfg)
    stats.update(files=len(seen), removed=len(gone), entries=len(entries), docs=len(docs))
    return stats


def stale(cfg):
    """Is the index older than the content? Cheap on purpose (D76): a content file modified after the last build,
    or a different number of walked files, means stale; no hashing, no tokenising. Absent or unreadable = stale."""
    if not cfg["index_path"].exists():
        return True
    try:
        con = sqlite3.connect(cfg["index_path"])
        meta = dict(con.execute("select key, value from meta"))
        con.close()
    except sqlite3.Error:
        return True
    built, walked = float(meta.get("built_epoch", 0)), int(meta.get("walked", -1))
    files = [f for f in config.walk(cfg) if f["area"] != "checks"]
    return len(files) != walked or any(f["path"].stat().st_mtime > built for f in files)


def write_index_md(cfg, entries, stats):
    """Human-readable index: one line per page. No build time in the header — the file is tracked by git and
    rebuilt by pre-commit on every commit, so a wall clock here left the working tree permanently dirty by one
    line that meant nothing (D64). Rebuilding now produces the same bytes unless the content actually changed.
    The build time lives in the index's own meta (`built_at`) and `plug check` prints it."""
    lines = ["# index · %d files · %d chunks · entryplug %s" % (len(entries), stats["chunks"], __version__)]
    for tool in [t["name"] for t in cfg["tools"]] + [None]:
        rows = [e for e in entries if e[0] == tool]
        if rows:
            lines.append("## %s" % (("tools/" + tool) if tool else "self · proposals"))
            lines += ["- %s · %s · %s · %s" % (e[2], e[4], e[5], e[6]) for e in rows]
    cfg["index_md_path"].write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_playbook_index(cfg, playbooks):
    """Playbook directory INDEX.md: id | stance | situation | when_not; pending proposals for new playbooks
    are listed at the end. Capped at 60 lines."""
    for t in cfg["tools"]:
        rows = playbooks.get(t["name"], [])
        if not (t["dir"] / "playbooks").is_dir():
            continue
        lines = ["# Playbook directory · %s · generated by plug index, do not hand-edit" % t["name"],
                 "A hit is not an obligation. If none fits, say so and analyse as usual.", "",
                 "| id | stance | situation | when_not |", "|---|---|---|---|"]
        lines += ["| %s | %s | %s | %s |" % r for r in rows]
        new = [(rel, tg) for rel, tg in playbooks.get("_pending", []) if "/playbooks/" in tg and not (cfg["root"] / tg).exists()]
        if new:
            lines += ["", "## Pending proposals for a missing playbook"] + ["- %s → %s" % x for x in new]
        (t["dir"] / "playbooks" / "INDEX.md").write_text("\n".join(lines[:60]) + "\n", encoding="utf-8", newline="\n")
