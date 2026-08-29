# 测试共用夹具：示例装备的临时副本（含索引）、带 git 的副本、跑 `plug` 子进程的小函数。
# 机器的测试只跑 example-tool，永远不碰真实内容仓库。
import os, shutil, subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "example-tool"
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def copy_example(dst):
    shutil.copytree(EXAMPLE, dst, ignore=shutil.ignore_patterns(".kb", ".claude", ".agents", "index.md", "数字.md"))
    return dst


@pytest.fixture
def repo(tmp_path):
    """example-tool 的临时副本，已建索引。返回 cfg。"""
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
    """带 git 历史的副本：全部内容一次提交。"""
    root = repo["root"]
    (root / ".gitignore").write_text(".kb/\n.claude/skills/\n.agents/skills/\n", encoding="utf-8")
    assert git(root, "init", "-q", "-b", "main").returncode == 0
    git(root, "config", "user.name", "t"), git(root, "config", "user.email", "t@example.com")
    assert git(root, "add", "-A").returncode == 0
    r = git(root, "commit", "-q", "-m", "init")
    assert r.returncode == 0, r.stderr
    return repo


def plug(root, *args, env=None, stdin=None):
    """跑 `python -m entryplug.cli --root <root> ...`，返回 CompletedProcess（stdout/stderr 为 utf-8 文本）。"""
    e = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    e.pop("KB_APPROVE", None) if not (env and "KB_APPROVE" in env) else None
    return subprocess.run([sys.executable, "-m", "entryplug.cli", "--root", str(root), *args], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", env=e, input=stdin)
