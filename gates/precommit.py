# The berserk lock (prohibition ①), the hardest of the layers: a git pre-commit hook.
# What: a commit that touches a protected path (by default self/RULES.md · self/facts/** · tools/** minus the
#       corpus; see plug.yaml protected/unprotected) without KB_APPROVE=1 is refused with one line of reason.
#       Every other commit: rebuild the index, then check must report 0 ERROR to pass. Stamps .kb/hooks/precommit.
# In:   the git index (git diff --cached --name-only); tests and first contact can pass PLUG_STAGED instead
#       (newline-separated paths).
# Out:  exit 0 = pass, 1 = refused; the reason is one line on stderr. No plug.yaml is also a refusal — this
#       gate is the fail-closed one.
# Not:  never reads or edits content; never asks who is committing (the owner is no exception: approving is
#       `plug apply`, which is what sets KB_APPROVE=1); never git-adds generated files (D19).
#       `.plug-off` does NOT affect this gate — nothing turns the berserk lock off.
# Who:  the content repo's .git/hooks/pre-commit (template gates/hooks/pre-commit, one line exec'ing this file)
#       · contact step ④ · tests.
# Note: Claude Code, Codex and any script writing directly all pass through here. Codex has no permissions.deny,
#       so on that side this is the only layer of prohibition ①. What a pilot may write and commit freely is
#       records/, proposals/, corpus/, work/ and workshop/ — nothing else.
# Deps: entryplug (pip install -e .); falls back to this repo's path when it is not installed.
import os, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entryplug import config  # noqa: E402


def staged(root):
    env = os.environ.get("PLUG_STAGED")
    if env is not None:
        return [l.strip().replace("\\", "/") for l in env.splitlines() if l.strip()]
    r = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRD"], cwd=str(root),
                       capture_output=True, text=True, encoding="utf-8")
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def stamp(cfg, name):
    cfg["hooks_dir"].mkdir(parents=True, exist_ok=True)
    (cfg["hooks_dir"] / name).write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    try:
        cfg = config.load(os.environ.get("PLUG_ROOT") or config.find_root())
    except FileNotFoundError as e:
        print("berserk lock: %s — a repo without plug.yaml should not have this hook; fix the config first" % e, file=sys.stderr)
        return 1
    files = staged(cfg["root"])
    stamp(cfg, "precommit")
    hit = [f for f in files if config.is_protected(cfg, f)]
    if hit and os.environ.get("KB_APPROVE") != "1":
        more = " (%d in total)" % len(hit) if len(hit) > 1 else ""
        print("berserk lock: this commit touches the protected path %s%s — rules and equipment can only be changed "
              "through a refit request (proposals/pending/); the owner approves with plug apply" % (hit[0], more), file=sys.stderr)
        return 1
    from entryplug import check, index
    index.build(cfg)
    r = check.run(cfg, expire=False)
    if r["errors"]:
        e = r["errors"][0]
        print("check found %d ERROR(s), commit refused: %s · %s · %s" % (len(r["errors"]), e["code"], e["file"], e["msg"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
