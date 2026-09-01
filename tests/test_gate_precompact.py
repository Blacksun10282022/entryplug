# Gate precompact (the compaction pin): five lines (where we are · record · equipment · pending proposals ·
# answer in) all read off files; writes .kb/pin.md + a stamp; --emit / SessionStart hands it back as
# additionalContext; .plug-off pins nothing.
import json, os, subprocess, sys
from conftest import ROOT

GATE = ROOT / "gates" / "precompact.py"


def run(root, payload=None, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PLUG_ROOT=str(root))
    return subprocess.run([sys.executable, str(GATE), *args], cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8",
                          input=json.dumps(payload, ensure_ascii=False) if payload is not None else "")


def test_pin_has_five_facts(repo):
    root = repo["root"]
    latest = root / "self/records/2026-08-27-choose-venue.md"
    os.utime(latest, None)
    r = run(root, {"hook_event_name": "PreCompact", "trigger": "auto", "cwd": str(root)})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "where we are: 下周的价格谈判" in out and "record: self/records/2026-08-27-choose-venue.md" in out
    assert "equipment: sunzi" in out and "pending proposals: 1" in out and "answer in: 中文" in out
    assert repo["pin_path"].read_text(encoding="utf-8").strip() == out.strip()
    assert (repo["hooks_dir"] / "precompact").exists()


def test_emit_returns_additional_context(repo):
    root = repo["root"]
    run(root, {"hook_event_name": "PreCompact", "cwd": str(root)})
    r = run(root, {"hook_event_name": "SessionStart", "source": "compact", "cwd": str(root)})
    j = json.loads(r.stdout)
    assert j["hookSpecificOutput"]["hookEventName"] == "SessionStart" and "answer in: 中文" in j["hookSpecificOutput"]["additionalContext"]
    r = run(root, None, "--emit")
    assert "additionalContext" in r.stdout


def test_no_records_still_pins(repo):
    root = repo["root"]
    for p in (root / "self/records").glob("*.md"):
        p.unlink()
    r = run(root, {"hook_event_name": "PreCompact", "cwd": str(root)})
    assert r.returncode == 0 and "(no records yet)" in r.stdout and "answer in" in r.stdout


def test_plug_off_pins_nothing(repo):
    root = repo["root"]
    (root / ".plug-off").write_text("", encoding="utf-8")
    r = run(root, {"hook_event_name": "PreCompact", "cwd": str(root)})
    assert r.returncode == 0 and r.stdout.strip() == "" and not repo["pin_path"].exists()
