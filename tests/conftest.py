# Shared fixtures: a temporary copy of the example equipment (indexed), a copy with git, and a helper that runs
# `plug` as a subprocess. The machine's tests only ever run against example-tool, never a real content repo.
import os, shutil, subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "example-tool"
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from entryplug.apply import AGENT_ENV  # noqa: E402


def owner_env(extra=None):
    """The environment the owner has in a terminal: no agent markers. The test suite itself usually runs inside
    an agent, and `plug apply` refuses that on purpose — see test_apply.test_apply_refuses_in_agent_environment."""
    e = dict(os.environ, PYTHONIOENCODING="utf-8")
    for k in AGENT_ENV:
        e.pop(k, None)
    e.update(extra or {})
    return e


def copy_example(dst):
    shutil.copytree(EXAMPLE, dst, ignore=shutil.ignore_patterns(".kb", ".claude", ".agents", "index.md", "数字.md"))
    return dst


@pytest.fixture
def repo(tmp_path):
    """A temporary copy of example-tool, already indexed. Returns cfg."""
    from entryplug import config, index
    cfg = config.load(copy_example(tmp_path / "content"))
    index.build(cfg)
    return cfg


def git(root, *args, env=None):
    e = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
             GIT_COMMITTER_EMAIL="t@example.com", **(env or {}))
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args], cwd=str(root),
                          capture_output=True, text=True, encoding="utf-8", env=e)


@pytest.fixture
def git_repo(repo):
    """The same copy with git history: everything committed once."""
    root = repo["root"]
    (root / ".gitignore").write_text(".kb/\n.claude/skills/\n.agents/skills/\n", encoding="utf-8")
    assert git(root, "init", "-q", "-b", "main").returncode == 0
    git(root, "config", "user.name", "t"), git(root, "config", "user.email", "t@example.com")
    assert git(root, "add", "-A").returncode == 0
    r = git(root, "commit", "-q", "-m", "init")
    assert r.returncode == 0, r.stderr
    return repo


def plug(root, *args, env=None, stdin=None):
    """Run `python -m entryplug.cli --root <root> ...` and return the CompletedProcess (stdout/stderr as utf-8)."""
    e = owner_env(env)
    e.pop("KB_APPROVE", None) if not (env and "KB_APPROVE" in env) else None
    return subprocess.run([sys.executable, "-m", "entryplug.cli", "--root", str(root), *args], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", env=e, input=stdin)
