# 初期接触（plug check --contact）：四步各一行；钩子与 deny 装好 → 全绿；缺 deny（Claude Code）或缺钩子 → 那一步 FAIL；结果写进数字页。
import json, sys
from conftest import ROOT, plug

GATE = ROOT / "gates" / "precommit.py"


def install(root, deny=True):
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexec \"%s\" \"%s\"\n" % (sys.executable.replace("\\", "/"), str(GATE).replace("\\", "/")), encoding="utf-8")
    if deny:
        (root / ".claude").mkdir(exist_ok=True)
        rules = ["Edit(//c/x/self/RULES.md)", "Edit(//c/x/self/facts/**)", "Edit(//c/x/tools/**)", "Read(//c/x/.kb/hooks/**)"]
        (root / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": rules}}), encoding="utf-8")


def test_contact_all_green_both_pilots(git_repo):
    root = git_repo["root"]
    install(root)
    for pilot in ("claude-code", "codex"):
        r = plug(root, "check", "--contact", pilot)
        assert r.returncode == 0, r.stdout + r.stderr
        lines = r.stdout.splitlines()
        assert lines[0].startswith("初期接触 · %s · harness " % pilot)
        assert [l[:1] for l in lines[1:5]] == ["①", "②", "③", "④"] and all(" OK " in l for l in lines[1:5])
        assert "中文查询「" in lines[2] and "命中" in lines[2] and "exit 2" in lines[3]
        assert lines[-1] == "初期接触，无异常"
    assert "Codex 没有 permissions.deny" in r.stdout
    assert "初期接触 codex" in git_repo["numbers_path"].read_text(encoding="utf-8")


def test_contact_fails_without_deny_or_hook(git_repo):
    root = git_repo["root"]
    install(root, deny=False)
    r = plug(root, "check", "--contact", "claude-code")
    assert r.returncode == 1 and "④ 受保护写入 FAIL" in r.stdout and "接入坏了" in r.stdout and "第 4 步" in r.stdout
    (root / ".git/hooks/pre-commit").unlink()
    r = plug(root, "check", "--contact", "codex")
    assert r.returncode == 1 and "没装 pre-commit 钩子" in r.stdout
