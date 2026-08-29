# 动词 index：一张 FTS5 表、按哈希增量、只取纯文本段、clean 优先、index.md / INDEX.md / 说明书镜像。
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
    assert idx[1].startswith("命中不是义务") and sum(l.startswith("| opponent") for l in idx) == 2 and len(idx) <= 60
    for d in (".claude/skills/sunzi/SKILL.md", ".agents/skills/sunzi/SKILL.md"):
        assert (root / d).read_bytes() == (root / "tools/sunzi/SKILL.md").read_bytes()


def test_tokens_two_char_word_and_bigrams():
    t = index.tokens("兵者，诡道也。Deception 101")
    assert "诡道" in t and "兵者" in t and "deception" in t and "101" in t and "道也" in t and "者诡" not in t


def test_cli_index_reports_shape_errors(repo):
    (repo["root"] / "tools/sunzi/dict/bad.md").write_text("---\nkind: concept\n---\nno title\n", encoding="utf-8")
    r = plug(repo["root"], "index")
    assert r.returncode == 0 and "index:" in r.stdout and "形状 ERROR tools/sunzi/dict/bad.md" in r.stdout
