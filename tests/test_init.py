# 动词 init：装钩子与驾驶员薄壳（真实绝对路径）· 合并不覆盖 · 幂等 · 装完 contact 两边全绿 · 别人的 pre-commit 备份 · 不是 git 仓库时跳过钩子。
import json, sys
from entryplug import init
from conftest import plug


def test_init_both_then_contact_green(git_repo):
    root = git_repo["root"]
    r = plug(root, "init", "--pilot", "both")
    assert r.returncode == 0, r.stdout + r.stderr
    hook = (root / ".git/hooks/pre-commit").read_text(encoding="utf-8")
    assert hook.startswith("#!/bin/sh") and "gates/precommit.py" in hook and sys.executable.replace("\\", "/") in hook
    s = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    base = init.posix_abs(root)
    assert "Edit(%s/self/RULES.md)" % base in s["permissions"]["deny"] and "Read(%s/.kb/hooks/**)" % base in s["permissions"]["deny"]
    assert not any(d.startswith("Write(") for d in s["permissions"]["deny"])
    assert "outbound.py" in json.dumps(s["hooks"]["PreToolUse"]) and "--emit" in json.dumps(s["hooks"]["SessionStart"])
    m = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["entryplug"]
    assert m["args"][-1] == "mcp" and m["command"] == sys.executable.replace("\\", "/")
    assert (root / "CLAUDE.md").exists() and (root / "AGENTS.md").exists()
    assert (root / ".agents/skills/sunzi/SKILL.md").exists() and (root / ".agents/skills/sunzi/agents/openai.yaml").exists()
    assert "outbound.py" in (root / ".codex/hooks.json").read_text(encoding="utf-8")
    assert "[mcp_servers.entryplug]" in (root / ".codex/config.toml").read_text(encoding="utf-8")
    gi = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".kb/" in gi and ".claude/skills/" in gi and ".agents/skills/" in gi
    for pilot in ("claude-code", "codex"):
        c = plug(root, "check", "--contact", pilot)
        assert c.returncode == 0 and c.stdout.strip().endswith("初期接触，无异常"), c.stdout


def test_init_is_idempotent_and_merges(git_repo):
    root = git_repo["root"]
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": ["Edit(//x/other)"], "allow": ["Bash(ls)"]}, "model": "x"}), encoding="utf-8")
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "o"}}}), encoding="utf-8")
    (root / "CLAUDE.md").write_text("主人自己的地图\n", encoding="utf-8")
    (root / ".git/hooks/pre-commit").write_text("#!/bin/sh\necho someone else\n", encoding="utf-8")
    r = plug(root, "init", "--pilot", "claude-code")
    assert r.returncode == 0 and "备份" in r.stdout and "跳过（已存在）" in r.stdout
    assert (root / ".git/hooks/pre-commit.before-entryplug").read_text(encoding="utf-8").endswith("someone else\n")
    s = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    assert s["model"] == "x" and s["permissions"]["allow"] == ["Bash(ls)"] and "Edit(//x/other)" in s["permissions"]["deny"]
    assert "other" in json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "主人自己的地图\n"
    assert not (root / "AGENTS.md").exists()
    snap = {p: p.read_bytes() for p in (root / ".claude/settings.json", root / ".mcp.json", root / ".git/hooks/pre-commit", root / ".gitignore")}
    r = plug(root, "init", "--pilot", "claude-code")
    assert r.returncode == 0 and "写入" not in r.stdout and "更新" not in r.stdout and r.stdout.count("已是最新") >= 3
    assert all(p.read_bytes() == b for p, b in snap.items())


def test_init_without_git_skips_hook(repo):
    r = plug(repo["root"], "init", "--pilot", "codex")
    assert r.returncode == 0 and "不是 git 仓库" in r.stdout and (repo["root"] / ".codex/hooks.json").exists()
    assert not (repo["root"] / ".claude/settings.json").exists()
