# Verb index: one FTS5 table, incremental by hash, only the plain-text section, clean beats raw,
# index.md / INDEX.md / the manual mirror.
import sqlite3
from entryplug import index
from conftest import plug


def rows(cfg, sql, *args):
    con = sqlite3.connect(cfg["index_path"])
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def test_build_is_one_fts_table_and_incremental(repo):
    names = {r[0] for r in rows(repo, "select name from sqlite_master where type='table' and name not like 'fts_%'")}
    assert names == {"fts", "files", "meta"}
    n = rows(repo, "select count(*) from fts")[0][0]
    assert n > 100
    again = index.build(repo)
    assert again["changed"] == 0 and again["removed"] == 0 and again["chunks"] == n
    p = repo["root"] / "tools/sunzi/dict/shi.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n新加一行。\n", encoding="utf-8")
    assert index.build(repo)["changed"] == 1
    p.unlink()
    s = index.build(repo)
    assert s["removed"] == 1 and rows(repo, "select count(*) from fts where id='shi'")[0][0] == 0


def test_corpus_plain_section_only_and_clean_preferred(repo):
    files = {r[0] for r in rows(repo, "select distinct file from fts where doc='BV1EXAMPLE01'")}
    assert files == {"tools/sunzi/corpus/clean/talk-2026-08-01-shi.md"}
    assert rows(repo, "select count(*) from fts where excerpt like '%->%'")[0][0] == 0
    pos = {r[0] for r in rows(repo, "select pos from fts where doc='BV1EXAMPLE01'")}
    assert "5:30" in pos
    ids = {r[0] for r in rows(repo, "select id from fts where doc='sunzi-05-bingshi'")}
    assert "sunzi-05-bingshi#6" in ids and len(ids) == 6
    lines = rows(repo, "select lstart, lend from fts where id='sunzi-05-bingshi#6'")[0]
    text = (repo["root"] / "tools/sunzi/corpus/raw/sunzi-05-bingshi.md").read_text(encoding="utf-8").splitlines()
    assert "求之于势" in text[lines[0] - 1]


def test_scopes_kinds_and_pages(repo):
    kinds = {r[0] for r in rows(repo, "select distinct kind from fts where scope='tools'")}
    assert {"concept", "method", "playbook", "record", "material", "manual", "rule"} <= kinds and "proposal" not in kinds
    assert rows(repo, "select count(distinct file) from fts where scope='proposals'")[0][0] == 1
    assert rows(repo, "select count(*) from fts where id='shi'")[0][0] == 1        # 一页一块
    lstart = rows(repo, "select lstart from fts where id='shi'")[0][0]
    assert (repo["root"] / "tools/sunzi/dict/shi.md").read_text(encoding="utf-8").splitlines()[lstart - 1].startswith("## 定义")


def test_generated_files(repo):
    root = repo["root"]
    md = (root / "index.md").read_text(encoding="utf-8")
    assert md.startswith("# index") and "tools/sunzi/dict/shi.md · 势 · concept · 势能, 态势" in md
    idx = (root / "tools/sunzi/playbooks/INDEX.md").read_text(encoding="utf-8").splitlines()
    assert idx[1].startswith("A hit is not an obligation") and sum(l.startswith("| opponent") for l in idx) == 2 and len(idx) <= 60
    for d in (".claude/skills/sunzi/SKILL.md", ".agents/skills/sunzi/SKILL.md"):
        assert (root / d).read_bytes() == (root / "tools/sunzi/SKILL.md").read_bytes()


def test_tokens_two_char_word_and_bigrams():
    t = index.tokens("兵者，诡道也。Deception 101")
    assert "诡道" in t and "兵者" in t and "deception" in t and "101" in t and "道也" in t and "者诡" not in t


def test_cli_index_reports_shape_errors(repo):
    (repo["root"] / "tools/sunzi/dict/bad.md").write_text("---\nkind: concept\n---\nno title\n", encoding="utf-8")
    r = plug(repo["root"], "index")
    assert r.returncode == 0 and "index:" in r.stdout and "shape ERROR tools/sunzi/dict/bad.md" in r.stdout


EXCLUDE_YAML = '''
exclude:
  - "self/facts/**"
'''


