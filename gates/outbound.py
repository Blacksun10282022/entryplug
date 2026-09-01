# The sortie lock (prohibition ②): a PreToolUse hook — never act outward in the owner's name without asking.
# What: read the hook's JSON (tool_name · tool_input · cwd), match it against plug.yaml's outbound list
#       (a tool regex + an optional match regex over the tool input); a hit prints one line of reason on stderr,
#       stamps .kb/hooks/outbound and exits 2 (blocked, the pilot sees the reason). No hit exits 0.
# In:   the hook JSON on stdin; PLUG_ROOT, or walk up from cwd looking for plug.yaml.
# Out:  exit code 0 / 2; one line of reason.
# Not:  never rewrites the tool input (updatedInput is forbidden outright); never reads content; a missing
#       plug.yaml or broken JSON passes through (hooks are fail-open by design; the second layer is simply not
#       giving the pilot tools that can reach outward).
#       `.plug-off` at the content repo root makes this gate pass everything through, silently.
# Who:  Claude Code hooks (pilots/claude-code/hooks/hooks.json) · Codex hooks (pilots/codex/hooks.json) — one
#       list, one script · contact step ③ · tests.
# Note: interactively this blocks and asks; unattended (-p with ask rules) the documented behaviour is
#       "auto-deny and keep going", it does not hang. One hook, one verb; one line of reason.
# Deps: entryplug.config; falls back to this repo's path when it is not installed.
import json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entryplug import config  # noqa: E402


def match(rules, tool_name, tool_input):
    """Return the explanation of the first matching rule, or None."""
    blob = tool_input if isinstance(tool_input, str) else json.dumps(tool_input, ensure_ascii=False)
    for rule in rules or []:
        try:
            if re.search(rule.get("tool", ""), tool_name or "") and (not rule.get("match") or re.search(rule["match"], blob)):
                return rule.get("reason") or "tool=%s%s" % (rule.get("tool"), " match=%s" % rule["match"] if rule.get("match") else "")
        except re.error:
            continue
    return None


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        data = {}
    try:
        cfg = config.load(os.environ.get("PLUG_ROOT") or config.find_root(data.get("cwd")))
    except FileNotFoundError:
        print("sortie lock: no plug.yaml found, passing through (fail-open)", file=sys.stderr)
        return 0
    if config.plug_off(cfg):
        return 0                              # .plug-off: the plug is out, nothing is checked
    reason = match(cfg["outbound"], data.get("tool_name", ""), data.get("tool_input", {}))
    if reason is None:
        return 0
    cfg["hooks_dir"].mkdir(parents=True, exist_ok=True)
    (cfg["hooks_dir"] / "outbound").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    print("sortie lock: %s is an outward action (list entry %s) — nothing goes out in the owner's name; "
          "ask first" % (data.get("tool_name"), reason), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
