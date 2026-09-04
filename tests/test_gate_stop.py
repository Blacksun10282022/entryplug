# Gate stop (the record reminder): reminder level only. It nudges once when no record was written this session,
# stays quiet when one was, says nothing at all under .plug-off, and it always exits 0 — it never blocks.
import json, os, subprocess, sys
from conftest import ROOT

GATE = ROOT / "gates" / "stop.py"
RECORD = ("---\ntool: sunzi\nby: codex · gpt-5 · 2026-08-29\nsituation: s\nverdict: v\nchosen:\noutcome:\n---\n"
          "## 依据\nJ1 · 上次：无类似记录\n## 最强反证\nb\n## 什么会改判\nc\n")


def run(root, payload=None, env=None):
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PLUG_ROOT=str(root), **(env or {}))
    return subprocess.run([sys.executable, str(GATE)], cwd=str(root), env=e, capture_output=True, text=True,
                          encoding="utf-8", input=json.dumps(payload or {}, ensure_ascii=False))


def test_nudges_when_no_record_was_written_and_still_exits_zero(repo):
    r = run(repo["root"], {"hook_event_name": "Stop", "cwd": str(repo["root"])}, {"PLUG_RECORD_WINDOW": "0"})
    assert r.returncode == 0
    msg = json.loads(r.stdout)["systemMessage"]
    assert msg.startswith("entry plug · no record was written this session") and "self/records" in msg
    assert "reminder, not a gate" in msg
    assert (repo["hooks_dir"] / "stop").exists()


def test_quiet_when_a_record_was_written_this_session(repo):
    (repo["root"] / "self/records/2026-08-29-new.md").write_text(RECORD, encoding="utf-8")
    r = run(repo["root"], {"hook_event_name": "Stop", "cwd": str(repo["root"])}, {"PLUG_RECORD_WINDOW": "1"})
    assert r.returncode == 0 and r.stdout.strip() == ""
    assert (repo["hooks_dir"] / "stop").exists()


def test_plug_off_silences_it_completely(repo):
    (repo["root"] / ".plug-off").write_text("", encoding="utf-8")
    r = run(repo["root"], {"hook_event_name": "Stop", "cwd": str(repo["root"])}, {"PLUG_RECORD_WINDOW": "0"})
    assert r.returncode == 0 and r.stdout.strip() == "" and not (repo["hooks_dir"] / "stop").exists()


def test_no_config_and_bad_json_are_both_silent(repo, tmp_path):
    e = dict(os.environ, PYTHONIOENCODING="utf-8")
    e.pop("PLUG_ROOT", None)
    r = subprocess.run([sys.executable, str(GATE)], cwd=str(tmp_path), env=e, capture_output=True, text=True,
                       encoding="utf-8", input="{}")
    assert r.returncode == 0 and r.stdout.strip() == ""
    r = subprocess.run([sys.executable, str(GATE)], cwd=str(repo["root"]), env=dict(os.environ, PLUG_ROOT=str(repo["root"]),
                       PYTHONIOENCODING="utf-8", PLUG_RECORD_WINDOW="0"), capture_output=True, text=True,
                       encoding="utf-8", input="this is not json")
    assert r.returncode == 0 and "systemMessage" in r.stdout       # unreadable payload still falls back to the window


def test_second_stop_in_the_same_session_is_silent(repo, tmp_path):
    """D77: the reminder fires once per session (the transcript's start), not at the end of every turn."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    payload = {"hook_event_name": "Stop", "cwd": str(repo["root"]), "transcript_path": str(transcript)}
    first = run(repo["root"], payload)
    assert first.returncode == 0 and "no record was written" in json.loads(first.stdout)["systemMessage"]
    second = run(repo["root"], payload)
    assert second.returncode == 0 and second.stdout.strip() == ""

