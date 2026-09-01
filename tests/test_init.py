# Verb init: install the hooks and pilot shells (real absolute paths) · merge, never overwrite · idempotent ·
# contact is green on both sides afterwards · a foreign pre-commit is backed up · no git repo, no hook ·
# deny rules cover self/ and registered equipment only · --link-skills is a manual trigger.
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
        assert c.returncode == 0 and c.stdout.strip().endswith("first contact, nothing wrong"), c.stdout


def test_init_is_idempotent_and_merges(git_repo):
    root = git_repo["root"]
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": ["Edit(//x/other)"], "allow": ["Bash(ls)"]}, "model": "x"}), encoding="utf-8")
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "o"}}}), encoding="utf-8")
    (root / "CLAUDE.md").write_text("主人自己的地图\n", encoding="utf-8")
    (root / ".git/hooks/pre-commit").write_text("#!/bin/sh\necho someone else\n", encoding="utf-8")
    r = plug(root, "init", "--pilot", "claude-code")
    assert r.returncode == 0 and "backed up" in r.stdout and "skipped (exists)" in r.stdout
    assert (root / ".git/hooks/pre-commit.before-entryplug").read_text(encoding="utf-8").endswith("someone else\n")
    s = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    assert s["model"] == "x" and s["permissions"]["allow"] == ["Bash(ls)"] and "Edit(//x/other)" in s["permissions"]["deny"]
    assert "other" in json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "主人自己的地图\n"
    assert not (root / "AGENTS.md").exists()
    snap = {p: p.read_bytes() for p in (root / ".claude/settings.json", root / ".mcp.json", root / ".git/hooks/pre-commit", root / ".gitignore")}
    r = plug(root, "init", "--pilot", "claude-code")
    assert r.returncode == 0 and "written" not in r.stdout and "updated" not in r.stdout and r.stdout.count("already current") >= 3
    assert all(p.read_bytes() == b for p, b in snap.items())


def test_init_without_git_skips_hook(repo):
    r = plug(repo["root"], "init", "--pilot", "codex")
    assert r.returncode == 0 and "not a git repo" in r.stdout and (repo["root"] / ".codex/hooks.json").exists()
    assert not (repo["root"] / ".claude/settings.json").exists()


def test_deny_rules_cover_self_and_registered_equipment_only(git_repo):
    from entryplug import config, init as I
    rules = I.deny_rules(git_repo)
    assert all(r.startswith(("Edit(", "Read(")) for r in rules)
    assert any(r.endswith("/self/RULES.md)") for r in rules) and any(r.endswith("/tools/sunzi/dict/**)") for r in rules)
    assert not any("/work/" in r or "/workshop/" in r or "tools/**" in r for r in rules), rules
    for rel in ("work/sunzi/brief.md", "workshop/newtool/SKILL.md", "tools/unregistered/dict/x.md"):
        assert not config.is_protected(git_repo, rel), rel
    assert config.is_protected(git_repo, "tools/sunzi/dict/shi.md")
    r = plug(git_repo["root"], "init", "--pilot", "claude-code")
    deny = json.loads((git_repo["root"] / ".claude/settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
    assert not any("work" in d.rsplit("/", 2)[-2] for d in deny if d.count("/") > 2)
    assert "Stop" in json.loads((git_repo["root"] / ".claude/settings.json").read_text(encoding="utf-8"))["hooks"]
    assert (git_repo["root"] / "work/README.md").exists() and (git_repo["root"] / "workshop/README.md").exists()


def test_link_skills_is_a_manual_trigger_that_stamps_the_root(git_repo, tmp_path):
    root, dest = git_repo["root"], tmp_path / "userskills"
    r = plug(root, "init", "--pilot", "both", env={"PLUG_USER_SKILLS": str(dest)})
    assert r.returncode == 0 and not dest.exists() and "--link-skills" in r.stdout
    r = plug(root, "init", "--pilot", "both", "--link-skills", env={"PLUG_USER_SKILLS": str(dest)})
    assert r.returncode == 0, r.stdout + r.stderr
    skill = (dest / "claude-code" / "sunzi" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: sunzi") and "plug init --link-skills" in skill
    assert root.as_posix() in skill and "/work/sunzi/" in skill and "the Base (self/) is not loaded" in skill
    assert "allow_implicit_invocation: true" in (dest / "codex" / "sunzi" / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert not (dest / "claude-code" / ".mcp.json").exists()          # never a user-level MCP registration


def test_disable_model_invocation_rides_along(git_repo, tmp_path):
    root, dest = git_repo["root"], tmp_path / "userskills"
    p = root / "tools/sunzi/SKILL.md"
    p.write_text(p.read_text(encoding="utf-8").replace("name: sunzi\n", "name: sunzi\ndisable-model-invocation: true\n"), encoding="utf-8")
    assert plug(root, "init", "--pilot", "both", "--link-skills", env={"PLUG_USER_SKILLS": str(dest)}).returncode == 0
    assert "disable-model-invocation: true" in (dest / "codex" / "sunzi" / "SKILL.md").read_text(encoding="utf-8")
    assert "allow_implicit_invocation: false" in (dest / "codex" / "sunzi" / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "allow_implicit_invocation: false" in (root / ".agents/skills/sunzi/agents/openai.yaml").read_text(encoding="utf-8")
PROTECT_YAML = """
protect:
  - "tools/sunzi/kit/**"
  - "work/**"
"""


def test_protect_list_is_read_by_both_layers(git_repo):
    """`protect:` is one list read by both layers — plug init turns it into deny rules and config.is_protected
    hands it to pre-commit. It cannot override the two hard exemptions (the free zones, unregistered tools/)."""
    from entryplug import config, init as I
    root = git_repo["root"]
    y = root / "plug.yaml"
    y.write_text(y.read_text(encoding="utf-8") + PROTECT_YAML, encoding="utf-8")
    cfg = config.load(root)
    assert config.is_protected(cfg, "tools/sunzi/kit/resume.md")              # pre-commit layer
    assert any(d.endswith("/tools/sunzi/kit/**)") for d in I.deny_rules(cfg))  # deny layer
    assert not config.is_protected(cfg, "work/sunzi/brief.md")               # free zone still wins
    assert not config.is_protected(cfg, "tools/unregistered/kit/x.md")       # unregistered still wins
    r = plug(root, "init", "--pilot", "claude-code")
    assert r.returncode == 0, r.stdout + r.stderr
    deny = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
    assert any("tools/sunzi/kit/**" in d for d in deny), deny
