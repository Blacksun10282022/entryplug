# The Antigravity pilot (the desktop app and the agy CLI, one wiring — D87): plug init writes the workspace plugin
# and the maps · the sortie lock speaks Antigravity's protocol (toolCall in, {"decision": "deny"} out, exit 0) ·
# the boot panel in its injectSteps shape · first contact is green · a switched-off plugin or an outbound list that
# never names run_command is reported, never assumed armed.
import json, os, subprocess, sys
from entryplug import antigravity, config
from conftest import ROOT, plug

GATE = ROOT / "gates" / "outbound.py"
PLUGIN = antigravity.PLUGIN


def agy_env(tmp_path, plugins=None):
    """Antigravity's config dir, standing in for ~/.gemini/config so the owner's real one is never read."""
    d = tmp_path / "agyconfig"
    d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps({"plugins": plugins or {}}), encoding="utf-8")
    return {"PLUG_AGY_CONFIG": str(d)}


def call(name, args, cwd):
    return {"hookEventName": "PreToolUse", "conversationId": "c", "workspacePaths": [str(cwd)], "cwd": str(cwd),
            "stepIdx": 3, "toolCall": {"id": "t1", "name": name, "args": args}}


def gate(payload, cwd):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("PLUG_ROOT", None)
    return subprocess.run([sys.executable, str(GATE)], cwd=str(cwd), env=env, capture_output=True, text=True,
                          encoding="utf-8", input=json.dumps(payload, ensure_ascii=False))


def test_init_writes_the_workspace_plugin_and_the_maps(git_repo):
    root = git_repo["root"]
    r = plug(root, "init", "--pilot", "antigravity")
    assert r.returncode == 0, r.stdout + r.stderr
    hooks = json.loads((root / PLUGIN / "hooks.json").read_text(encoding="utf-8"))
    pre = hooks["sortie-lock"]["PreToolUse"][0]
    assert pre["matcher"] == antigravity.MATCHER and {"run_command", "send_command_input", "call_mcp_tool", "mcp_.*"} <= set(pre["matcher"].split("|"))
    for cmd in (pre["hooks"][0]["command"], hooks["boot-panel"]["SessionStart"][0]["command"]):
        assert isinstance(cmd, str) and '"' not in cmd, cmd           # bare words: cmd /c takes the line as typed
    assert pre["hooks"][0]["command"].endswith("gates/outbound.py")
    assert hooks["boot-panel"]["SessionStart"][0]["command"].endswith("status --emit antigravity")
    m = json.loads((root / PLUGIN / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]["entryplug"]
    assert m["args"][-1] == "mcp" and m["command"] == sys.executable.replace("\\", "/") and root.as_posix() in m["args"]
    assert json.loads((root / PLUGIN / "plugin.json").read_text(encoding="utf-8"))["name"] == "entryplug"
    assert (root / "GEMINI.md").exists() and (root / "AGENTS.md").exists()
    assert "antigravity ·" in (root / "GEMINI.md").read_text(encoding="utf-8")
    assert not (root / ".claude/settings.json").exists() and not (root / ".codex/hooks.json").exists()
    again = plug(root, "init", "--pilot", "antigravity")
    assert again.returncode == 0 and "written" not in again.stdout and "updated" not in again.stdout, again.stdout


def test_init_all_installs_three_pilots_and_one_gitignore_line(repo):
    root = repo["root"]
    assert plug(root, "init", "--pilot", "all").returncode == 0
    assert (root / ".claude/settings.json").exists() and (root / ".codex/hooks.json").exists() and (root / PLUGIN / "hooks.json").exists()
    lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines.count(".agents/skills/") == 1, lines                 # Codex and Antigravity share the mirror


def test_the_sortie_lock_speaks_antigravity(repo):
    root = repo["root"]
    r = gate(call("run_command", {"CommandLine": "curl -X POST https://example.invalid/send", "Cwd": str(root)}, root), root)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and out["decision"] == "deny" and "sortie lock" in out["reason"] and "run_command" in out["reason"]
    assert "hookSpecificOutput" not in out                           # the other protocol's answer would be ignored here
    assert (repo["hooks_dir"] / "outbound").exists()
    assert antigravity.denied(gate(call("run_command", {"CommandLine": "git push origin main"}, root), root).stdout)
    quiet = gate(call("run_command", {"CommandLine": "git status", "Cwd": str(root)}, root), root)
    assert quiet.returncode == 0 and not quiet.stdout.strip()
    # only the command line runs, so only the command line is matched — the model's toolSummary beside it is not
    prose = gate(call("run_command", {"CommandLine": "ls", "toolSummary": "then curl -X POST it"}, root), root)
    assert not prose.stdout.strip(), prose.stdout
    # the second door into the same shell: text typed into a running command is matched like a command line
    typed = gate(call("send_command_input", {"CommandId": "c1", "Input": "git push origin main\n", "WaitMs": "500"}, root), root)
    assert antigravity.denied(typed.stdout) and "send_command_input" in typed.stderr, typed.stdout + typed.stderr
    assert not gate(call("send_command_input", {"CommandId": "c1", "Input": "y\n"}, root), root).stdout.strip()


def test_both_forms_of_an_mcp_call_meet_the_one_list(repo):
    """Antigravity hands an MCP call to the hook as call_mcp_tool (ServerName · ToolName · Arguments) or as the tool
    itself, mcp_<server>_<tool>. Both are renamed mcp__…, so the list written for the other pilots catches them."""
    root = repo["root"]
    by_name = gate(call("call_mcp_tool", {"ServerName": "mail", "ToolName": "send_email", "Arguments": "{'to': 'a'}"}, root), root)
    assert antigravity.denied(by_name.stdout) and "mcp__mail__send_email" in by_name.stderr, by_name.stdout + by_name.stderr
    direct = gate(call("mcp_mail_send_email", {"to": "a", "toolSummary": "Send it"}, root), root)
    assert antigravity.denied(direct.stdout) and "mcp__mail_send_email" in direct.stderr, direct.stdout + direct.stderr
    search = gate(call("call_mcp_tool", {"ServerName": "entryplug", "ToolName": "search", "Arguments": "{'query': 'send'}"}, root), root)
    assert not search.stdout.strip(), search.stdout                   # a read is not an outward action
    assert antigravity.tool_call({"tool_name": "Bash"}) is None        # the other protocol is left alone


def test_the_hook_finds_the_repo_from_the_plugin_folder(repo, tmp_path):
    """Antigravity runs a hook with the plugin folder as its cwd; the agent's own cwd may sit outside the repo."""
    root = repo["root"]
    folder = root / PLUGIN
    folder.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    r = gate(call("run_command", {"CommandLine": "curl -X POST https://example.invalid/x"}, elsewhere), folder)
    assert antigravity.denied(r.stdout), r.stdout + r.stderr


def test_plug_apply_refuses_inside_antigravity(git_repo):
    """Every command Antigravity runs carries ANTIGRAVITY_AGENT (seen live in agy 1.5.13), so its pilot cannot
    approve its own refit request; the owner approves from a terminal of his own, as with the other pilots."""
    r = plug(git_repo["root"], "apply", "proposals/pending/2026-08-26-shi-alias.md", env={"ANTIGRAVITY_AGENT": "1"})
    assert r.returncode == 1 and "ANTIGRAVITY_AGENT" in r.stdout, r.stdout + r.stderr


def test_boot_panel_in_antigravity_shape(git_repo):
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "antigravity").returncode == 0 and plug(root, "index").returncode == 0
    r = plug(root, "status", "--emit", "antigravity")
    assert r.returncode == 0, r.stderr
    step = json.loads(r.stdout)["injectSteps"][0]["systemMessage"]
    assert step["systemMessage"].startswith("entry plug boot: SYNC RATE") and "never paste it" in step["systemMessage"]
    assert "ENTRY PLUG — INSERTION SEQUENCE" in step["renderInfo"]["markdown"]        # the owner's screen, never the model's
    assert "metadata" not in step                                     # agy drops a hook whose metadata holds a string
    assert "ENTRY PLUG" not in step["systemMessage"]
    old = json.loads(plug(root, "status", "--emit").stdout)                         # the bare flag keeps its old shape
    assert "systemMessage" in old and old["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_first_contact_green_on_antigravity(git_repo, tmp_path):
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "antigravity").returncode == 0 and plug(root, "index").returncode == 0
    r = plug(root, "check", "--contact", "antigravity", env=agy_env(tmp_path))
    lines = r.stdout.splitlines()
    assert r.returncode == 0 and lines[-1] == "first contact, nothing wrong", r.stdout
    assert lines[0].startswith("first contact · antigravity · harness ")
    assert "the payload shape Antigravity sends" in lines[3] and "Antigravity has no deny rules" in lines[4]


