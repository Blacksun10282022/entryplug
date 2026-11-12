# What: shape v1 observation lines — the `- ` lines under an entry's `## 观察` section, each read into its parts.
# In:   one entry's body text (frontmatter already split off by shapes.split_frontmatter).
# Out:  parse_observations() → a list of dicts, one per line: text · unreviewed · anchor · src · refs · doc · seq ·
#       quote · unanchored · missing_src, with the line number inside the body.
# Not:  never resolves anything (^p anchors, docs and anchor sentences are checked across files in check); never
#       reads the corpus; never writes anything.
# Who:  shapes.parse_file (the only caller; moved here unchanged from shapes.py to keep that file within 250 lines).
# Note: the line form is shape v1 on-disk vocabulary: `- [?]? statement [[link]]* ^pNNNN (src: doc-id#seq "anchor
#       sentence")`; synthesis `(src: ^p1 ^p2)`; no original sentence `(src: doc p.12 [未锚])`.
# Deps: stdlib re.
import re

RE_SRC = re.compile(r"\(src:\s*(.*?)\)\s*$")
RE_ANCHOR = re.compile(r"\^p\d+")


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
