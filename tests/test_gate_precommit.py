# Gate precommit (the berserk lock): a protected path without KB_APPROVE is refused · records / proposals / corpus
# pass · a check ERROR is refused · the real git hook blocks too · it leaves a last-fired stamp.
# .plug-off does NOT relax this gate, and neither work/ nor an unregistered tools/ directory is protected.
import os, subprocess, sys
from conftest import ROOT, git

GATE = ROOT / "gates" / "precommit.py"


def run_gate(root, staged, approve=False):
    env = {k: v for k, v in os.environ.items() if k != "KB_APPROVE"}
    env.update(PLUG_ROOT=str(root), PLUG_STAGED="\n".join(staged), PYTHONIOENCODING="utf-8")
    if approve:
        env["KB_APPROVE"] = "1"
    return subprocess.run([sys.executable, str(GATE)], cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8")


def test_protected_paths_refused_one_line_reason(repo):
    root = repo["root"]
    for path in ("self/RULES.md", "self/facts/example.md", "tools/sunzi/dict/shi.md", "tools/sunzi/SKILL.md", "tools/sunzi/materials/x.md"):
        r = run_gate(root, [path])
        assert r.returncode == 1 and r.stderr.count("\n") == 1 and "berserk lock" in r.stderr and path in r.stderr, (path, r.stderr)
    assert (repo["hooks_dir"] / "precommit").exists()


def test_free_paths_pass_and_approve_unlocks(repo):
    root = repo["root"]
    for path in ("self/records/2026-08-29-x.md", "proposals/pending/2026-08-29-y.md", "tools/sunzi/corpus/raw/new.md", "README.md"):
        r = run_gate(root, [path])
        assert r.returncode == 0, (path, r.stderr)
    r = run_gate(root, ["self/RULES.md", "self/records/a.md"], approve=True)
    assert r.returncode == 0, r.stderr
    assert (root / "index.md").exists()


def test_check_error_blocks_commit(repo):
    p = repo["root"] / "tools/sunzi/dict/shi.md"
    p.write_text(p.read_text(encoding="utf-8").replace("势也\")", "力也\")", 1), encoding="utf-8")
    r = run_gate(repo["root"], ["self/records/a.md"])
    assert r.returncode == 1 and "check found" in r.stderr and "anchor" in r.stderr


def test_real_git_hook_blocks_direct_write_but_allows_records(git_repo):
    root = git_repo["root"]
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexec \"%s\" \"%s\"\n" % (sys.executable.replace("\\", "/"), str(GATE).replace("\\", "/")), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "KB_APPROVE"}
    rules = root / "self/RULES.md"
    rules.write_text(rules.read_text(encoding="utf-8") + "- J9 · 用 python -c 直写的一行 [2026-08]\n", encoding="utf-8")
    g = lambda *a, **k: subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=str(root), capture_output=True, text=True, encoding="utf-8", env=k.get("env", env))
    g("add", "self/RULES.md")
    r = g("commit", "-q", "-m", "sneak")
    assert r.returncode != 0 and "berserk lock" in r.stderr
    g("reset", "-q", "HEAD", "self/RULES.md"), g("checkout", "--", "self/RULES.md")
    rec = root / "self/records/2026-08-29-new.md"
    rec.write_text("---\ntool: sunzi\nby: codex · gpt-5 · 2026-08-29\nsituation: s\nverdict: v\nchosen:\noutcome:\n---\n## 依据\nJ1\n## 最强反证\nb\n## 什么会改判\nc\n", encoding="utf-8")
    g("add", "self/records")
    r = g("commit", "-q", "-m", "record")
    assert r.returncode == 0, r.stderr
    assert "record" in g("log", "-1", "--format=%s").stdout


def test_plug_off_does_not_relax_the_berserk_lock(repo):
    (repo["root"] / ".plug-off").write_text("", encoding="utf-8")
    r = run_gate(repo["root"], ["self/RULES.md"])
    assert r.returncode == 1 and "berserk lock" in r.stderr


def test_free_zones_and_unregistered_equipment_are_not_protected(repo):
    for path in ("work/sunzi/brief.md", "workshop/newtool/SKILL.md", "tools/unregistered/dict/x.md"):
        r = run_gate(repo["root"], [path])
        assert r.returncode == 0, (path, r.stderr)
def test_protect_list_extends_the_gate(repo):
    y = repo["root"] / "plug.yaml"
    y.write_text(y.read_text(encoding="utf-8") + chr(10) + 'protect:' + chr(10) + '  - "tools/sunzi/kit/**"' + chr(10),
                 encoding="utf-8")
    r = run_gate(repo["root"], ["tools/sunzi/kit/resume.md"])
    assert r.returncode == 1 and "berserk lock" in r.stderr
    assert run_gate(repo["root"], ["work/sunzi/kit/resume.md"]).returncode == 0
