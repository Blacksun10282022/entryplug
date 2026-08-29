# 闸门 precompact（压缩钉子）：五行（处境 · 记录路径 · 装备 · 待批提议 · 回复语言）从文件推出；写 .kb/pin.md + 上次触发；--emit / SessionStart 注回 additionalContext。
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
    assert "当前处境：下周的价格谈判" in out and "记录路径：self/records/2026-08-27-choose-venue.md" in out
    assert "当前装备：sunzi" in out and "待批提议：1 条" in out and "回复语言：中文" in out
    assert repo["pin_path"].read_text(encoding="utf-8").strip() == out.strip()
    assert (repo["hooks_dir"] / "precompact").exists()


def test_emit_returns_additional_context(repo):
    root = repo["root"]
    run(root, {"hook_event_name": "PreCompact", "cwd": str(root)})
    r = run(root, {"hook_event_name": "SessionStart", "source": "compact", "cwd": str(root)})
    j = json.loads(r.stdout)
    assert j["hookSpecificOutput"]["hookEventName"] == "SessionStart" and "回复语言：中文" in j["hookSpecificOutput"]["additionalContext"]
    r = run(root, None, "--emit")
    assert "additionalContext" in r.stdout


def test_no_records_still_pins(repo):
    root = repo["root"]
    for p in (root / "self/records").glob("*.md"):
        p.unlink()
    r = run(root, {"hook_event_name": "PreCompact", "cwd": str(root)})
    assert r.returncode == 0 and "（还没有记录）" in r.stdout and "回复语言" in r.stdout