def test_exclude_hides_files_from_walk_but_leaves_the_locks_alone(repo):
    """plug.yaml `exclude:` is a visibility switch: excluded files never reach walk(), the index or the check-up,
    and stay exactly as protected as they were."""
    from entryplug import config
    root = repo["root"]
    y = root / "plug.yaml"
    y.write_text(y.read_text(encoding="utf-8") + EXCLUDE_YAML, encoding="utf-8")
    cfg = config.load(root)
    assert config.excluded(cfg, "self/facts/example.md") and not config.excluded(cfg, "self/RULES.md")
    walked = config.walk(cfg)
    assert not any(f["area"] == "facts" for f in walked) and any(f["area"] == "rules" for f in walked)
    assert config.is_protected(cfg, "self/facts/example.md")          # excluded, still protected
    index.build(cfg, full=True)
    assert rows(cfg, "select count(*) from fts where kind='fact'")[0][0] == 0
    assert rows(cfg, "select count(*) from fts where kind='rule'")[0][0] > 0
CORPUS_YAML = """
corpus:
  - {path: shared-corpus, tool: sunzi, sub: clean}
"""
EXTRA_DOC = """---
id: extra-doc
title: 额外教材
kind: text
---
第一段：兵者，国之大事。

第二段：不可不察也。
"""


def test_corpus_can_be_declared_outside_an_equipment(repo):
    """plug.yaml `corpus:` mounts a corpus directory that does not sit under tools/<equipment>/corpus/ —
    a content repo may keep one shared corpus at its root."""
    from entryplug import config
    root = repo["root"]
    (root / "shared-corpus").mkdir()
    (root / "shared-corpus" / "extra-doc.md").write_text(EXTRA_DOC, encoding="utf-8")
    y = root / "plug.yaml"
    y.write_text(y.read_text(encoding="utf-8") + CORPUS_YAML, encoding="utf-8")
    cfg = config.load(root)
    walked = [f for f in config.walk(cfg) if f["area"] == "corpus" and "shared-corpus" in f["rel"]]
    assert len(walked) == 1 and walked[0]["tool"] == "sunzi" and walked[0]["sub"] == "clean"
    index.build(cfg, full=True)
    assert rows(cfg, "select scope, tool from fts where doc='extra-doc'")[0] == ("corpus", "sunzi")
    assert rows(cfg, "select count(*) from fts where doc='extra-doc'")[0][0] >= 1
    from entryplug import search
    assert search.search(cfg, "国之大事", scope="corpus")["total"] > 0
    assert not config.is_protected(cfg, "shared-corpus/extra-doc.md")     # corpus is append-only, never locked


def test_missing_declared_corpus_directory_warns(repo):
    from entryplug import check, config
    y = repo["root"] / "plug.yaml"
    y.write_text(y.read_text(encoding="utf-8") + CORPUS_YAML.replace("shared-corpus", "no-such-dir"), encoding="utf-8")
    r = check.run(config.load(repo["root"]), expire=False, tool_checks=False)
    assert any(f["code"] == "corpus_path" for f in r["warnings"])
    assert r["errors"] == []
def test_no_op_rebuild_never_tokenises_again(repo, monkeypatch):
    """Incremental has to mean incremental in the expensive dimension. Tokenising is ~all of the cost, so an
    unchanged file must not be tokenised a second time; its chunk count is read back from the table instead.
    Before this, a no-op rebuild of a 900-file content repo still cost ~35 s, and pre-commit pays it every commit."""
    calls = []
    real = index.tokens
    monkeypatch.setattr(index, "tokens", lambda t: (calls.append(1), real(t))[1])
    first = index.build(repo, full=True)
    assert len(calls) > 50, len(calls)                      # a full rebuild really does tokenise
    calls.clear()
    again = index.build(repo)
    assert calls == [], len(calls)                          # a no-op rebuild tokenises nothing at all
    assert again["changed"] == 0 and again["removed"] == 0
    assert again["chunks"] == first["chunks"] and again["files"] == first["files"]
    p = repo["root"] / "tools/sunzi/dict/shi.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n新加一行。\n", encoding="utf-8")
    calls.clear()
    third = index.build(repo)
    assert third["changed"] == 1 and 0 < len(calls) < 20, len(calls)   # only the file that moved


def test_index_md_still_names_unchanged_pages(repo):
    """The cheap metadata (titles, aliases, the playbook directory) is still recomputed for unchanged files —
    only tokenising is skipped — so the generated pages do not degrade on a no-op rebuild."""
    index.build(repo, full=True)
    before = (repo["root"] / "index.md").read_text(encoding="utf-8")
    (repo["root"] / "index.md").unlink()
    index.build(repo)
    after = (repo["root"] / "index.md").read_text(encoding="utf-8")
    assert "tools/sunzi/dict/shi.md · 势 · concept · 势能, 态势" in after
    assert after.splitlines()[1:] == before.splitlines()[1:]           # only the timestamp line may differ
    idx = (repo["root"] / "tools/sunzi/playbooks/INDEX.md").read_text(encoding="utf-8")
    assert sum(l.startswith("| opponent") for l in idx.splitlines()) == 2
