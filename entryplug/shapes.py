# What: shape v1 — the field table and per-file validation for entry (dict / playbook) · record (flight log) ·
#       proposal (refit request) · material · manual · the RULES.md rule file · corpus doc; plus parsing of
#       observation lines, rule lines, [[links]] and ## sections.
# In:   one file's text (frontmatter + body) and its area name (from config.walk).
# Out:  a structured dict (fm · body · errors · obs · links · sections); parse_rules / parse_doc for rules and corpus.
# Not:  never crosses files ([[link]] resolution, anchor-sentence checks and R-id existence live in check);
#       never reads the corpus directory; never writes anything.
# Who:  index (validation + summary fields) · check (findings) · apply (proposal parsing) · numbers (record fields).
# Note: section headings and markers below are shape v1 on-disk vocabulary, not prose — they stay as written.
#       Observation line: `- [?]? statement [[link]]* ^pNNNN (src: doc-id#seq "anchor sentence")`;
#       synthesis line `(src: ^p1 ^p2)`; no original sentence `(src: doc p.12 [未锚])`.
#       Rule line: `- R12 · statement [YYYY-MM · source]`; `到期 YYYY-MM-DD` / `复核 YYYY-MM` are read by the machine.
#       Shape v1 only gains optional fields (§6.6); unknown keys are an ERROR in the three strict shapes.
# Deps: stdlib + PyYAML.
import re
import yaml

SHAPES = {
    "entry": {"required": ["kind", "title"], "optional": ["aliases", "legacy_id", "origin", "situation", "when_not", "stance"],
              "kinds": ("concept", "method", "playbook"), "playbook": ["situation", "when_not", "stance"]},
    "record": {"required": ["tool", "by", "situation", "verdict"], "optional": ["chosen", "outcome"],
               "headings": ["依据", "最强反证", "什么会改判"]},
    "proposal": {"required": ["target", "base", "from"], "optional": [], "headings": ["改成什么", "为什么", "最强反证"]},
    "material": {"required": ["date"], "optional": ["kind", "title", "source", "expires"]},
    "manual": {"required": ["name", "description"], "optional": ["when_to_use", "disable-model-invocation", "user-invocable"]},
}
AREA_SHAPE = {"dict": "entry", "playbook": "entry", "record": "record", "proposal": "proposal",
              "material": "material", "manual": "manual"}
RE_SRC = re.compile(r"\(src:\s*(.*?)\)\s*$")
RE_ANCHOR = re.compile(r"\^p\d+")
RE_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
RULE_ID = r"[A-Z]{1,2}\d{1,3}[a-z]?"        # B1 · J12 · P2a — a lowercase suffix is part of the id
RE_RULE = re.compile(r"^\s*[-*]\s*(%s)\s*[·・:：]\s*(.*)$" % RULE_ID)
RE_DATE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
RE_HEAD = re.compile(r"^(?:[A-Za-z_]+|标题|来源|日期|主讲)\s*[:：]\s*(.*)$")
SEP = re.compile(r"^={3,}(?:\s*(.*?)\s*={3,})?\s*$")
RE_PARA = re.compile(r"^\[(\d+:\d{2}(?::\d{2})?|¶\d+)\]\s*(.*)$")
HEAD_KEYS = {"标题": "title", "日期": "date", "bvid": "id", "主讲": "speaker"}


def split_frontmatter(text):
    """--- yaml --- body. Returns (fm|None, body, error|None). fm must be a mapping."""
    if not text.startswith("---"):
        return None, text, None
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return None, text, "frontmatter has no closing ---"
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        return None, text[m.end():], "frontmatter is not valid YAML: " + str(e).splitlines()[0]
    if not isinstance(fm, dict):
        return None, text[m.end():], "frontmatter is not a mapping"
    return fm, text[m.end():], None


def sections(body):
    """## heading → text, in order. The '' key holds whatever precedes the first heading."""
    out, cur, fence = {"": []}, "", False
    for line in body.splitlines():
        fence ^= line.startswith("```")
        m = None if fence else re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1).strip()
            out.setdefault(cur, [])
        else:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def links(body):
    return [m.group(1).strip() for m in RE_LINK.finditer(body)]


