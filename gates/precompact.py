# The compaction pin: carry "where we are · which record · which equipment · how many pending proposals ·
# what language to answer in" across a context compaction. Not a prohibition — an engineering chore at the gate layer.
# What: on PreCompact, work out the pin, write .kb/pin.md, print it, and stamp .kb/hooks/precompact;
#       on SessionStart(matcher=compact) or with --emit, hand the same pin back as additionalContext
#       (D17: PreCompact's stdout is not guaranteed to reach the context).
# In:   the hook JSON on stdin (hook_event_name picks the mode; with no stdin, argv: --emit = re-inject,
#       otherwise pin); PLUG_ROOT, or walk up looking for plug.yaml.
# Out:  the pin text (PreCompact) or {"hookSpecificOutput": {...additionalContext}} (re-injection); exit 0.
# Not:  never injects the rules in full, never injects search results, never nags (all three forbidden outright);
#       it pins five facts, every one of them read off a file (the newest record + the pending count + plug.yaml).
#       `.plug-off` at the content repo root makes it pass through and pin nothing.
# Who:  Claude Code hooks (PreCompact · SessionStart compact) · Codex hooks on the same events · contact /
#       acceptance · tests. No plug.yaml → pass through (exit 0, no pin).
# Origin: in 2026-02 a user's "confirm before acting" instruction was lost to a compaction and the agent emptied
#       an inbox; drifting into English after a compaction is a real incident too — hence line five.
# Deps: entryplug.config · shapes; falls back to this repo's path when it is not installed.
import json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entryplug import config, shapes  # noqa: E402


def pin(cfg):
    recs = sorted(cfg["records_dir"].glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True) if cfg["records_dir"].is_dir() else []
    situation = tool = "(no records yet)"
    path = "(none)"
    if recs:
        fm, _, _ = shapes.split_frontmatter(recs[0].read_text(encoding="utf-8"))
        fm = fm or {}
        situation, tool, path = str(fm.get("situation") or "?"), str(fm.get("tool") or "?"), config.rel(cfg, recs[0])
    pend = cfg["proposals_dir"] / "pending"
    n = len(list(pend.glob("*.md"))) if pend.is_dir() else 0
    return "\n".join(["[entry plug · compaction pin · %s]" % time.strftime("%Y-%m-%d %H:%M"),
                      "where we are: %s" % situation,
                      "record: %s (Read it before continuing; do not carry on from memory. A fresh judgment means a new record.)" % path,
                      "equipment: %s" % tool,
                      "pending proposals: %d (%s/pending/)" % (n, cfg["proposals"]),
                      "answer in: %s" % cfg["language"]])


def main(argv):
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    data = {}
    if not sys.stdin.isatty():
        try:
            data = json.load(sys.stdin)
        except (ValueError, OSError):
            data = {}
    try:
        cfg = config.load(os.environ.get("PLUG_ROOT") or config.find_root(data.get("cwd")))
    except FileNotFoundError:
        print("compaction pin: no plug.yaml found, nothing pinned", file=sys.stderr)
        return 0
    if config.plug_off(cfg):
        return 0                              # .plug-off: the plug is out, nothing is pinned
    event = data.get("hook_event_name") or ("SessionStart" if "--emit" in argv else "PreCompact")
    if event == "PreCompact":
        text = pin(cfg)
        cfg["pin_path"].parent.mkdir(parents=True, exist_ok=True)
        cfg["pin_path"].write_text(text + "\n", encoding="utf-8", newline="\n")
        cfg["hooks_dir"].mkdir(parents=True, exist_ok=True)
        (cfg["hooks_dir"] / "precompact").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8", newline="\n")
        print(text)
        return 0
    text = cfg["pin_path"].read_text(encoding="utf-8") if cfg["pin_path"].exists() else pin(cfg)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
