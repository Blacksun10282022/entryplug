# The record reminder: a Stop hook. Reminder level — it never blocks, it never rewrites anything, it exits 0 always.
# What: at the end of a turn, ask whether a record was written this session. If none was touched since the session
#       began, print one nudge — once per session, not every turn (D77); otherwise stay silent. Stamps .kb/hooks/stop.
# In:   the hook JSON on stdin (transcript_path tells us when the session started; cwd finds plug.yaml);
#       PLUG_ROOT overrides the root. PLUG_RECORD_WINDOW (hours, default 8) is the fallback when there is no
#       transcript path and no earlier stamp.
# Out:  {"systemMessage": …} on stdout when it has something to say, nothing when it has not; always exit 0.
# Not:  never blocks (exit 2 is not used here), never writes a record for the pilot, never edits content, never
#       injects rules or search results. `.plug-off` makes it pass through in silence, like the other soft gates.
# Who:  Claude Code hooks (Stop) · Codex hooks on the same event · tests.
# Note: the discipline it is reminding of: a record holds a judgment, not a diary. Given options, the owner chose
#       → write one record on the spot. Nothing decided → nothing to write, and this hook stays quiet about it.
# Deps: entryplug.config; falls back to this repo's path when it is not installed.
import json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entryplug import config  # noqa: E402

NUDGE = ("entry plug · no record was written this session. If the owner was given options and chose one, write it "
         "now: %s/<date>-<slug>.md (tool · by · situation · verdict + 依据 / 最强反证 / 什么会改判). "
         "If nothing was decided, there is nothing to write — this is a reminder, not a gate.")


def session_start(cfg, data):
    """When this session began: the transcript's creation time, else a window (PLUG_RECORD_WINDOW hours)."""
    tp = data.get("transcript_path")
    if tp:
        try:
            return os.path.getctime(tp)
        except OSError:
            pass
    return time.time() - float(os.environ.get("PLUG_RECORD_WINDOW", "8")) * 3600


def newest_record(cfg):
    d = cfg["records_dir"]
    return max((p.stat().st_mtime for p in d.glob("*.md")), default=None) if d.is_dir() else None


def main():
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
        return 0
    if config.plug_off(cfg):
        return 0                              # .plug-off: the plug is out, no record nagging
    since = session_start(cfg, data)
    newest = newest_record(cfg)
    stamp = cfg["hooks_dir"] / "stop"
    nudged_already = stamp.exists() and stamp.stat().st_mtime >= since     # D77: one nudge per session, not per turn
    cfg["hooks_dir"].mkdir(parents=True, exist_ok=True)
    stamp.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8", newline="\n")
    if (newest is not None and newest >= since) or nudged_already:
        return 0
    print(json.dumps({"systemMessage": NUDGE % (config.rel(cfg, cfg["records_dir"]))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