def test_switched_off_plugin_and_unnamed_shell_tool_are_reported(git_repo, tmp_path):
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "antigravity").returncode == 0 and plug(root, "index").returncode == 0
    off = agy_env(tmp_path, {"entryplug": {"enabled": False}})
    s = plug(root, "status", env=off)
    assert "[NG] Sortie lock" in s.stdout and "switched off" in s.stdout, s.stdout
    assert "agy_plugin" in plug(root, "check", "--quiet", "--no-expire", env=off).stdout
    k = plug(root, "check", "--contact", "antigravity", env=off)
    assert k.returncode == 1 and "③ sortie lock FAIL" in k.stdout and "switched off" in k.stdout, k.stdout
    on = agy_env(tmp_path)                                          # switched back on
    assert antigravity.problem(config.load(root), conf=on["PLUG_AGY_CONFIG"]) is None
    y = root / "plug.yaml"
    y.write_text(y.read_text(encoding="utf-8").replace("|send_command_input)$", ")$"), encoding="utf-8")
    msg = antigravity.problem(config.load(root), conf=on["PLUG_AGY_CONFIG"])
    assert msg and "no outbound rule names send_command_input" in msg and "run_command" not in msg.split("—")[0], msg
    y.write_text(y.read_text(encoding="utf-8").replace("|run_command)$", ")$"), encoding="utf-8")
    msg = antigravity.problem(config.load(root), conf=on["PLUG_AGY_CONFIG"])
    assert msg and "no outbound rule names run_command or send_command_input" in msg, msg
    s = plug(root, "status", env=on)
    assert "[NG] Sortie lock" in s.stdout and "run_command" in s.stdout, s.stdout
