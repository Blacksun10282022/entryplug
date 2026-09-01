# Shapes: the field table for the three strict shapes, and parsing of observation lines / rule lines / corpus docs.
# Every way frontmatter can be out of shape is broken once here.
from pathlib import Path
from entryplug import shapes

ENTRY = """---
kind: concept
title: 势
aliases: [势能, momentum]
---
## 定义
x
## 观察
- 善战者求之于势 [[形]] ^p0001 (src: sunzi-05-bingshi#6 "故善战者，求之于势，不责于人")
- [?] 综合一句 (src: ^p0001 ^p0002)
- 无原句 (src: sunzi-05-bingshi p.3 [未锚])
- 缺来源的一行
## 关系
- 属于 [[庙算]]
"""


def parse(text, area="dict"):
    return shapes.parse_file(text, area)


def test_entry_ok_and_observations():
    r = parse(ENTRY)
    assert r["errors"] == [] and r["shape"] == "entry"
    assert r["links"] == ["形", "庙算"]
    o = r["obs"]
    assert (o[0]["anchor"], o[0]["doc"], o[0]["seq"], o[0]["quote"]) == ("^p0001", "sunzi-05-bingshi", "6", "故善战者，求之于势，不责于人")
    assert o[1]["unreviewed"] and o[1]["refs"] == ["^p0001", "^p0002"] and o[1]["quote"] is None
    assert o[2]["unanchored"] and o[2]["doc"] == "sunzi-05-bingshi"
    assert o[3]["missing_src"]


def test_entry_shape_errors():
    assert any("title" in e for e in parse(ENTRY.replace("title: 势\n", ""))["errors"])
    assert any("alias" in e for e in parse(ENTRY.replace("aliases: [势能, momentum]\n", ""))["errors"])
    assert any("kind" in e for e in parse(ENTRY.replace("kind: concept", "kind: thing"))["errors"])
    assert any("unknown field" in e for e in parse(ENTRY.replace("title: 势\n", "title: 势\ncolour: red\n"))["errors"])
    assert any("frontmatter" in e for e in parse("no frontmatter\n")["errors"])
    pb = ENTRY.replace("kind: concept", "kind: playbook")
    errs = parse(pb, "playbook")["errors"]
    assert any("situation" in e for e in errs) and any("stance" in e for e in errs)
    pb += ""
    ok = pb.replace("aliases: [势能, momentum]\n", "situation: s\nwhen_not: w\nstance: diagnostic\n")
    assert parse(ok, "playbook")["errors"] == []


def test_record_and_proposal_shapes():
    rec = "---\ntool: sunzi\nby: codex · gpt-5 · 2026-08-21\nsituation: s\nverdict: v\nchosen:\noutcome:\n---\n## 依据\na\n## 最强反证\nb\n## 什么会改判\nc\n"
    assert parse(rec, "record")["errors"] == []
    assert any("verdict" in e for e in parse(rec.replace("verdict: v\n", ""), "record")["errors"])
    assert any("最强反证" in e for e in parse(rec.replace("## 最强反证", "## 反证"), "record")["errors"])
    prop = "---\ntarget: tools/sunzi/dict/shi.md\nbase: 3d42b9a9\nfrom: records/x\n---\n## 改成什么\nretire\n## 为什么\nw\n## 最强反证\nc\n"
    assert parse(prop, "proposal")["errors"] == []
    assert any("base" in e for e in parse(prop.replace("base: 3d42b9a9\n", ""), "proposal")["errors"])
    mat = "---\ndate: 2026-07-10\nkind: price\n---\nx\n"
    assert parse(mat, "material")["errors"] == []
    assert any("date" in e for e in parse(mat.replace("2026-07-10", "July"), "material")["errors"])
    assert any("description" in e for e in parse("---\nname: x\n---\nbody\n", "manual")["errors"])


def test_parse_rules():
    text = ("model: claude-fable-5 · codex      reviewed: 2026-08-29\n## 底线\n- B1 · 不违法 [2026-08 · 主人]\n- B2 · 没日期\n"
            "## 当前计划（到期 2026-11-30）\n- P1 · 待到 11 月 [2026-08]\n## 判断规则\n- J1 · 当务之急（复核 2026-12）：x [2026-08]\n## 已退役\n")
    r = shapes.parse_rules(text)
    assert r["header"] == {"model": "claude-fable-5", "reviewed": "2026-08-29"}
    assert r["ids"] == {"B1", "B2", "P1", "J1"} and r["retired"]
    lines = {l["id"]: l for s in r["sections"] for l in s["lines"]}
    assert lines["B1"]["dated"] and not lines["B2"]["dated"] and lines["J1"]["review"] == "2026-12"
    assert [s["expires"] for s in r["sections"]] == [None, "2026-11-30", None, None]


def test_parse_doc_three_formats():
    lec = "Title: 讲座｜势与形\nBVID: BV1EXAMPLE01\nDate: 2026-08-01\n==== 纯文本 ====\n第一段。\n第二段。\n==== 带时间戳 ====\n[0.0s] 第一段\n"
    d = shapes.parse_doc(lec, Path("x/lec.txt"), "raw")
    assert (d["id"], d["series"], d["kind"]) == ("BV1EXAMPLE01", "讲座", "lecture")
    assert d["units"] == [(5, 6, "", "第一段。\n第二段。")] and "0.0s" not in d["text"]
    clean = "Title: 计篇\nID: sunzi-01\nDate: 2026-08-01\nSource: raw/x\nCleaned: codex\nSpeaker: -\n====\n[0:00] 兵者，国之大事。\n[¶2] 死生之地。\n"
    d = shapes.parse_doc(clean, Path("x/clean.md"), "clean")
    assert d["units"] == [(8, 8, "0:00", "兵者，国之大事。"), (9, 9, "¶2", "死生之地。")]
    d = shapes.parse_doc("---\nid: b1\ntitle: 书\ndate: 2020\nkind: book\n---\n第一行。\n第二行。\n", Path("x/b.md"), "raw")
    assert d["id"] == "b1" and d["kind"] == "book" and d["units"][0][0] == 7 and "第二行" in d["text"]
    d = shapes.parse_doc("# 标题\n正文。\n", Path("x/plain.md"), "raw")
    assert d["id"] == "plain" and d["title"] == "标题"
