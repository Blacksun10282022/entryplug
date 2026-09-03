# What: the two trust checks on things the machine executes or relies on but never wrote itself: is the installed
#       pre-commit hook the real berserk lock (hook_ok), and may an equipment check run (run_checks).
# In:   a hook path; cfg plus the check-up's err / warn callbacks.
# Out:  hook_ok → bool. run_checks → findings through the callbacks; a script that git does not track unchanged is a
#       WARNING and is not executed.
# Not:  never edits anything; never decides what a check means (exit 0 = reminders, 2 = ERROR is the D20 contract).
# Who:  status · contact · check (run_checks) · tests.
# Note: D68 — a substring test ("precommit" in the file) was satisfied by a stub whose only statement was `exit 0`.
#       D70 — checks/*.py are globbed from disk and run with the owner's full environment on every commit, while
#       pre-commit only inspects the paths being committed, so an untracked or edited script ran unapproved.
# Deps: stdlib subprocess · config.
import os, re, subprocess, sys
from pathlib import Path
from . import config


def hook_ok(path):
    """Is this pre-commit file the berserk lock and nothing else? The hook plug init writes has exactly one
    executable line, `exec <python> <gates/precommit.py>`, and that script must exist."""
    try:
        lines = [l.strip() for l in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()]
    except OSError:
        return False
    code = [l for l in lines if l and not l.startswith("#")]
    if len(code) != 1 or not code[0].startswith("exec ") or "precommit.py" not in code[0]:
        return False
    m = re.search(r'"([^"]*precommit\.py)"', code[0]) or re.search(r"(\S*precommit\.py)", code[0])
    return bool(m) and Path(m.group(1)).is_file()


def trusted_script(root, rel):
    """(may it run, why not). In a git repo only a tracked file with no uncommitted change qualifies; outside git
    there is nothing to trust against, and it runs as before."""
    try:
        if subprocess.run(["git", "rev-parse", "--git-dir"], cwd=str(root), capture_output=True, text=True).returncode != 0:
            return True, ""
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel], cwd=str(root), capture_output=True, text=True).returncode == 0
        dirty = subprocess.run(["git", "-c", "core.quotePath=false", "status", "--porcelain", "--", rel], cwd=str(root),
                               capture_output=True, text=True, encoding="utf-8").stdout.strip()
    except OSError:
        return True, ""
    return (False, "not tracked by git") if not tracked else (False, "has uncommitted changes") if dirty else (True, "")


def run_checks(cfg, warn, err):
    """Run every registered equipment's checks/*.py (D20 mount point) that git trusts; report the rest."""
    root = cfg["root"]
    for t in cfg["tools"]:
        for s in sorted((t["dir"] / "checks").glob("*.py")) if (t["dir"] / "checks").is_dir() else []:
            rel, env = config.rel(cfg, s), dict(os.environ, PLUG_ROOT=str(root), PLUG_TOOL=t["name"], PLUG_TOOL_DIR=str(t["dir"]), PYTHONIOENCODING="utf-8")
            ok, why = trusted_script(root, rel)
            if not ok:
                warn("tool_check", rel, "equipment check skipped: %s (commit it first; a check runs on every commit)" % why)
                continue
            try:
                r = subprocess.run([sys.executable, str(s)], cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
            except subprocess.TimeoutExpired:
                warn("tool_check", rel, "equipment check timed out after 60 s")
                continue
            for line in r.stdout.splitlines():
                (err if r.returncode == 2 else warn)("tool_check", rel, line.strip())
            if r.returncode not in (0, 2):
                warn("tool_check", rel, "equipment check exited %d: %s" % (r.returncode, r.stderr.strip()[-160:]))
