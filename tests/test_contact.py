# First contact (plug check --contact): one line per step; with the hooks and deny installed everything is green;
# without deny (Claude Code) or without the hook that step FAILs; the result is appended to the numbers page.
import json, sys
from conftest import ROOT, plug

GATE = ROOT / "gates" / "precommit.py"


def install(root, deny=True):
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexec \"%s\" \"%s\"\n" % (sys.executable.replace("\\", "/"), str(GATE).replace("\\", "/")), encoding="utf-8")
    if deny:
        (root / ".claude").mkdir(exist_ok=True)
        rules = ["Edit(//c/x/self/RULES.md)", "Edit(//c/x/self/facts/**)", "Edit(//c/x/tools/**)", "Edit(//c/x/.kb/hooks/**)"]
        (root / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": rules}}), encoding="utf-8")


def test_contact_all_green_both_pilots(git_repo):
    root = git_repo["root"]
    install(root)
    for pilot in ("claude-code", "codex"):
        r = plug(root, "check", "--contact", pilot)
        assert r.returncode == 0, r.stdout + r.stderr
        lines = r.stdout.splitlines()
        assert lines[0].startswith("first contact · %s · harness " % pilot)
        assert [l[:1] for l in lines[1:5]] == ["①", "②", "③", "④"] and all(" OK " in l for l in lines[1:5])
        assert "Chinese query" in lines[2] and "hit" in lines[2]
        assert "denied (Bash · PowerShell · mcp" in lines[3], lines[3]      # D65: one deny, exit 0, the real tool names
        assert lines[-1] == "first contact, nothing wrong"
    assert "Codex has no permissions.deny" in r.stdout
    assert "first contact codex" in git_repo["numbers_path"].read_text(encoding="utf-8")


def test_contact_fails_without_deny_or_hook(git_repo):
    root = git_repo["root"]
    install(root, deny=False)
    r = plug(root, "check", "--contact", "claude-code")
    assert r.returncode == 1 and "④ protected write FAIL" in r.stdout and "the integration is broken" in r.stdout and "step 4" in r.stdout
    (root / ".git/hooks/pre-commit").unlink()
    r = plug(root, "check", "--contact", "codex")
    assert r.returncode == 1 and "no pre-commit hook installed" in r.stdout
def test_contact_without_a_dictionary_is_not_a_broken_integration(git_repo):
    """A content repo with no dict/ used to fail step 2 outright and be declared broken, while MCP was healthy.
    The probe now falls back to the index; with nothing indexed to probe with the hit count is simply not asserted."""
    import shutil
    from entryplug import config, contact
    root = git_repo["root"]
    install(root)
    shutil.rmtree(root / "tools/sunzi/dict")
    assert plug(root, "index").returncode == 0
    cfg = config.load(root)
    q, src = contact.probe_query(cfg)
    assert q and src == "index", (q, src)
    r = plug(root, "check", "--contact", "claude-code")
    lines = r.stdout.splitlines()
    assert " OK " in lines[2] and "(index)" in lines[2], lines[2]
    assert r.returncode == 0 and lines[-1] == "first contact, nothing wrong", r.stdout
    cfg["index_path"].unlink()
    assert contact.probe_query(cfg) == (None, None)      # no index either: still not a broken integration


def test_contact_step_four_does_not_claim_deny_is_in_force(git_repo):
    """deny rules live in the content repo's settings and bind only a session whose project root is that repo.
    A file check can prove they are written, never that they are in force, and step 4 must say so."""
    root = git_repo["root"]
    install(root)
    r = plug(root, "check", "--contact", "claude-code")
    step4 = r.stdout.splitlines()[4]
    assert "written, NOT proven in force" in step4 and "project root is this repo" in step4, step4
def test_contact_reports_a_real_block_on_both_pilots(git_repo):
    """The sortie lock blocks on both sides with one decision (D65): the deny JSON from a process that exits 0,
    probed with each pilot's real payload shape and with every shell tool. Step 3 says so, and on the Codex side it
    also prints the owner's approval_policy / sandbox_mode — the layer on top."""
    from entryplug import contact
    root = git_repo["root"]
    install(root)
    c = plug(root, "check", "--contact", "codex")
    step3 = c.stdout.splitlines()[3]
    assert "denied (Bash · PowerShell · mcp" in step3 and "exit 0" in step3, step3
    assert "only RECORDS" not in step3 and "cannot veto" not in step3, step3
    assert "approval_policy=" in step3 and "sandbox_mode=" in step3, step3
    k = plug(root, "check", "--contact", "claude-code")
    assert "the payload shape Claude Code sends" in k.stdout.splitlines()[3]
    posture = contact.codex_posture()
    assert "approval_policy=" in posture or "not found" in posture or "unreadable" in posture
