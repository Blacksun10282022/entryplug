# 动词 check：示例装备 0 ERROR；每种 ERROR 在临时副本里故意坏一次；主要 WARNING；提议过期搬家；头部自检；同步率的盲判核对。
from datetime import date
from entryplug import check, index, report
from conftest import git, plug

TODAY = date(2026, 8, 29)


def codes(r, level="errors"):
    return sorted({f["code"] for f in r[level]})


def edit(root, rel, old=None, new=None, text=None):
    p = root / rel
    s = text if text is not None else p.read_text(encoding="utf-8").replace(old, new)
    assert text is not None or old in p.read_text(encoding="utf-8"), "old text missing: " + old
    p.write_text(s, encoding="utf-8")


def run(cfg, **kw):
    index.build(cfg)
    return check.run(cfg, today=TODAY, **kw)


def test_example_has_zero_errors_and_known_warnings(repo):
    r = run(repo)
    assert r["errors"] == []
    assert {"outcome", "expired", "hook"} <= set(codes(r, "warnings"))
    assert all(f["at"] for f in r["warnings"])
    assert r["header"]["shape_ok"] and r["header"]["tools"] == ["sunzi"] and not r["header"]["index_stale"]
    assert repo["numbers_path"].exists() and "同步率" in r["numbers"] and "总分" in r["numbers"]
    text = report.report(repo, r)
    assert "ERROR 0" in text and "待批提议 1" in text and "过期资料 1" in text and "本周记录" in text


def test_error_shape(repo):
    edit(repo["root"], "tools/sunzi/dict/shi.md", "title: 势\n", "")
    assert "shape" in codes(run(repo))


def test_error_link_unresolved(repo):
    edit(repo["root"], "tools/sunzi/dict/shi.md", "## 注\n", "## 注\n见 [[不存在的词]]。\n")
    r = run(repo)
    assert "link" in codes(r) and any("不存在的词" in f["msg"] for f in r["errors"])


def test_error_observation_missing_src(repo):
    edit(repo["root"], "tools/sunzi/dict/shi.md", "## 关系", "- 没有来源的一句 ^p0999\n\n## 关系")
    assert "obs_src" in codes(run(repo))


def test_error_anchor_sentence_not_in_corpus(repo):
    edit(repo["root"], "tools/sunzi/dict/shi.md", "激水之疾，至于漂石者，势也\")", "激水之疾，至于漂石者，力也\")")
    r = run(repo)
    assert "anchor" in codes(r) and any("力也" in f["msg"] for f in r["errors"])


def test_error_pid_unresolved_and_unknown_doc(repo):
    edit(repo["root"], "tools/sunzi/dict/shi.md", "(src: ^p0002 ^p0004)", "(src: ^p0002 ^p9999)")
    edit(repo["root"], "tools/sunzi/dict/xing.md", "(src: sunzi-04-junxing#1 \"不可胜在己", "(src: no-such-doc#1 \"不可胜在己")
    assert {"pid", "anchor"} <= set(codes(run(repo)))


def test_error_record_rule_id_missing(repo):
    edit(repo["root"], "self/records/2026-08-27-choose-venue.md", "J1 · 先算", "J9 · 先算")
    r = run(repo)
    assert "rid" in codes(r) and any("J9" in f["msg"] for f in r["errors"])


def test_error_cross_tool_link_without_dependency(repo):
    edit(repo["root"], "tools/sunzi/dict/shi.md", "## 注\n", "## 注\n另见 [[other/势]]。\n")
    assert "cross_tool" in codes(run(repo))


def test_error_unknown_shape_version_refuses(repo):
    edit(repo["root"], "plug.yaml", "shape_version: 1 ", "shape_version: 99")
    from entryplug import config
    cfg = config.load(repo["root"])
    r = check.run(cfg, today=TODAY)
    assert codes(r) == ["shape_version"]
    assert plug(repo["root"], "search", "势").returncode == 1
    assert plug(repo["root"], "check").returncode == 1


def test_error_tool_check_exit_2_and_warning_lines(repo):
    hook = repo["root"] / "tools/sunzi/checks/boom.py"
    hook.write_text("import sys\nsys.stdout.reconfigure(encoding='utf-8')\nprint('挂点说：坏了')\nsys.exit(2)\n", encoding="utf-8")
    r = run(repo)
    assert any(f["code"] == "tool_check" and "坏了" in f["msg"] for f in r["errors"])
    hook.unlink()
    edit(repo["root"], "self/records/2026-08-27-choose-venue.md", "## 最强反证", "见「第十四篇」。\n## 最强反证")
    r = run(repo)
    assert any(f["code"] == "tool_check" and "第十篇" not in f["msg"] and "篇" in f["msg"] for f in r["warnings"])


