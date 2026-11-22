# What: what the machine knows about the Codex pilot: its .codex/hooks.json shape (five hooks, bare space-separated
#       command words, D53), Codex's own hook-trust hash recipe (`version_for_toml`, D58), whether ~/.codex/config.toml
#       still trusts the installed hooks, and Codex's approval_policy / sandbox_mode posture.
# In:   cfg · interpreter path and machine repo (from init) · hooks.json path · optional codex_home (tests).
# Out:  hooks_config() → JSON-ready dict; codex_hooks() → [(trust key, sha256)]; codex_trust() → problem text or None;
#       posture() → one-line summary of approval_policy and sandbox_mode.
# Not:  never writes files; never edits ~/.codex; never runs codex itself.
# Who:  init (--pilot codex) · config (re-exports codex_hooks · codex_trust) · status · check · contact · tests.
# Note: uses stdlib tomllib (Python 3.12+) rather than regex on config.toml, so double-quoted keys, comments and
#       sub-tables ([profiles.*]) are read the way Codex reads them.
# Deps: stdlib hashlib · json · os · tomllib · pathlib.
import hashlib, json, os, tomllib
from pathlib import Path

CODEX_EVENTS = {"PreToolUse": "pre_tool_use", "PermissionRequest": "permission_request", "PostToolUse": "post_tool_use",
                "PreCompact": "pre_compact", "PostCompact": "post_compact", "SessionStart": "session_start",
                "SessionEnd": "session_end", "UserPromptSubmit": "user_prompt_submit", "SubagentStart": "subagent_start",
                "SubagentStop": "subagent_stop", "Stop": "stop", "Interrupt": "interrupt"}
CODEX_CONTEXT = ("pre_tool_use", "post_tool_use", "session_start", "user_prompt_submit", "subagent_start")


def cmd(*parts):
    """Codex takes `command` as ONE string and splits it on whitespace without honouring quotes, so the Claude
    form (quoted paths) makes it try to spawn a program whose name contains quote characters (D53)."""
    return " ".join(str(p) for p in parts)


def hooks_config(cfg, py, repo, matcher):
    """The same five gates as Claude Code, in Codex's shape: {hooks: {<Event>: [{matcher?, hooks: [handler]}]}} with
    bare space-separated words. SessionStart[0] is the boot panel; SessionStart[1] re-injects the compaction pin."""
    gate = lambda s, *a: cmd(py, (Path(repo) / "gates" / s).as_posix(), *a)
    cli = cmd(py, "-m", "entryplug.cli", "--root", cfg["root"].as_posix(), "status", "--emit")
    return {"hooks": {
        "PreToolUse": [{"matcher": matcher, "hooks": [{"type": "command", "command": gate("outbound.py"), "timeout": 30}]}],
        "PreCompact": [{"hooks": [{"type": "command", "command": gate("precompact.py"), "timeout": 30}]}],
        "SessionStart": [
            {"matcher": "startup|resume|clear", "hooks": [{"type": "command", "command": cli, "timeout": 30}]},
            {"matcher": "compact", "hooks": [{"type": "command", "command": gate("precompact.py", "--emit"), "timeout": 30}]},
        ],
        "Stop": [{"hooks": [{"type": "command", "command": gate("stop.py"), "timeout": 20}]}],
    }}


def codex_hooks(hooks_json):
    """Every handler in a Codex hooks.json as (trust key, the hash Codex expects it to have).
    Key: <abs path>:<event_snake>:<group index>:<handler index>. Hash: sha256 over the canonical JSON of the
    handler after Codex normalises it — Codex's own recipe (D58), checked against five hashes Codex wrote."""
    try:
        cfg = (json.loads(Path(hooks_json).read_text(encoding="utf-8")) or {}).get("hooks") or {}
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for ev, groups in cfg.items():
        snake = CODEX_EVENTS.get(ev, ev.lower())
        for gi, g in enumerate(groups or []):
            for hi, h in enumerate((g or {}).get("hooks") or []):
                t, short = h.get("timeout"), snake in ("session_end", "interrupt")
                t = min(max(1 if t is None else t, 1), 3) if short else max(600 if t is None else t, 1)
                hook = {"type": "command", "command": h.get("command") or "", "timeout": t, "async": bool(h.get("async"))}
                if h.get("statusMessage") is not None:
                    hook["statusMessage"] = h["statusMessage"]
                if h.get("additionalContextLimit") not in (None, 2500) and snake in CODEX_CONTEXT:
                    hook["additionalContextLimit"] = h["additionalContextLimit"]
                obj = {"event_name": snake, "hooks": [hook]}
                if (g or {}).get("matcher") is not None:
                    obj["matcher"] = g["matcher"]
                blob = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
                out.append(("%s:%s:%d:%d" % (hooks_json, snake, gi, hi), "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()))
    return out


def config_path(codex_home=None):
    return Path(codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"


def codex_trust(cfg, codex_home=None):
    """Whether Codex will really run the hooks installed here, decided the way Codex decides it (D58).
    Returns None when every hook will run, otherwise one line: what is wrong and how to fix it."""
    hooks = cfg["root"] / ".codex" / "hooks.json"
    if not hooks.exists():
        return None
    conf = config_path(codex_home)
    fix = "open an interactive `codex` in this repo once; it shows a `Hooks need review` screen — trust them there."
    if not conf.exists():
        return "Codex hooks are installed but %s does not exist, so nothing has ever been trusted and none of them runs. %s" % (conf, fix)
    try:
        doc = tomllib.loads(conf.read_text(encoding="utf-8", errors="replace"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return "Codex config %s could not be read (%s), so hook trust cannot be verified. %s" % (conf, e, fix)
    raw = (doc.get("hooks") or {}).get("state") or {}
    state = {k.lower(): v for k, v in raw.items() if isinstance(v, dict)}
    want = codex_hooks(hooks)
    off = [k for k, _ in want if state.get(k.lower(), {}).get("enabled") is False]
    bad = [k for k, h in want if k not in off and state.get(k.lower(), {}).get("trusted_hash") != h]
    if off:
        return "%d of the %d Codex hooks are switched off in %s, so Codex skips them. Turn them back on there." % (len(off), len(want), conf)
    if not bad:
        return None
    if len(bad) == len(want):
        return "none of the %d Codex hooks is trusted as it now stands, so Codex runs none of them and the sortie lock is off on that side. %s" % (len(want), fix)
    return "%d of the %d Codex hooks changed since they were trusted, so Codex skips those silently. %s" % (len(bad), len(want), fix)


def posture(codex_home=None):
    """Codex's own approval policy and sandbox, read from top-level ~/.codex/config.toml (respects CODEX_HOME)."""
    p = config_path(codex_home)
    if not p.exists():
        return "%s not found — check `approval_policy` / `sandbox_mode` yourself" % p
    try:
        doc = tomllib.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return "%s unreadable (%s) — check it yourself" % (p, e)
    got = {k: str(doc[k]) if isinstance(doc.get(k), str) else "unset" for k in ("approval_policy", "sandbox_mode")}
    plain = {"never": "nothing is ever asked", "on-request": "it asks when it wants more", "untrusted": "asks outside trusted commands",
             "on-failure": "asks only after a sandboxed failure", "danger-full-access": "no sandbox at all",
             "workspace-write": "may write in the workspace", "read-only": "cannot write"}
    return "approval_policy=%s (%s) · sandbox_mode=%s (%s)" % (
        got["approval_policy"], plain.get(got["approval_policy"], "?"),
        got["sandbox_mode"], plain.get(got["sandbox_mode"], "?"))
