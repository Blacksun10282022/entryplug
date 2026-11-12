# Verb status: one line per real check against the example fixture, the sync-rate arithmetic, PATTERN ORANGE when
# a layer is down, ALL SYSTEMS NOMINAL once plug init has run, and a nonzero exit only when the index is unusable.
import json
from entryplug import status
from conftest import plug, trust_codex


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
    env = trust_codex(root, root.parent / "codexhome")     # untrusted Codex hooks are skipped, so the lock is not armed
    r = plug(root, "status", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert all(l.startswith("[OK]") for l in lines[1:6]), lines
    assert "deny written" in lines[3] and "pre-commit armed" in lines[3]     # written, never "in force": D49
    assert lines[-1].startswith("SYNC RATE 100.0% — ALL SYSTEMS NOMINAL.") and lines[-1].endswith("LIFT OFF.")


def test_plug_off_is_reported_and_a_dead_index_exits_nonzero(repo):
    (repo["root"] / ".plug-off").write_text("", encoding="utf-8")
    text, code = status.panel(repo)
    assert code == 0 and "[--] plug-off" in text and "present" in text.splitlines()[6]
    repo["index_path"].unlink()
    text, code = status.panel(repo)
    assert code == 1 and text.splitlines()[1].startswith("[NG] LCL pressure")
    assert "PATTERN ORANGE" in text and "the index layer" in text and "run plug index" in text.splitlines()[-1]


def test_a_stale_index_is_ng_with_how_far_but_exits_zero(repo):
    """D83: a content repo's index sat two days behind — the read-only MCP search could not see the newest records —
    while this panel said ALL SYSTEMS NOMINAL. Behind is now [NG] with how far; still searchable, so exit stays 0."""
    from entryplug import index
    p = repo["root"] / "tools/sunzi/dict/shi.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n未进索引的改动\n", encoding="utf-8", newline="\n")
    text, code = status.panel(repo)
    line = text.splitlines()[1]
    assert code == 0 and line.startswith("[NG] LCL pressure") and "docs," in line, line
    assert "STALE: 1 file(s) newer than the index built " in line and "MCP search reads it as is" in line, line
    assert "the index layer" in text.splitlines()[-1] and "run plug index" in text.splitlines()[-1]
    assert "[NG] LCL pressure" in status.brief(text)            # the pilot's one boot line carries it too (D74)
    index.build(repo)
    text, code = status.panel(repo)
    assert code == 0 and text.splitlines()[1].startswith("[OK] LCL pressure") and "STALE" not in text


def test_kb_approve_in_the_environment_disarms_the_berserk_lock(repo, monkeypatch):
    monkeypatch.setenv("KB_APPROVE", "1")
    text, _ = status.panel(repo)
    assert "DISARMED (KB_APPROVE=1" in text and "the berserk lock" in text.splitlines()[-1]


def test_emit_wraps_the_panel_for_session_start(repo):
    """D74: the whole panel goes to the owner's screen as systemMessage; the pilot's context gets one verdict line."""
    r = plug(repo["root"], "status", "--emit")
    d = json.loads(r.stdout)
    assert d["systemMessage"].startswith("ENTRY PLUG") and "SYNC RATE" in d["systemMessage"]
    ctx = d["hookSpecificOutput"]["additionalContext"]
    assert d["hookSpecificOutput"]["hookEventName"] == "SessionStart" and ctx.startswith("entry plug boot: SYNC RATE")
    assert ctx.count("\n") == 0 and "[OK]" not in ctx


def test_emit_never_exits_nonzero_even_when_the_panel_breaks(repo, monkeypatch):
    """--emit feeds a SessionStart hook: a degraded layer belongs in the panel as [NG], and a panel that throws
    should say so in one line rather than end the session with a nonzero exit (D54)."""
    repo["index_path"].unlink()                       # index layer dead: plain status exits 1 ...
    assert status.run(repo, emit=False) == 1
    assert status.run(repo, emit=True) == 0           # ... but --emit still exits 0
    def boom(cfg):
        raise RuntimeError("panel exploded")
    monkeypatch.setattr(status, "panel", boom)
    assert status.run(repo, emit=True) == 0           # even a crashing panel must not take the session down


def test_emit_payload_is_session_start_context(repo, capsys):
    status.run(repo, emit=True)
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "INSERTION SEQUENCE" in out["systemMessage"]                                   # the owner's screen (D74)
    assert out["hookSpecificOutput"]["additionalContext"].startswith("entry plug boot: ")   # the pilot's one line


def test_a_stub_pre_commit_hook_is_not_reported_armed(git_repo):
    """The old check was `"precommit" in text`: a hook replaced by `# precommit disabled` + `exit 0` still read as
    armed on the boot panel (D68). The real hook has exactly one executable line, exec'ing gates/precommit.py."""
    root = git_repo["root"]
    assert plug(root, "init", "--pilot", "both").returncode == 0
    hook = root / ".git/hooks/pre-commit"
    real = hook.read_text(encoding="utf-8")
    hook.write_text("#!/bin/sh\n# precommit disabled\nexit 0\n", encoding="utf-8")
    text, _ = status.panel(git_repo)
    assert "pre-commit is NOT the plug init hook" in text and "[NG] Berserk lock" in text, text
    hook.write_text(real, encoding="utf-8")
    text, _ = status.panel(git_repo)
    assert "pre-commit armed" in text and "[OK] Berserk lock" in text, text


