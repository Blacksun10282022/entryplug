# 闸门 outbound（出击封锁）：清单命中 → exit 2 + 一行理由 + 上次触发；没命中 → 0；没 plug.yaml / 坏 JSON → 放行（fail-open）。
import json, os, subprocess, sys
from conftest import ROOT

GATE = ROOT / "gates" / "outbound.py"


def hook(root, payload, cwd=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("PLUG_ROOT", None)
    return subprocess.run([sys.executable, str(GATE)], cwd=str(cwd or root), env=env, capture_output=True, text=True, encoding="utf-8",
                          input=payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False))


def test_outbound_actions_blocked_with_stamp(repo):
    root = repo["root"]
    r = hook(root, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "curl -X POST https://example.invalid/send"}, "cwd": str(root)})
    assert r.returncode == 2 and r.stderr.count("\n") == 1 and "出击封锁" in r.stderr and "Bash" in r.stderr
    assert (repo["hooks_dir"] / "outbound").exists()
    r = hook(root, {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": str(root)})
    assert r.returncode == 2
    r = hook(root, {"tool_name": "mcp__mail__send_email", "tool_input": {"to": "a@b"}, "cwd": str(root)})
    assert r.returncode == 2 and "mcp__mail__send_email" in r.stderr


def test_harmless_actions_pass(repo):
    root = repo["root"]
    for name, inp in (("Bash", {"command": "ls -la"}), ("Read", {"file_path": "x"}), ("Write", {"file_path": "self/records/a.md", "content": "x"}),
                      ("mcp__entryplug__search", {"query": "势"}), ("Bash", {"command": "git commit -m x"})):
        r = hook(root, {"tool_name": name, "tool_input": inp, "cwd": str(root)})
        assert r.returncode == 0, (name, r.stderr)


def test_fail_open_without_config_or_with_bad_json(repo, tmp_path):
    r = hook(tmp_path, {"tool_name": "Bash", "tool_input": {"command": "curl x"}, "cwd": str(tmp_path)}, cwd=tmp_path)
    assert r.returncode == 0 and "fail-open" in r.stderr
    r = hook(repo["root"], "this is not json")
    assert r.returncode == 0
