# What: `plug check` — the findings list (ERROR / WARNING, one line each with the time it was verified, never
#       aggregated into a score) + the header self-check (shape version · index freshness · when each hook last
#       fired · mounted equipment · .plug-off) + each equipment's own checks/ + moving refit requests left
#       unapproved for 30 days to rejected/ + one page of report and the sync rate. Code list: README, docs/.
# In:   cfg; expire=False leaves proposals alone (pre-commit uses that); today can be injected (tests).
# Out:  run() → dict{errors, warnings, header, moved, records, proposals, materials, entries, orphans, numbers}.
# Not:  never edits content (its only writes are an expired proposal and the numbers page); no score; no LLM.
# Who:  cli (plug check) · gates/precommit (0 ERROR to pass) · apply (before and after landing) · status · tests.
# Deps: stdlib (subprocess only to ask git) · shapes · config · numbers · trust (runs the equipment checks).
import hashlib, os, re, sqlite3, subprocess, sys, time
from datetime import date
from . import __version__, SHAPE_VERSION, config, shapes, trust

HOOKS = ("precommit", "outbound", "precompact", "stop")
VERBS = ("index", "check", "apply", "eval", "search", "status", "init", "mcp", "hash")
PATHISH = re.compile(r"(?<![\w/`.])((?:self|tools|proposals|playbooks|dict|corpus|materials|records|checks)/[\w\-./]*\w)")
OTHER_PARTY = re.compile(r"^\s*[-*]\s*(让|叫|要求|告诉|向|逼|劝)对方")
MAP_LIE = re.compile(r"(?i)sortie lock.{0,200}(only records|cannot veto|records, not a lock|obligation, not a fence)")
DESC_ONE, DESC_TOTAL, EXPIRE_DAYS, HOOK_DAYS, NEW_DAYS = 1536, 4000, 30, 30, 30


