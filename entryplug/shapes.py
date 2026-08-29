# 做什么：形状 v1 的字段表与逐文件校验——内容条目 entry（词典 / 打法）· 记录 record（驾驶日志）· 提议 proposal（改装申请）
#         · 资料 material · 说明书 manual · 规则文件 RULES.md · 教材 doc；外加观察行 / 规则行 / [[链接]] / 小节的解析。
# 输入：一个文件的文本（frontmatter + 正文）和它的区域名（config.walk 给的 area）。
# 输出：结构化 dict（fm · body · errors · obs · links · sections）；parse_rules / parse_doc 给出规则与教材的结构。
# 不做什么：不跨文件（[[链接]] 解析、锚句核对、R-id 存在性在 check）；不读教材目录；不写任何文件。
# 谁调用：index（校验 + 摘要字段）· check（清单）· apply（提议解析）· numbers（记录字段）。
# 观察行语法：`- [?]? 陈述 [[链接]]* ^pNNNN (src: doc-id#seq "锚句")`；综合行 `(src: ^p1 ^p2)`；无原句 `(src: doc p.12 [未锚])`。
# 规则行语法：`- R12 · 陈述 [YYYY-MM · 来源]`；小节标题或行内的 `到期 YYYY-MM-DD` / `复核 YYYY-MM` 机器会读。
# 形状只加可选字段不改必填字段（§6.6）；三种形状的未知键是 ERROR，其余形状宽松。
# 依赖：stdlib + PyYAML。
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
RE_RULE = re.compile(r"^\s*[-*]\s*([A-Z]{1,2}\d{1,3})\s*[·・:：]\s*(.*)$")
RE_DATE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
RE_HEAD = re.compile(r"^(?:[A-Za-z_]+|标题|来源|日期|主讲)\s*[:：]\s*(.*)$")
SEP = re.compile(r"^={3,}(?:\s*(.*?)\s*={3,})?\s*$")
RE_PARA = re.compile(r"^\[(\d+:\d{2}(?::\d{2})?|¶\d+)\]\s*(.*)$")
HEAD_KEYS = {"标题": "title", "日期": "date", "bvid": "id", "主讲": "speaker"}


def split_frontmatter(text):
    """--- yaml --- 正文。返回 (fm|None, body, error|None)。fm 必须是映射。"""
    if not text.startswith("---"):
        return None, text, None
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return None, text, "frontmatter 没有闭合的 ---"
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        return None, text[m.end():], "frontmatter 不是合法 YAML：" + str(e).splitlines()[0]
    if not isinstance(fm, dict):
        return None, text[m.end():], "frontmatter 不是映射"
    return fm, text[m.end():], None


def sections(body):
    """## 小节 → 文本（保留顺序）。'' 键是首个小节前的正文。"""
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
    """## 观察 下的 `- ` 行。每条：text · unreviewed · anchor · src · refs · doc · seq · quote · unanchored · missing_src。"""
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
    """按字段表校验一个文件，返回 ERROR 文案列表（空 = 合形状）。"""
    spec = SHAPES.get(shape)
    if spec is None:
        return []
    if fm is None:
        return ["缺 frontmatter"]
    errs = ["缺必填字段 " + k for k in spec["required"] if fm.get(k) in (None, "", [])]
    if shape in ("entry", "record", "proposal"):
        allowed = set(spec["required"]) | set(spec["optional"])
        errs += ["未知字段 %s（形状 v1 不认识）" % k for k in fm if k not in allowed]
    if shape == "entry":
        kind = fm.get("kind")
        if kind not in spec["kinds"]:
            errs.append("kind 必须是 %s，现在是 %r" % ("/".join(spec["kinds"]), kind))
        if kind == "concept" and not fm.get("aliases"):
            errs.append("concept 至少一个 alias")
        if kind == "playbook":
            errs += ["playbook 缺 " + k for k in spec["playbook"] if not fm.get(k)]
        if "aliases" in fm and not isinstance(fm["aliases"], list):
            errs.append("aliases 必须是列表")
    if "headings" in spec:
        have = sections(body)
        errs += ["正文缺小节 ## " + h for h in spec["headings"] if h not in have]
    if shape == "material" and fm.get("date") is not None and not RE_DATE.match(str(fm["date"])):
        errs.append("date 必须是 YYYY-MM-DD")
    return errs


def parse_file(text, area):
    """一次把文件读成结构：shape · fm · body · errors · sections · links · obs。"""
    shape = AREA_SHAPE.get(area)
    fm, body, err = split_frontmatter(text)
    errors = [err] if err else []
    if shape:
        errors += validate(shape, fm, body)
    return {"shape": shape, "fm": fm or {}, "body": body, "errors": errors, "sections": sections(body),
            "links": links(body), "obs": parse_observations(body) if shape == "entry" else []}


def parse_rules(text):
    """RULES.md → header{model, reviewed} · sections[{name, expires, review, lines[{id, text, dated, review}]}] · ids。"""
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
    """教材文件 → doc：id · title · date · kind · speaker · series · units[(lstart, lend, pos, text)] · text。
    三种来源：frontmatter 文本；讲座（头部 Title/BVID/Date + ==== 纯文本 ====，只取纯文本段）；清洗稿（6 行头 + ==== + [m:ss]/[¶n] 段落）。"""
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
