# Verb status: one line per real check against the example fixture, the sync-rate arithmetic, PATTERN ORANGE when
# a layer is down, ALL SYSTEMS NOMINAL once plug init has run, and a nonzero exit only when the index is unusable.
import json
from entryplug import status
from conftest import plug


def test_panel_on_the_bare_example_fixture(repo):
    text, code = status.panel(repo)
    lines = text.splitlines()
    assert lines[0] == "ENTRY PLUG — INSERTION SEQUENCE" and code == 0        # the index is fine, so exit stays 0
    assert lines[1].startswith("[OK] LCL pressure") and "index.sqlite" in lines[1] and "docs," in lines[1]
    assert lines[2].startswith("[OK] A10 nerve link") and "RULES " in lines[2] and "records " in lines[2]
    assert lines[3].startswith("[NG] AT-Field") and "pre-commit NOT installed" in lines[3]   # nothing installed yet
    assert "Berserk lock" in lines[4] and "Sortie lock" in lines[4]
    assert lines[5].startswith("[OK] Equipment bay") and "1 registered (sunzi)" in lines[5] and "1 pending" in lines[5]
    assert lines[6].startswith("[--] plug-off") and "not present" in lines[6]
    assert lines[-1].startswith("SYNC RATE ") and "PATTERN ORANGE" in lines[-1] and "run plug init" in lines[-1]


def test_all_systems_nominal_after_init(git_repo):
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "both").returncode == 0
    assert plug(root, "index").returncode == 0
    r = plug(root, "status")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert all(l.startswith("[OK]") for l in lines[1:6]), lines
    assert "deny armed" in lines[3] and "pre-commit armed" in lines[3]
    assert lines[-1].startswith("SYNC RATE 100.0% — ALL SYSTEMS NOMINAL.") and lines[-1].endswith("LIFT OFF.")


def test_plug_off_is_reported_and_a_dead_index_exits_nonzero(repo):
    (repo["root"] / ".plug-off").write_text("", encoding="utf-8")
    text, code = status.panel(repo)
    assert code == 0 and "[--] plug-off" in text and "present" in text.splitlines()[6]
    repo["index_path"].unlink()
    text, code = status.panel(repo)
    assert code == 1 and text.splitlines()[1].startswith("[NG] LCL pressure")
    assert "PATTERN ORANGE" in text and "the index layer" in text and "run plug index" in text.splitlines()[-1]


def test_kb_approve_in_the_environment_disarms_the_berserk_lock(repo, monkeypatch):
    monkeypatch.setenv("KB_APPROVE", "1")
    text, _ = status.panel(repo)
    assert "DISARMED (KB_APPROVE=1" in text and "the berserk lock" in text.splitlines()[-1]


def test_emit_wraps_the_panel_for_session_start(repo):
    r = plug(repo["root"], "status", "--emit")
    assert r.returncode == 0, r.stdout + r.stderr
    j = json.loads(r.stdout)
    assert j["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "INSERTION SEQUENCE" in j["hookSpecificOutput"]["additionalContext"]