def parse_observations(body):
    """`- ` lines under `## 观察`. Each: text · unreviewed · anchor · src · refs · doc · seq · quote · unanchored · missing_src."""
    out, in_obs = [], False
    for n, line in enumerate(body.splitlines(), 1):
        if line.startswith("## "):
            in_obs = line[3:].strip().startswith("观察")
            continue
        if not in_obs or not re.match(r"^\s*-\s+", line):
            continue
        item = {"line": n, "text": line.strip()[2:].strip(), "unreviewed": False, "anchor": None, "src": None,
                "refs": [], "doc": None, "seq": None, "quote": None, "unanchored": False, "missing_src": False}
        if item["text"].startswith("[?]"):
            item["unreviewed"] = True
            item["text"] = item["text"][3:].strip()
        m = RE_SRC.search(item["text"])
        if not m:
            item["missing_src"] = True
        else:
            src, head = m.group(1).strip(), item["text"][:m.start()]
            item["src"] = src
            a = RE_ANCHOR.findall(head)
            item["anchor"] = a[-1] if a else None
            item["refs"] = RE_ANCHOR.findall(src)
            item["unanchored"] = "[未锚]" in src
            q = re.search(r'"([^"]+)"|「([^」]+)」', src)
            item["quote"] = (q.group(1) or q.group(2)).strip() if q else None
            rest = RE_ANCHOR.sub(" ", src)
            d = re.search(r"([A-Za-z0-9][\w\-\.]*)(?:#([\w\-:\.]+))?", rest)
            if d:
                item["doc"], item["seq"] = d.group(1), d.group(2)
        out.append(item)
    return out


def validate(shape, fm, body):
    """Validate one file against the field table; returns a list of ERROR texts (empty = in shape)."""
    spec = SHAPES.get(shape)
    if spec is None:
        return []
    if fm is None:
        return ["no frontmatter"]
    errs = ["missing required field " + k for k in spec["required"] if fm.get(k) in (None, "", [])]
    if shape in ("entry", "record", "proposal"):
        allowed = set(spec["required"]) | set(spec["optional"])
        errs += ["unknown field %s (shape v1 does not know it)" % k for k in fm if k not in allowed]
    if shape == "entry":
        kind = fm.get("kind")
        if kind not in spec["kinds"]:
            errs.append("kind must be one of %s, got %r" % ("/".join(spec["kinds"]), kind))
        if kind == "concept" and not fm.get("aliases"):
            errs.append("a concept needs at least one alias")
        if kind == "playbook":
            errs += ["playbook is missing " + k for k in spec["playbook"] if not fm.get(k)]
        if "aliases" in fm and not isinstance(fm["aliases"], list):
            errs.append("aliases must be a list")
    if "headings" in spec:
        have = sections(body)
        errs += ["body is missing section ## " + h for h in spec["headings"] if h not in have]
    if shape == "material" and fm.get("date") is not None and not RE_DATE.match(str(fm["date"])):
        errs.append("date must be YYYY-MM-DD")
    return errs


def parse_file(text, area):
    """Read a file into one structure: shape · fm · body · errors · sections · links · obs."""
    shape = AREA_SHAPE.get(area)
    fm, body, err = split_frontmatter(text)
    errors = [err] if err else []
    if shape:
        errors += validate(shape, fm, body)
    return {"shape": shape, "fm": fm or {}, "body": body, "errors": errors, "sections": sections(body),
            "links": links(body), "obs": parse_observations(body) if shape == "entry" else []}


def rule_refs(text, ids):
    """Rule ids named in text, restricted to the prefixes that actually occur in RULES.md. One definition, used by
    check (does the id exist?) and numbers (is the reference real?), so the two can never drift apart. The
    lowercase suffix is part of the id: without it P2a matched nothing at all — the reference was not misjudged,
    it was invisible, because the trailing letter broke the word-boundary lookahead."""
    if not ids:
        return []
    pre = "|".join(sorted({re.match(r"[A-Z]+", i).group(0) for i in ids}))
    return re.findall(r"(?<![A-Za-z0-9])((?:%s)\d{1,3}[a-z]?)(?![A-Za-z0-9])" % pre, text)


