# Verb init: install the hooks and pilot shells (real absolute paths) · merge, never overwrite · idempotent ·
# contact is green on both sides afterwards · a foreign pre-commit is backed up · no git repo, no hook ·
# deny rules cover self/ and registered equipment only · --link-skills is a manual trigger.
import json, sys
from entryplug import init
from conftest import plug, trust_codex


def test_init_both_then_contact_green(git_repo):
    root = git_repo["root"]
    r = plug(root, "init", "--pilot", "both")
    assert r.returncode == 0, r.stdout + r.stderr
    hook = (root / ".git/hooks/pre-commit").read_text(encoding="utf-8")
    assert hook.startswith("#!/bin/sh") and "gates/precommit.py" in hook and sys.executable.replace("\\", "/") in hook
    s = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    base = init.posix_abs(root)
    assert "Edit(%s/self/RULES.md)" % base in s["permissions"]["deny"]
    # The stamps are deny-write, not deny-read: a pilot must be able to check whether a gate fired, and forging a
    # stamp (silencing "this hook has not fired", in a gitignored dir pre-commit never sees) is the real risk.
    assert "Edit(%s/.kb/hooks/**)" % base in s["permissions"]["deny"]
    assert not any(d.startswith(("Write(", "Read(")) for d in s["permissions"]["deny"])
    assert "outbound.py" in json.dumps(s["hooks"]["PreToolUse"]) and "--emit" in json.dumps(s["hooks"]["SessionStart"])
    m = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["entryplug"]
    assert m["args"][-1] == "mcp" and m["command"] == sys.executable.replace("\\", "/")
    assert (root / "CLAUDE.md").exists() and (root / "AGENTS.md").exists()
    assert (root / ".agents/skills/sunzi/SKILL.md").exists() and (root / ".agents/skills/sunzi/agents/openai.yaml").exists()
    assert "outbound.py" in (root / ".codex/hooks.json").read_text(encoding="utf-8")
    assert "[mcp_servers.entryplug]" in (root / ".codex/config.toml").read_text(encoding="utf-8")
    gi = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".kb/" in gi and ".claude/skills/" in gi and ".agents/skills/" in gi
    env = trust_codex(root, root.parent / "codexhome")     # the owner trusts the hooks once; without it Codex skips them
    for pilot in ("claude-code", "codex"):
        c = plug(root, "check", "--contact", pilot, env=env)
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


def test_a_dot_path_can_be_protected(git_repo):
    """The files that define the locks are dot-paths. New in this build — `is_protected` normalised with
    lstrip("./"), which takes a SET of characters, so it ate the leading dot: `.claude/settings.json` arrived as
    `claude/settings.json` and could never match a pattern that kept the dot. Every dot-path (.claude/, .codex/,
    .github/, .env) was silently unprotectable — plug.yaml could list it and pre-commit would still let it through."""
    from entryplug import config, init as I
    root = git_repo["root"]
    y = root / "plug.yaml"
    # `protect:` is the key both layers read (init.deny_rules and config.is_protected), so it is the one that
    # keeps them covering the same set — see deny_rules' docstring.
    y.write_text(y.read_text(encoding="utf-8")
                 + "\nprotect:\n  - \".claude/settings.json\"\n  - \".codex/**\"\n", encoding="utf-8")
    cfg = config.load(root)
    assert config.is_protected(cfg, ".claude/settings.json")
    assert config.is_protected(cfg, ".codex/hooks.json")
    assert config.is_protected(cfg, "./.claude/settings.json"), "a leading ./ must still be stripped"
    assert not config.is_protected(cfg, ".github/workflows/ci.yml"), "only what protect: lists"
    assert any(r.endswith("/.claude/settings.json)") for r in I.deny_rules(cfg)), "deny must cover the same set"
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
def test_codex_hooks_are_written_in_codex_shape(git_repo):
    """Codex takes `command` as one whitespace-split string with no quoting. The Claude form (quoted paths) made it
    spawn a program whose name contained quote characters, which is why every Codex hook reported Failed (D53)."""
    from entryplug import init as I
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "codex").returncode == 0
    h = json.loads((root / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert set(h) == {"PreToolUse", "PreCompact", "SessionStart", "Stop"}
    for event, groups in h.items():
        for g in groups:
            for entry in g["hooks"]:
                cmd = entry["command"]
                assert isinstance(cmd, str), (event, cmd)          # a list is rejected by Codex outright
                assert '"' not in cmd and "'" not in cmd, (event, cmd)   # quoting is not honoured
                assert cmd.split()[0].endswith(("python.exe", "python", "python3")), cmd
    pre = h["PreToolUse"][0]["hooks"][0]["command"]
    assert pre.endswith("gates/outbound.py") and "matcher" in h["PreToolUse"][0]
    assert h["SessionStart"][0]["hooks"][0]["command"].endswith("status --emit")


def test_claude_hooks_keep_their_own_quoted_shape(git_repo):
    """The two pilots do not share a hook shape: Claude Code needs the quoted form and must not be changed."""
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "claude-code").returncode == 0
    s = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    cmd = s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd.startswith('"') and "outbound.py" in cmd, cmd
def test_untrusted_codex_hooks_are_reported_not_assumed(git_repo, tmp_path):
    """Codex skips a hook whose trusted_hash no longer matches, silently (D58). Everything that reports on the
    sortie lock must therefore refuse to call it armed until the trust record matches what is installed."""
    from entryplug import config
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "both").returncode == 0
    empty = tmp_path / "nohome"; empty.mkdir()
    (empty / "config.toml").write_text("[hooks.state]\n", encoding="utf-8")
    env = {"CODEX_HOME": str(empty)}
    msg = config.codex_trust(config.load(root), codex_home=str(empty))
    assert msg and "none of the" in msg and "is trusted" in msg, msg
    s = plug(root, "status", env=env)
    assert "[NG] Sortie lock" in s.stdout or "Codex has not trusted" in s.stdout, s.stdout
    c = plug(root, "check", "--quiet", "--no-expire", env=env)
    assert "codex_trust" in c.stdout, c.stdout
    k = plug(root, "check", "--contact", "codex", env=env)
    assert k.returncode == 1 and "will not run it" in k.stdout, k.stdout   # step 3 fails rather than claiming a block
    good = trust_codex(root, tmp_path / "yeshome")
    assert config.codex_trust(config.load(root), codex_home=good["CODEX_HOME"]) is None
    assert "codex_trust" not in plug(root, "check", "--quiet", "--no-expire", env=good).stdout


