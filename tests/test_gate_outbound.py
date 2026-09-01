# Gate outbound (the sortie lock): a list hit → exit 2 + one line of reason + a stamp; no hit → 0;
# no plug.yaml / bad JSON → pass through (fail-open); .plug-off → pass through in silence.
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
    assert r.returncode == 2 and r.stderr.count("\n") == 1 and "sortie lock" in r.stderr and "Bash" in r.stderr
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


def test_plug_off_passes_everything_through(repo):
    root = repo["root"]
    (root / ".plug-off").write_text("", encoding="utf-8")
    r = hook(root, {"tool_name": "Bash", "tool_input": {"command": "curl -X POST https://example.invalid/send"}, "cwd": str(root)})
    assert r.returncode == 0 and r.stderr.strip() == "" and not (repo["hooks_dir"] / "outbound").exists()