def parse_rules(text):
    """RULES.md → header{model, reviewed} · sections[{name, expires, review, lines[{id, text, dated, review}]}] · ids."""
    header, secs, cur = {}, [], None
    for line in text.splitlines():
        if not line.startswith("#"):
            for k, v in re.findall(r"(model|reviewed)\s*[:：]\s*(\S+)", line):
                header.setdefault(k, v)
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            name = h.group(1)
            e = re.search(r"到期\s*(\d{4}-\d{2}-\d{2})", name)
            r = re.search(r"复核\s*(\d{4}-\d{2})", name)
            cur = {"name": name, "expires": e.group(1) if e else None, "review": r.group(1) if r else None, "lines": []}
            secs.append(cur)
            continue
        m = RE_RULE.match(line)
        if m and cur is not None:
            r = re.search(r"复核\s*(\d{4}-\d{2})", m.group(2))
            cur["lines"].append({"id": m.group(1), "text": m.group(2).strip(), "dated": bool(RE_DATE.search(m.group(2))),
                                 "review": r.group(1) if r else None})
    ids = {l["id"] for s in secs for l in s["lines"]}
    return {"header": header, "sections": secs, "ids": ids, "retired": any("退役" in s["name"] for s in secs)}


def parse_doc(text, path, sub=None):
    """Corpus file → doc: id · title · date · kind · speaker · series · units[(lstart, lend, pos, text)] · text.
    Three sources: frontmatter text; a lecture (Title/BVID/Date header + ==== plain text ====, only that section);
    a cleaned transcript (6-line header + ==== + [m:ss] / [¶n] paragraphs)."""
    fm, body, _ = split_frontmatter(text)
    lines = text.splitlines()
    meta, units = {}, []
    sep = [i for i, l in enumerate(lines) if SEP.match(l)]
    if fm:
        meta = {k: fm.get(k) for k in ("id", "title", "date", "kind", "speaker", "series")}
        fm_lines = text[:len(text) - len(body)].count("\n")
        units = [(fm_lines + 1, len(lines), "", "\n".join(lines[fm_lines:]))]
    elif sep:
        for l in lines[:sep[0]]:
            m = RE_HEAD.match(l)
            if m:
                key = re.split(r"[:：]", l, 1)[0].strip().lower()
                meta[HEAD_KEYS.get(key, key)] = m.group(1).strip()
        labels = [SEP.match(lines[i]).group(1) or "" for i in sep]
        start = next((sep[i] for i, lab in enumerate(labels) if "纯文本" in lab), sep[0])
        end = next((s for s in sep if s > start), len(lines))
        for i in range(start + 1, end):
            m = RE_PARA.match(lines[i])
            if m and m.group(2).strip():
                units.append((i + 1, i + 1, m.group(1), m.group(2).strip()))
        if not units and "".join(lines[start + 1:end]).strip():
            units = [(start + 2, end, "", "\n".join(lines[start + 1:end]))]
        meta["kind"] = meta.get("kind") or ("lecture" if meta.get("id") or (units and units[0][2]) else "text")
    else:
        units = [(1, len(lines), "", "\n".join(lines))]
    title = str(meta.get("title") or (lines[0].lstrip("# ").strip() if lines else path.stem))
    doc_id = str(meta.get("id") or path.stem)
    sm = re.match(r"^(.+?)\s*[｜|·—\-：:]\s*.+$", title)
    return {"id": doc_id, "title": title, "date": str(meta.get("date") or ""), "kind": meta.get("kind") or "text",
            "speaker": meta.get("speaker"), "series": sm.group(1) if sm else "", "sub": sub,
            "units": units, "text": "\n".join(u[3] for u in units)}
