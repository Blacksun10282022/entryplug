# What: what the machine knows about the Antigravity pilot. The desktop app (Antigravity 2.0) and the `agy` CLI
#       run one engine and read one workspace customization root, `.agents/`, so they are one pilot with one
#       wiring (D87): a workspace plugin at .agents/plugins/entryplug/ (plugin.json · mcp_config.json · hooks.json),
#       the hook protocol the gates speak to it, and whether that plugin is switched off.
# In:   cfg · the interpreter and the machine repo (from init) · a hook payload (from the gates).
# Out:  plain dicts and strings; this file writes nothing (init writes what plugin_files() returns).
# Not:  never registers anything user-level — the MCP server rides in the workspace plugin because Antigravity's only
#       other MCP file is ~/.gemini/config/mcp_config.json; never edits ~/.gemini; wires neither the compaction pin
#       (no compaction event) nor the record reminder (its Stop hook can only keep the loop running) — D90.
# Who:  init (--pilot antigravity) · contact (--contact antigravity) · status · check · gates/outbound.py · tests.
# Note: the contract is Antigravity's own (builtin agy-customizations/docs/hooks.md, verified live — D88): a
#       camelCase payload, the call in `toolCall {name, args}` with PascalCase args, a deny is
#       {"decision": "deny", "reason": …} on stdout from a process that exits 0, matchers are anchored regexes on
#       the tool name. A hook runs as `cmd /d /s /c "<command>"` with the plugin folder as cwd; bare words, as for
#       Codex. On agy 1.5.13 a hook that exits non-zero or prints anything but valid JSON fails the tool call (the
#       guide says fail-open; this engine is not), so the gate prints nothing at all to let a call through.
# Deps: stdlib json · os · re · pathlib.
import json, os, re
from pathlib import Path

PLUGIN = ".agents/plugins/entryplug"
SKILLS, USER_SKILLS = ".agents/skills", "~/.gemini/config/skills"
# The tools that put a command line into a shell, and the argument holding the text that runs: run_command starts
# one, send_command_input types into one already running — a second door to the same shell, so it is gated too.
SHELL_TOOLS = {"run_command": "CommandLine", "send_command_input": "Input"}
MCP_CALL = "call_mcp_tool"                   # an MCP call by name: args ServerName · ToolName · Arguments
MCP_DIRECT = "mcp_"                          # …or the MCP tool itself, offered as mcp_<server>_<tool>
MATCHER = "run_command|send_command_input|call_mcp_tool|mcp_.*"   # what the sortie lock has to see here (D88)
DESC_MAX = 1024                              # Antigravity's cap on a skill description (Claude Code's is 1,536)


def plugin_files(cfg, py, repo):
    """The three files of the workspace plugin, as {path relative to the content repo: JSON-ready dict}. Commands
    are bare, space-separated words: `cmd /c` takes the line as typed, and a path with a space is warned about by
    init rather than written into a hook that would die at its first call."""
    root, gates = cfg["root"].as_posix(), (Path(repo) / "gates").as_posix()
    cmd = lambda *parts: " ".join(str(p) for p in parts)
    hooks = {
        "sortie-lock": {"PreToolUse": [{"matcher": MATCHER, "hooks": [
            {"type": "command", "command": cmd(py, gates + "/outbound.py"), "timeout": 30}]}]},
        "boot-panel": {"SessionStart": [
            {"type": "command", "command": cmd(py, "-m", "entryplug.cli", "--root", root, "status", "--emit", "antigravity"), "timeout": 30}]},
    }
    server = {"command": py, "args": ["-m", "entryplug.cli", "--root", root, "mcp"], "env": {"PYTHONIOENCODING": "utf-8"}}
    return {PLUGIN + "/plugin.json": {"name": "entryplug"},
            PLUGIN + "/mcp_config.json": {"mcpServers": {"entryplug": server}},
            PLUGIN + "/hooks.json": hooks}


