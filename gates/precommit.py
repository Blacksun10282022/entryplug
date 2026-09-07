# The berserk lock (prohibition ①), the hardest of the layers: a git pre-commit hook.
# What: a commit that touches a protected path (by default self/RULES.md · self/facts/** · tools/** minus the
#       corpus; policy from HEAD:plug.yaml, or working tree with a warning if absent) without KB_APPROVE=1 is refused.
#       Every other commit: a staged record or proposal must have its shape (D75); nothing else is checked here,
#       nothing is rebuilt or written, so the hook takes milliseconds. Stamps .kb/hooks/precommit.
# In:   the git index (git diff --cached --name-only -z); tests and first contact can pass PLUG_STAGED instead
#       (newline-separated paths) — honoured only outside a real git commit (GIT_INDEX_FILE unset). PLUG_ROOT is
#       ignored here: the repo is the one git is committing in.
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
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entryplug import config  # noqa: E402


def staged(root):
    """The paths this commit would write. PLUG_STAGED (a test seam) is honoured only when git is NOT running us —
    git sets GIT_INDEX_FILE for every hook, so inside a real commit the variable is ignored (D66). `-z` asks git
    for raw, NUL-separated names: with the default core.quotePath a non-ASCII path came back octal-escaped and
    matched no protected pattern, so every Chinese file name was silently unprotected (D67)."""
    env = os.environ.get("PLUG_STAGED")
    if env is not None and "GIT_INDEX_FILE" not in os.environ:
        return [l.strip().replace("\\", "/") for l in env.splitlines() if l.strip()]
    r = subprocess.run(["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRD"], cwd=str(root),
                       capture_output=True, text=True, encoding="utf-8")
    return [l for l in r.stdout.split("\0") if l.strip()]


def repo_root():
    """The repo git is committing in. PLUG_ROOT is deliberately NOT consulted here: pointed at another repo it made
    this gate judge somebody else's staged files under somebody else's plug.yaml (D66). cwd is the repo's top level
    when git runs a hook; tests and first contact run the script with cwd set the same way."""
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8")
    top = r.stdout.strip()
    return top if r.returncode == 0 and top and (Path(top) / "plug.yaml").exists() else config.find_root()


def stamp(cfg, name):
    cfg["hooks_dir"].mkdir(parents=True, exist_ok=True)
    (cfg["hooks_dir"] / name).write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")


def protection_policy(cfg):
    """Only committed policy may relax protection; repositories without it retain the existing fallback."""
    r = subprocess.run(["git", "show", "HEAD:plug.yaml"], cwd=str(cfg["root"]),
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("berserk lock warning: HEAD has no readable plug.yaml; using working-tree protection policy", file=sys.stderr)
        return cfg
    raw = yaml.safe_load(r.stdout) or {}
    policy = dict(cfg)
    for key in ("protected", "unprotected", "protect"):
        policy[key] = raw[key] if raw.get(key) is not None else config.DEFAULTS[key]
    policy["tools"] = [dict(t, path=t.get("path", f"tools/{t['name']}")) for t in raw.get("tools") or []]
    return policy


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    try:
        cfg = config.load(repo_root())
    except FileNotFoundError as e:
        print("berserk lock: %s — a repo without plug.yaml should not have this hook; fix the config first" % e, file=sys.stderr)
        return 1
    files = staged(cfg["root"])
    stamp(cfg, "precommit")
    policy = protection_policy(cfg)
    hit = [f for f in files if config.is_protected(policy, f)]
    if hit and os.environ.get("KB_APPROVE") != "1":
        more = " (%d in total)" % len(hit) if len(hit) > 1 else ""
        print("berserk lock: this commit touches the protected path %s%s — rules and equipment can only be changed "
              "through a refit request (proposals/pending/); the owner approves with plug apply" % (hit[0], more), file=sys.stderr)
        return 1
    from entryplug import shapes                 # D75: the hook refuses, it does not rebuild or check up
    known = {f["rel"]: f for f in config.walk(cfg)}
    bad = []
    for rel in files:
        f = known.get(rel)
        if f and f["area"] in ("record", "proposal") and f["path"].exists():
            bad += ["%s · %s" % (rel, e) for e in shapes.parse_file(f["path"].read_text(encoding="utf-8"), f["area"])["errors"]]
    if bad:
        print("shape error, commit refused: %s%s — fix the file; plug check explains the shape" %
              (bad[0], " (%d in total)" % len(bad) if len(bad) > 1 else ""), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
