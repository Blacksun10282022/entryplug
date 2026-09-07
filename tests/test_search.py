# Verb search: a two-character Chinese word hits (ERROR-grade acceptance), alias expansion, the default scope is
# the equipment layer, corpus needs saying, several queries merge, the row format, no reranking.
import json
import pytest
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
    assert lines[-1].startswith("showing 2/")
    assert len(lines[0].split(" · ")[4]) <= 120
    r = plug(repo["root"], "search", "诡道", "--k", "1")
    assert r.returncode == 0 and r.stdout.startswith("gui-dao")
    r = plug(repo["root"], "search", "势", "拖延", "--json", "--scope", "corpus")
    assert json.loads(r.stdout)["queries"]


def test_zero_hits_explain_scope_and_a_missing_index_is_rebuilt_on_read(repo):
    r = plug(repo["root"], "search", "责任")                       # 责任 lives only in the corpus: 0 hits in tools, the tail must say so
    assert r.returncode == 0 and r.stdout.startswith("showing 0/0 · no hit in scope tools") and "scope=corpus" in r.stdout and "index built" in r.stdout
    r = plug(repo["root"], "search", "责任", "--scope", "corpus")
    assert r.stdout.startswith("BV1EXAMPLE01#5")
    text = search.format_rows(search.search(repo, "责任", scope="corpus"))
    assert "showing 1/1" in text.splitlines()[-1] and "no hit" not in text
    repo["index_path"].unlink()                                   # D76: the ordinary CLI still rebuilds a missing index
    r = plug(repo["root"], "search", "责任")
    assert r.returncode == 0 and r.stdout.startswith("showing 0/0 · no hit in scope tools") and repo["index_path"].exists()
    repo["index_path"].unlink()
    from entryplug import mcp
    res, err = mcp.handle(repo, {"method": "tools/call", "params": {"name": "search", "arguments": {"query": "责任", "scope": "corpus"}}})
    assert err is None and res["isError"] is True and "run plug index first" in res["content"][0]["text"]
    r = plug(repo["root"], "search", "责任", "--no-index")
    assert r.returncode == 1 and "run plug index first" in r.stderr and not repo["index_path"].exists()
    with pytest.raises(FileNotFoundError, match="run plug index first"):       # read-only callers report the missing index
        search.search(repo, "责任", auto_index=False)


def test_fts_query_construction():
    assert search.fts_query("责任转移", []) == '"责任 任转 转移" OR "责任" OR "转移"' or search.fts_query("责任转移", []).startswith('"责任 任转 转移"')
    q = search.fts_query("对方在谈判里拖延 delay", [])
    assert '"delay"' in q and '"拖延"' in q
    assert search.fts_query("势", [["势", "势能"]]) == '"势"* OR "势能"'
    assert search.fts_query("", []) is None


def test_a_stale_index_is_rebuilt_on_read(repo):
    """D76: edit a page, search for the new word: the index is rebuilt before the answer, no plug index needed."""
    from entryplug import index
    assert not index.stale(repo)
    p = repo["root"] / "tools/sunzi/dict/shi.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n新词自动重建索引。\n", encoding="utf-8", newline="\n")
    assert index.stale(repo)
    assert search.search(repo, "自动重建索引")["total"] > 0
    assert not index.stale(repo)
    assert search.search(repo, "自动重建索引", auto_index=False)["total"] > 0


def test_mcp_and_cli_no_index_warn_without_rebuilding(repo):
    import io
    from entryplug import index, mcp
    before = repo["index_path"].read_bytes()
    page = repo["root"] / "tools/sunzi/dict/shi.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nnewstaleword\n", encoding="utf-8", newline="\n")
    assert index.stale(repo)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "search", "arguments": {"query": "newstaleword"}}}
    out = io.BytesIO()
    mcp.serve(repo, io.BytesIO((json.dumps(msg) + "\n").encode("utf-8")), out)
    result = json.loads(out.getvalue())["result"]           # warning stays inside the single JSON-RPC response
    text = result["content"][0]["text"]
    assert not result["isError"] and "showing 0/0" in text and text.count("stale; run plug index") == 1
    r = plug(repo["root"], "search", "newstaleword", "--no-index")
    assert r.returncode == 0 and "showing 0/0" in r.stdout and r.stdout.count("stale; run plug index") == 1
    r = plug(repo["root"], "search", "newstaleword", "--no-index", "--json")
    result = json.loads(r.stdout)
    assert r.returncode == 0 and result["total"] == 0 and result["warning"] == "stale; run plug index"
    assert repo["index_path"].read_bytes() == before and index.stale(repo)
    r = plug(repo["root"], "search", "newstaleword", "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["total"] > 0 and not index.stale(repo)
