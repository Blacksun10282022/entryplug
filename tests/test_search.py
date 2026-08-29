# 动词 search：中文两字词命中（ERROR 级验收）、别名扩展、默认只查工具、scope=corpus 明说、多组查询合并、行格式、不重排。
import json
from entryplug import search
from conftest import plug


def ids(res):
    return [r["id"] for r in res["rows"]]


def test_chinese_two_char_word_hits(repo):
    res = search.search(repo, "诡道")
    assert ids(res)[0] == "gui-dao" and res["total"] > 0
    assert search.search(repo, "虚实", scope="corpus")["total"] > 0


def test_single_char_and_alias_expansion(repo):
    assert ids(search.search(repo, "势"))[0] == "shi"
    assert ids(search.search(repo, "deception"))[0] == "gui-dao"
    assert ids(search.search(repo, "know the enemy and yourself"))[0] == "zhi-bi-zhi-ji"


def test_default_scope_is_tools_and_corpus_explicit(repo):
    res = search.search(repo, "致人而不致于人")
    assert all(r["kind"] != "corpus" for r in res["rows"])
    res = search.search(repo, "致人而不致于人", scope="corpus")
    assert ids(res)[0] == "sunzi-06-xushi#1" and res["rows"][0]["title_hit"]
    res = search.search(repo, "责任转移", scope="corpus")
    r = res["rows"][0]
    assert r["id"] == "BV1EXAMPLE01#5" and r["pos"] == "5:30" and r["lstart"] == 12 and "责任转移" in r["excerpt"]
    assert search.search(repo, "诡道", scope="all", kind="corpus")["rows"][0]["kind"] == "corpus"
    assert all(r["tool"] == "sunzi" for r in search.search(repo, "势", tool="sunzi")["rows"])


def test_multi_query_round_robin_merge_and_caps(repo):
    a = search.search(repo, "以迂为直", scope="corpus", k=3)
    b = search.search(repo, "反间", scope="corpus", k=3)
    both = search.search(repo, ["以迂为直", "反间"], scope="corpus", k=6)
    assert ids(both)[0] == ids(a)[0] and ids(b)[0] in ids(both)
    assert len(both["queries"]) == 2
    big = search.search(repo, ["兵", "者", "之", "也"], scope="all", k=999, per_doc=99)
    assert big["shown"] <= 60 and big["total"] <= 60
    capped = search.search(repo, "孙子曰", scope="corpus", k=30, per_doc=1)
    docs = [r["doc"] for r in capped["rows"]]
    assert len(docs) == len(set(docs))


def test_format_rows_and_cli(repo):
    text = search.format_rows(search.search(repo, "诡道", k=2))
    lines = text.splitlines()
    assert lines[0].startswith("gui-dao · 诡道 · tools/sunzi/dict/gui-dao.md#L") and " · concept · " in lines[0]
    assert lines[-1].startswith("已显示 2/")
    assert len(lines[0].split(" · ")[4]) <= 120
    r = plug(repo["root"], "search", "诡道", "--k", "1")
    assert r.returncode == 0 and r.stdout.startswith("gui-dao")
    r = plug(repo["root"], "search", "势", "拖延", "--json", "--scope", "corpus")
    assert json.loads(r.stdout)["queries"]


def test_fts_query_construction():
    assert search.fts_query("责任转移", []) == '"责任 任转 转移" OR "责任" OR "转移"' or search.fts_query("责任转移", []).startswith('"责任 任转 转移"')
    q = search.fts_query("对方在谈判里拖延 delay", [])
    assert '"delay"' in q and '"拖延"' in q
    assert search.fts_query("势", [["势", "势能"]]) == '"势"* OR "势能"'
    assert search.fts_query("", []) is None