def test_init_says_hooks_need_retrusting_when_it_changes_them(git_repo):
    r = plug(git_repo["root"], "init", "--pilot", "codex")
    assert "RE-TRUST" in r.stdout and "silently" in r.stdout.lower(), r.stdout
    again = plug(git_repo["root"], "init", "--pilot", "codex")     # unchanged file: no false alarm
    assert "RE-TRUST" not in again.stdout, again.stdout


def test_codex_trust_uses_codex_own_hash_recipe(tmp_path):
    """The trust check is worth nothing unless it computes the hash Codex computes. Codex hashes a normalised
    handler: sha256 over the canonical JSON of {event_name, matcher?, hooks:[handler]} — keys sorted, no spaces,
    absent options dropped, an absent timeout defaulted to 600 (D58). These two vectors are pinned so that a
    later tidy-up of the serialiser cannot quietly change the answer, and the recipe behind them was checked
    against five hashes Codex itself recorded for this machine's own hooks."""
    from entryplug import config
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi", "timeout": 30}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}]}}), encoding="utf-8")
    pairs = config.codex_hooks(p)
    assert {k.rsplit("hooks.json:", 1)[1]: h for k, h in pairs} == {
        "pre_tool_use:0:0": "sha256:65f88c378f287741bd683c759c7306a773bbb410594d61f7a39b723f8ab8eb45",
        "stop:0:0": "sha256:4f878c38b4dbda92e002b63eef79a8f2f60364c2b7b7490baffe2e180dcea6ac"}, pairs
    assert pairs[0][0].startswith(str(p) + ":"), pairs      # the key Codex files the trust decision under


def test_editing_a_trusted_codex_hook_makes_it_untrusted_again(git_repo, tmp_path):
    """The failure this guards against is the quiet one: the hook list keeps its shape, one command changes, and
    Codex stops running that hook without saying so. A key-set or timestamp check misses it; a hash check does
    not, and it names how many of the hooks are affected rather than condemning the lot."""
    from entryplug import config
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "codex").returncode == 0
    env = trust_codex(root, tmp_path / "home")
    assert config.codex_trust(config.load(root), codex_home=env["CODEX_HOME"]) is None
    p = root / ".codex" / "hooks.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"] += " --oops"
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    msg = config.codex_trust(config.load(root), codex_home=env["CODEX_HOME"])
    assert msg and "changed since they were trusted" in msg, msg
    assert msg.startswith("1 of the "), msg
    assert "[NG] Sortie lock" in plug(root, "status", env=env).stdout
