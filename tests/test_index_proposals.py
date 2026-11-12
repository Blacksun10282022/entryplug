# Verb index, pending proposals (D84): a refit request is indexed from its reasons only (为什么 · 最强反证), never
# from 改成什么 — that section carries the whole new target file (D03), so indexing it duplicated the target page
# or, when the target is excluded (D44), put an excluded page back into the index. A proposal whose target is
# excluded contributes no rows at all. The index records the rules it was built under and rebuilds once when
# they move, so rows written under the old rule do not survive an upgrade (the file hash alone never changes).
import sqlite3
from entryplug import config, index, search

PROPOSAL = """---
target: %s
base: 0000000
from: records/2026-08-21-counterpart-feigns-weakness.md
---
## 改成什么
整文件替换为：

```md
---
kind: concept
title: 势
---
## 定义
carriedonlyprobe 只在被携带的整页里出现。
```

## 为什么
whyonlyprobe 这是理由。

第二段理由，仍属为什么。

## 最强反证
counteronlyprobe 这是反证。
"""
EXCLUDE_YAML = '\nexclude:\n  - "self/facts/**"\n'


def rows(cfg, sql, *args):
    con = sqlite3.connect(cfg["index_path"])
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def write_pending(cfg, target, name="2026-09-01-probe.md"):
    p = cfg["proposals_dir"] / "pending" / name
    p.write_text(PROPOSAL % target, encoding="utf-8")
    return p


def hits(cfg, word, scope):
    return search.search(cfg, word, scope=scope, auto_index=False)["rows"]


def test_pending_proposal_is_indexed_from_its_reasons_only(repo):
    p = write_pending(repo, "tools/sunzi/dict/shi.md")
    index.build(repo)
    for scope in ("proposals", "all"):
        assert not hits(repo, "carriedonlyprobe", scope), "the carried file under 改成什么 must never be indexed"
    lines = p.read_text(encoding="utf-8").splitlines()
    for word in ("whyonlyprobe", "counteronlyprobe"):
        got = [h for h in hits(repo, word, "proposals") if h["file"].endswith("2026-09-01-probe.md")]
        assert got, word
        h = got[0]
        assert any(word in l for l in lines[h["lstart"] - 1:h["lend"]]), (word, h["lstart"], h["lend"])
        assert "carriedonlyprobe" not in h["excerpt"] and h["source"] == "tools/sunzi/dict/shi.md"
    spans = rows(repo, "select lstart, lend, excerpt from fts where file like '%2026-09-01-probe.md'")
    for a, b, _ in spans:                                             # no row reaches into 改成什么
        assert not any(l.startswith("```") or "carriedonlyprobe" in l for l in lines[a - 1:b]), (a, b)
    assert any("第二段理由" in e for _, _, e in spans), "both paragraphs of 为什么 are indexed"


def test_pending_proposal_for_an_excluded_target_yields_no_rows(repo):
    y = repo["root"] / "plug.yaml"
    y.write_text(y.read_text(encoding="utf-8") + EXCLUDE_YAML, encoding="utf-8")
    cfg = config.load(repo["root"])
    write_pending(cfg, "self/facts/example.md")
    index.build(cfg)
    assert rows(cfg, "select count(*) from fts where file like '%2026-09-01-probe.md'")[0][0] == 0
    assert not hits(cfg, "whyonlyprobe", "all")
    pend = (cfg["root"] / "index.md").read_text(encoding="utf-8")
    assert "2026-09-01-probe.md" in pend, "the pending list itself is unchanged"


def test_an_exclude_added_later_drops_an_unchanged_proposal(repo):
    """The proposal file does not move when plug.yaml gains an exclude glob, so its hash alone would keep its rows."""
    write_pending(repo, "self/facts/example.md")
    index.build(repo)
    assert hits(repo, "whyonlyprobe", "proposals")
    y = repo["root"] / "plug.yaml"
    y.write_text(y.read_text(encoding="utf-8") + EXCLUDE_YAML, encoding="utf-8")
    cfg = config.load(repo["root"])
    index.build(cfg)
    assert rows(cfg, "select count(*) from fts where file like '%2026-09-01-probe.md'")[0][0] == 0


def test_upgrade_drops_rows_written_under_the_old_rule(repo):
    """Simulate an index built before D84: the proposal is unchanged on disk (same hash), its old rows carried the
    whole 改成什么 block, and the meta has no rules key. A plain build — no full=True — must remove them, and must
    do it by re-indexing proposals only: a full rebuild of a real content repo outlives search's tool-call timeout
    (D76), so the first search after an upgrade would never finish. A sentinel row planted on an unrelated, unchanged
    page proves that page was not re-tokenised (re-indexing a file deletes all of its rows first)."""
    p = write_pending(repo, "tools/sunzi/dict/shi.md")
    index.build(repo)
    rel = p.relative_to(repo["root"]).as_posix()
    con = sqlite3.connect(repo["index_path"])
    con.execute("insert into fts values (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("carriedonlyprobe", p.stem, p.stem, "tools/sunzi/dict/shi.md", "", "proposal", "proposals", rel, 6, 30, "",
                 "carriedonlyprobe"))
    con.execute("insert into fts values (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("sentinelprobe", "shi", "shi", "势", "sunzi", "concept", "tools", "tools/sunzi/dict/shi.md", 1, 1, "", "s"))
    con.execute("delete from meta where key='index_rules'")
    con.commit(), con.close()
    assert hits(repo, "carriedonlyprobe", "all"), "the simulated old row is really there"
    s = index.build(repo)
    assert not hits(repo, "carriedonlyprobe", "all") and not hits(repo, "carriedonlyprobe", "proposals")
    assert hits(repo, "whyonlyprobe", "proposals")
    pending = len(list((repo["proposals_dir"] / "pending").glob("*.md")))
    assert s["changed"] == pending and s["removed"] == 0, (s["changed"], pending)   # proposals only, nothing else
    assert rows(repo, "select count(*) from fts where tokens match 'sentinelprobe'")[0][0] == 1, "shi.md was re-tokenised"
    stamp = dict(rows(repo, "select key, value from meta"))["index_rules"]
    assert stamp == index.rules_stamp(repo)
    again = index.build(repo)                                         # stamp now current: incremental again
    assert again["changed"] == 0