def tool_call(data):
    """(tool name, tool input) when the payload speaks Antigravity's protocol, else None. Only Antigravity sends a
    `toolCall` object, so the shape itself says which protocol answers (D88) — unlike D65's tool_use_id, which both
    other pilots carried. A shell call is matched on its command line alone, as `command` is on the other side (the
    model's own toolSummary beside it never runs). An MCP call reaches the hook in one of two forms — call_mcp_tool
    naming ServerName and ToolName, or the tool itself as mcp_<server>_<tool> — and both are renamed mcp__…, the
    prefix Claude Code and Codex give the same tool, so one outbound list covers all three pilots."""
    tc = data.get("toolCall") if isinstance(data, dict) else None
    if not isinstance(tc, dict):
        return None
    name, args = str(tc.get("name") or ""), tc.get("args") if isinstance(tc.get("args"), dict) else {}
    if isinstance(args.get(SHELL_TOOLS.get(name, "")), str):
        return name, {"command": args[SHELL_TOOLS[name]]}
    if name == MCP_CALL:
        return "mcp__%s__%s" % (args.get("ServerName") or "", args.get("ToolName") or ""), args
    if name.startswith(MCP_DIRECT) and not name.startswith("mcp__"):
        return "mcp__" + name[len(MCP_DIRECT):], args
    return name, args


def deny(reason):
    return {"decision": "deny", "reason": reason}


def boot(panel, line):
    """The SessionStart answer in Antigravity's shape, D74's split kept: the panel goes to the owner's screen as the
    message's renderInfo.markdown, which the model never reads (agy -p does not print it; whether the app shows it
    is checked by hand); the model gets the one boot line as the system
    message. Not metadata.user_markdown, which its own hooks guide names: neither engine has that field, and agy
    1.5.13 drops the whole hook with "cannot convert string to message" (D89)."""
    return {"injectSteps": [{"systemMessage": {"systemMessage": line, "renderInfo": {"markdown": "```\n%s\n```" % panel}}}]}


def config_dir(conf=None):
    """Antigravity's user config folder; PLUG_AGY_CONFIG points it elsewhere (tests never read the owner's)."""
    return Path(conf or os.environ.get("PLUG_AGY_CONFIG") or Path.home() / ".gemini" / "config")


def installed(cfg):
    return (cfg["root"] / PLUGIN / "hooks.json").exists()


def problem(cfg, conf=None):
    """None when the Antigravity side of the sortie lock will really run, else one line saying why it will not:
    the plugin is switched off in Antigravity's config.json (its own on/off switch, keyed by directory name), or no
    outbound rule names a tool Antigravity runs commands through, so its shell calls reach the gate and match
    nothing. Says nothing when the plugin is not installed: Antigravity is then simply not a pilot here."""
    if not installed(cfg):
        return None
    path = config_dir(conf) / "config.json"
    try:
        state = ((json.loads(path.read_text(encoding="utf-8")) or {}).get("plugins") or {}).get("entryplug") or {}
    except (OSError, ValueError, AttributeError):
        state = {}
    if state.get("enabled") is False:
        return "the entryplug plugin is switched off in %s, so Antigravity runs neither the sortie lock nor the boot panel. Turn it back on in its plugin settings (or `agy plugin enable entryplug`)" % path
    unnamed = [t for t in SHELL_TOOLS if not any(_names(r, t) for r in cfg["outbound"])]
    if unnamed:
        return "armed for Claude Code and Codex; no outbound rule names %s, so what Antigravity runs through it matches nothing — add it to the shell rules in plug.yaml" % " or ".join(unnamed)
    return None


def _names(rule, tool):
    try:
        return bool(re.search(rule.get("tool", ""), tool))
    except re.error:
        return False


def fake_calls(root):
    """What first contact sends the gate on this side: the payload Antigravity really sends (D88)."""
    base = {"hookEventName": "PreToolUse", "conversationId": "c", "workspacePaths": [str(root)], "cwd": str(root), "stepIdx": 1}
    calls = (("run_command", {"CommandLine": "curl -X POST https://example.invalid/send", "WaitMsBeforeAsync": "5000", "toolSummary": "s"}),
             ("send_command_input", {"CommandId": "c1", "Input": "git push --dry-run https://example.invalid/x.git\n", "WaitMs": "500"}),
             (MCP_CALL, {"ServerName": "mail", "ToolName": "send_email", "Arguments": "{'to': 'x'}"}),
             ("mcp_mail_send_email", {"to": "x", "toolSummary": "s"}))
    return [dict(base, toolCall={"id": "t%d" % i, "name": n, "args": a}) for i, (n, a) in enumerate(calls)]


def denied(stdout):
    try:
        out = json.loads(stdout.strip().splitlines()[-1])
        return out.get("decision") == "deny" and bool(str(out.get("reason") or "").strip())
    except (ValueError, IndexError, AttributeError):
        return False