def git_added(root):
    """{rel: date first committed}; {} when this is not a git repo."""
    try:
        out = subprocess.run(["git", "-c", "core.quotePath=false", "log", "--diff-filter=A", "--format=@%cs", "--name-only"], cwd=str(root),
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
    """File age: date prefix in the filename → date in the `by` field → date first committed → mtime."""
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
    header = {"at": at, "machine": __version__, "machine_pin": cfg["machine_pin"], "shape_version": cfg.get("shape_version"), "shape_ok": shape_ok,
              "tools": [t["name"] for t in cfg["tools"]], "hooks": {}, "index_built": None, "index_stale": None, "plug_off": config.plug_off(cfg)}
    out = {"errors": E, "warnings": W, "header": header, "moved": moved, "records": [], "proposals": [], "materials": [],
           "entries": {}, "orphans": [], "numbers": "", "rules": None}
    if not shape_ok:
        err("shape_version", "plug.yaml", "shape version %r is unknown to this machine (v%d) — refusing to run" % (cfg.get("shape_version"), SHAPE_VERSION))
        return out
    if not machine_ok:
        warn("machine_pin", "plug.yaml", "pinned machine version %r != installed %s" % (cfg["machine_pin"], __version__))
    for t in [x for x in cfg["tools"] if not x["dir"].is_dir()]:
        err("tool_path", "plug.yaml", "mounted equipment directory does not exist: %s" % t["path"])
    for c in [x for x in cfg["corpus"] if not (root / str(x["path"])).is_dir()]:
        warn("corpus_path", "plug.yaml", "declared corpus directory does not exist: %s" % c["path"])
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
            docs.setdefault(d["title"], []).append(d["text"])
            continue
        if f["area"] == "rules":
            rules = shapes.parse_rules(text)
            rules["text"] = text
            continue
        if f["area"] in ("style", "facts", "reading"):
            continue
        p = shapes.parse_file(text, None if f["sub"] == "kit" and not text.startswith("---") else f["area"])
        p.update(f, age=age_days(f, p["fm"], added, today), text=text)
        for e in p["errors"]:
            err("shape", f["rel"], e)
        {"dict": entries, "playbook": entries}.get(f["area"], {}).__setitem__(f["rel"], p) if f["area"] in ("dict", "playbook") else \
            {"record": records, "proposal": proposals, "material": materials, "manual": manuals}[f["area"]].append(p)
    out.update(records=records, proposals=proposals, materials=materials, entries=entries, rules=rules)
    # —— entries: titles / aliases · links · observation lines ——
    names, anchors, inbound = {}, set(), {rel: 0 for rel, p in entries.items() if p["area"] == "dict"}
    for rel, p in entries.items():
        for nm in [p["fm"].get("title")] + list(p["fm"].get("aliases") or []):
            key = (p["tool"], str(nm))
            if key in names and names[key] != rel:
                warn("collision", rel, "title / alias %r collides with %s" % (nm, names[key]))
            names.setdefault(key, rel)
        anchors |= {o["anchor"] for o in p["obs"] if o["anchor"]}
    for rel, p in entries.items():
        tool, fm = p["tool"], p["fm"]
        for link in p["links"]:
            t2, _, name = link.rpartition("/")
            t2 = t2 or tool
            if t2 != tool and t2 not in tool_of.get(tool, {}).get("depends", []):
                err("cross_tool", rel, "[[%s]] points at equipment %s, which is not a declared dependency" % (link, t2))
            elif (t2, name) not in names:
                err("link", rel, "[[%s]] resolves to no title or alias" % link)
            elif names[(t2, name)] != rel and names[(t2, name)] in inbound:
                inbound[names[(t2, name)]] += 1
        for o in p["obs"]:
            where = "%s:%d" % (rel, o["line"])
            if o["missing_src"]:
                err("obs_src", where, "observation line has no (src: …)")
                continue
            for ref in o["refs"]:
                if ref not in anchors:
                    err("pid", where, "%s does not resolve (no such anchor)" % ref)
            if o["quote"] is not None and o["doc"]:
                if o["doc"] not in docs:
                    err("anchor", where, "the corpus has no doc %r" % o["doc"])
                elif not quote_in(docs, o["doc"], o["quote"]):
                    err("anchor", where, "anchor sentence not found in %s: %r" % (o["doc"], o["quote"][:30]))
            elif not o["refs"] and not o["unanchored"]:
                err("obs_src", where, "src carries neither an anchor sentence nor a ^p reference (mark [未锚] when there is no original)")
        if len(p["body"]) > 4000 or len(p["obs"]) > 25:
            warn("long", rel, "page too long (%d chars · %d observation lines)" % (len(p["body"]), len(p["obs"])))
        if fm.get("kind") == "concept" and len(fm.get("aliases") or []) < 2:
            warn("aliases", rel, "concept has fewer than 2 aliases")
        if fm.get("stance") in ("warning", "diagnostic"):
            for sec in ("动作", "练习"):
                for line in p["sections"].get(sec, "").splitlines():
                    if OTHER_PARTY.match(line):
                        warn("warning_action", rel, "a stance=%s playbook gives an action aimed at the other party: %s" % (fm["stance"], line.strip()[:40]))
    for rel in inbound:
        if inbound[rel] < 3 and entries[rel]["age"] <= NEW_DAYS:
            warn("inbound", rel, "new entry has %d inbound links (<3)" % inbound[rel])
    out["orphans"] = sorted(rel for rel, n in inbound.items() if n == 0)
    for t in cfg["tools"]:
        if t.get("unreviewed") is not None:
            n = sum(o["unreviewed"] for rel, p in entries.items() if p["tool"] == t["name"] for o in p["obs"])
            if n != t["unreviewed"]:
                warn("unreviewed", t["path"], "[?] line count %d does not match the declared %d" % (n, t["unreviewed"]))
    # —— rules · records · proposals · materials · manuals ——
    ids = rules["ids"] if rules else set()
    if rules:
        for k in ("model", "reviewed"):
            if not rules["header"].get(k):
                warn("rules_header", "self/RULES.md", "file header is missing %s:" % k)
        for s in rules["sections"]:
            if s["expires"] and s["expires"] < today.isoformat():
                warn("rules_expired", "self/RULES.md", "section %r has expired; the whole section is void and must be rewritten" % s["name"])
            for l in s["lines"]:
                if not l["dated"] and "退役" not in s["name"]:
                    warn("rule_date", "self/RULES.md", "%s carries no date" % l["id"])
                for rv in filter(None, (l["review"], s["review"])):
                    if rv < today.strftime("%Y-%m"):
                        warn("rules_review", "self/RULES.md", "%s was due for review in %s" % (l["id"], rv))
    for r in records:
        for rid in shapes.rule_refs(r["sections"].get("依据", ""), ids):
            if rid not in ids:
                err("rid", r["rel"], "%s is named in 依据 but does not exist in RULES.md" % rid)
            elif rid in rules["retired_ids"]:
                warn("rid_retired", r["rel"], "%s is named in 依据 but is retired in RULES.md" % rid)
        if not r["fm"].get("outcome") and r["age"] >= 30:
            warn("outcome", r["rel"], "record has had no outcome for %d days" % r["age"])
    seen_p = {}
    for p in [x for x in proposals if x["sub"] == "pending"]:
        key = (str(p["fm"].get("target")), str(p["fm"].get("from")))
        if key in seen_p:
            warn("dup", p["rel"], "duplicate proposal (same target + same from): %s" % seen_p[key])
        seen_p.setdefault(key, p["rel"])
        if "plug apply" not in p["text"]:
            warn("footer", p["rel"], "no footer with the two copy-paste lines (approve / --reject); the owner cannot act on it from the chat")
        if expire and p["age"] > EXPIRE_DAYS:
            dst = cfg["proposals_dir"] / "rejected" / p["path"].name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(p["text"].rstrip("\n") + "\n\nrejected: %s · expired (%d days unapproved, moved here by plug check)\n" % (today, p["age"]), encoding="utf-8", newline="\n")
            p["path"].unlink()
            moved.append(p["rel"])
    for m in materials:
        ttl = tool_of.get(m["tool"], {}).get("ttl_days", {})
        days = ttl.get(str(m["fm"].get("kind")), ttl.get("default", 90))
        if m["age"] > days:
            warn("expired", m["rel"], "material is past its shelf life (%s: %d days > %d)" % (m["fm"].get("kind"), m["age"], days))
            m["expired"] = True
    descs = [(m, str(m["fm"].get("description") or "") + str(m["fm"].get("when_to_use") or "")) for m in manuals]
    for m, d in [x for x in descs if len(x[1]) > DESC_ONE]:
        warn("desc", m["rel"], "description is %d chars > %d; it will be truncated in the skill list" % (len(d), DESC_ONE))
    if sum(len(d) for _, d in descs) > DESC_TOTAL:
        warn("desc", "tools", "manual descriptions total %d chars > the %d list budget" % (sum(len(d) for _, d in descs), DESC_TOTAL))
    # —— paths and commands · the map's claims · index.md · hooks · index freshness · equipment checks ——
    maps = [(n, (root / n).read_text(encoding="utf-8"), root) for n in ("CLAUDE.md", "AGENTS.md") if (root / n).exists()]
    for m in [x for x in [config.codex_trust(cfg)] if x]:
        warn("codex_trust", ".codex/hooks.json", m)
    for rel, x, _ in [m for m in maps if MAP_LIE.search(m[1])]:
        warn("map_claim", rel, "this map says the sortie lock only records / cannot veto — it does block, on both pilots (D56). A pilot told nothing stops it will act as if nothing does. Replace that line from pilots/")
    for rel, text, base in ([("self/RULES.md", rules["text"], root)] if rules else []) + \
            [(m["rel"], m["text"], m["path"].parent) for m in manuals] + maps:
        for tok in set(PATHISH.findall(text)):
            if "<" not in tok and not any((b / tok).exists() for b in (root, base, cfg["self_dir"])):
                warn("path", rel, "path resolves to nothing that exists: %s" % tok)
        for verb in set(re.findall(r"(?:`|!\s|^\s*)plug\s+([a-z][\w-]*)", text, re.M)) - set(VERBS):   # a command, not the prose "the plug is out"
            warn("path", rel, "there is no command plug %s" % verb)
    md = cfg["index_md_path"]
    if not md.exists():
        warn("index_md", cfg["index_md"], "index.md does not exist (run plug index)")
    else:
        lines = md.read_text(encoding="utf-8")
        missing = [rel for rel in entries if rel not in lines]
        if missing:
            warn("index_md", cfg["index_md"], "index.md is incomplete, %d pages missing (e.g. %s)" % (len(missing), missing[0]))
        if len(lines) > 200_000:
            warn("index_md", cfg["index_md"], "index.md is oversized (%d chars)" % len(lines))
    for h in HOOKS:
        header["hooks"][h] = last = (cfg["hooks_dir"] / h).read_text(encoding="utf-8").strip() if (cfg["hooks_dir"] / h).exists() else None
        if not last or (today - date.fromisoformat(last[:10])).days > HOOK_DAYS:
            warn("hook", ".kb/hooks/" + h, "hook %s %s" % (h, "has never fired" if not last else "last fired %s, over %d days ago" % (last, HOOK_DAYS)))
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
        warn("index_stale", cfg["index"], "the index is older than the content (or absent); run plug index")
    if tool_checks:
        trust.run_checks(cfg, warn, err)             # only scripts git tracks unchanged (D70)
    from . import numbers
    out["numbers"] = numbers.page(cfg, records, today, docs, anchors, ids)
    cfg["numbers_path"].parent.mkdir(parents=True, exist_ok=True)
    cfg["numbers_path"].write_text(out["numbers"], encoding="utf-8", newline="\n")
    return out