def test_warnings_batch(repo):
    root = repo["root"]
    edit(root, "self/RULES.md", "- J4 · 让步只换算数的东西：交期、付款条件、书面承诺；口头承诺不算 [2026-08 · 示例]", "- J4 · 让步只换算数的东西")
    edit(root, "self/RULES.md", "到期 2026-12-31", "到期 2026-01-31")
    edit(root, "tools/sunzi/dict/fan-jian.md", "aliases: [用间, 五间, 反间计, double agent, fanjian]", "aliases: [用间]")
    edit(root, "tools/sunzi/dict/xing.md", "aliases: [军形, 形势, 不可胜, disposition, xing]", "aliases: [军形, 势, disposition]")
    edit(root, "tools/sunzi/playbooks/opponent-feigns-weakness.md", "## 动作\n", "## 动作\n- 让对方先报价。\n")
    edit(root, "tools/sunzi/SKILL.md", "## 学（只在主人点名时）", "见 tools/sunzi/dict/nope.md 与 `plug fly`。\n## 学（只在主人点名时）")
    edit(root, "tools/sunzi/SKILL.md", "description: 用《孙子兵法》", "description: " + "长" * 1600 + "用《孙子兵法》")
    edit(root, "tools/sunzi/dict/shi.md", "- [?] 治乱归于数", "- 治乱归于数")
    (root / "proposals/pending/2026-08-27-dup.md").write_text((root / "proposals/pending/2026-08-26-shi-alias.md").read_text(encoding="utf-8"), encoding="utf-8")
    w = set(codes(run(repo), "warnings"))
    assert {"rule_date", "rules_expired", "aliases", "collision", "warning_action", "path", "desc", "unreviewed", "dup"} <= w
    (root / "index.md").unlink()
    edit(root, "tools/sunzi/dict/shi.md", "## 注\n", "## 注\n改了。\n")
    r = check.run(repo, today=TODAY)
    assert {"index_md", "index_stale"} <= set(codes(r, "warnings")) and r["header"]["index_stale"]


def test_proposal_expiry_moves_to_rejected(repo):
    root = repo["root"]
    old = root / "proposals/pending/2026-06-01-old.md"
    old.write_text("---\ntarget: tools/sunzi/dict/shi.md\nbase: new\nfrom: records/x\n---\n## 改成什么\nx\n## 为什么\ny\n## 最强反证\nz\n", encoding="utf-8")
    r = run(repo, expire=False)
    assert old.exists() and r["moved"] == []
    r = run(repo)
    assert r["moved"] == ["proposals/pending/2026-06-01-old.md"] and not old.exists()
    moved = (root / "proposals/rejected/2026-06-01-old.md").read_text(encoding="utf-8")
    assert "rejected: 2026-08-29 · expired" in moved
    assert (root / "proposals/pending/2026-08-26-shi-alias.md").exists()


def test_hook_stamps_in_header(repo):
    repo["hooks_dir"].mkdir(parents=True, exist_ok=True)
    (repo["hooks_dir"] / "outbound").write_text("2026-08-28T10:00:00", encoding="utf-8")
    (repo["hooks_dir"] / "precommit").write_text("2026-01-01T10:00:00", encoding="utf-8")
    r = run(repo)
    hooks = {f["file"].split("/")[-1] for f in r["warnings"] if f["code"] == "hook"}
    assert hooks == {"precommit", "precompact"} and r["header"]["hooks"]["outbound"].startswith("2026-08-28")


def test_numbers_blind_check_uses_git_history(git_repo):
    root = git_repo["root"]
    blind = root / "self/records/2026-08-28-blind.md"
    blind.write_text("---\ntool: sunzi\nby: codex · gpt-5 · 2026-08-28\nsituation: s\nverdict: 不接\nchosen:\noutcome:\n---\n## 依据\nJ1 · 上次：无类似记录\n## 最强反证\nb\n## 什么会改判\nc\n", encoding="utf-8")
    git(root, "add", "-A"), git(root, "commit", "-q", "-m", "verdict first")
    blind.write_text(blind.read_text(encoding="utf-8").replace("chosen:\n", "chosen: 同意\n"), encoding="utf-8")
    nonblind = root / "self/records/2026-08-28-nonblind.md"
    nonblind.write_text(blind.read_text(encoding="utf-8").replace("chosen: 同意", "chosen: 不接"), encoding="utf-8")
    git(root, "add", "-A"), git(root, "commit", "-q", "-m", "chosen")
    r = run(git_repo)
    page = r["numbers"]
    assert "| 同意率（盲判有效） | 1/1" in page and "非盲 3 已剔" in page
    assert "| 规则引用真实率 | 6/6 |" in page and "| 引文可核率 | 6/6 |" in page
    assert "说不清 1" in page and "未答 1" in page