def test_emit_tells_the_pilot_the_panel_is_not_for_the_owner(repo):
    """Blind test 2026-09-03: both pilots pasted the boot panel and hook status into answers for the owner (D73)."""
    r = plug(repo["root"], "status", "--emit")
    d = json.loads(r.stdout)
    ctx = d["hookSpecificOutput"]["additionalContext"]
    assert ctx.rstrip().endswith(status.PILOT_ONLY) and "never paste" in ctx
    assert status.PILOT_ONLY not in d["systemMessage"] and status.PILOT_ONLY not in plug(repo["root"], "status").stdout


def test_emit_context_keeps_every_ng_line(repo):
    """A degraded layer must still reach the pilot in the one-line context (D74)."""
    text = "ENTRY PLUG — INSERTION SEQUENCE\n[OK] a ... fine\n[NG] b ... broken\n[NG] c ... also broken\nSYNC RATE 50.0% — PATTERN ORANGE"
    b = status.brief(text)
    assert b.startswith("entry plug boot: SYNC RATE 50.0%") and b.count("[NG]") == 2 and "[OK]" not in b and b.endswith(status.PILOT_ONLY)


# The bare example panel exactly as it read before D86 (only the measured milliseconds vary).
BARE = ["ENTRY PLUG — INSERTION SEQUENCE",
        "[OK] LCL pressure ....... index.sqlite (38 docs, <ms>)",
        "[OK] A10 nerve link ..... self/ (RULES 8 · style · facts 1 · records 3)",
        "[NG] AT-Field ........... deny MISSING · pre-commit NOT installed",
        "[NG] Berserk lock ....... no pre-commit hook [NG] Sortie lock ... hook not wired",
        "[OK] Equipment bay ...... 1 registered (sunzi) · 1 pending",
        "[--] plug-off ........... not present",
        "SYNC RATE 50.0% — PATTERN ORANGE: the AT-Field · the berserk lock · the sortie lock degraded; run plug init --pilot both"]
OLD, SETTLED, NEW = ("self/records/2026-07-20-supplier-delay.md", "self/records/2026-08-21-counterpart-feigns-weakness.md",
                     "self/records/2026-08-27-choose-venue.md")


def put_due(cfg, rel, day):
    p = cfg["root"] / rel
    p.write_text(p.read_text(encoding="utf-8").replace("\noutcome:", "\ndue: %s\noutcome:" % day, 1), encoding="utf-8")
    from entryplug import index
    index.build(cfg)                                  # keep the LCL line [OK]: only the due line may differ


def lines_of(cfg):
    import re
    return [re.sub(r"\d+ms\)", "<ms>)", l) for l in status.panel(cfg)[0].splitlines()]


def test_the_due_line_appears_only_when_a_record_is_due(repo, monkeypatch):
    """D86: a dated prediction passed its day by eleven days and neither the boot panel nor plug check said so.
    A record whose due day has come with no outcome adds one [--] line, not counted; otherwise the panel is the
    same, byte for byte, as before."""
    from datetime import date, timedelta
    monkeypatch.delenv("KB_APPROVE", raising=False)
    today = date.today()
    assert lines_of(repo) == BARE
    put_due(repo, NEW, today + timedelta(days=5))                   # not yet due
    put_due(repo, SETTLED, today - timedelta(days=30))               # due long ago, but settled
    assert lines_of(repo) == BARE
    put_due(repo, OLD, today - timedelta(days=11))
    line = "[--] Records due ........ 1 due, no outcome yet: 2026-07-20-supplier-delay (due %s) — settle it by filling outcome" % (
        today - timedelta(days=11))
    assert lines_of(repo) == BARE[:7] + [line] + BARE[7:]             # same verdict, same sync rate, same exit
    assert status.panel(repo)[1] == 0


def test_the_brief_carries_the_due_line_and_plug_off_silences_it(repo, monkeypatch):
    from datetime import date, timedelta
    monkeypatch.delenv("KB_APPROVE", raising=False)
    today = date.today()
    put_due(repo, OLD, today)
    put_due(repo, NEW, '"%s"' % (today - timedelta(days=3)))
    text = status.panel(repo)[0]
    due = "[--] Records due ........ 2 due, no outcome yet: oldest 2026-08-27-choose-venue (due %s), and 1 more — settle them by filling outcome" % (
        today - timedelta(days=3))
    assert due in text.splitlines()
    b = status.brief(text)
    assert b.startswith("entry plug boot: SYNC RATE 50.0%") and due in b and b.endswith(status.PILOT_ONLY) and "\n" not in b
    assert "[--] plug-off" not in b                                    # only the due line joins the [NG] lines
    (repo["root"] / ".plug-off").write_text("", encoding="utf-8")
    text = status.panel(repo)[0]
    assert "Records due" not in text and "Records due" not in status.brief(text)


def test_plug_status_reports_a_due_record_and_writes_nothing(repo):
    from datetime import date
    put_due(repo, OLD, date.today())
    root = repo["root"]
    def tree():
        return {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*")}
    before = tree()
    r = plug(root, "status")
    assert "[--] Records due ........ 1 due, no outcome yet: 2026-07-20-supplier-delay" in r.stdout, r.stdout
    assert tree() == before
