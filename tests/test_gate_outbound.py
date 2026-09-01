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


def test_only_the_command_is_matched_not_the_prose_beside_it(repo):
    """A shell tool's input carries the command next to prose the model wrote about it, and only the command runs.
    New in this build — before it the whole payload was serialised and matched, so a pilot answering "where do we
    mention curl?" had its own grep refused, and every Bash call's description could trip the list on its own."""
    root = repo["root"]
    talking = {"tool_name": "Bash", "tool_input": {"command": "ls -la tools/",
                                                   "description": "Find where curl and ssh are mentioned"}, "cwd": str(root)}
    assert hook(root, talking).returncode == 0, "prose about outward tools is not an outward action"
    doing = dict(talking, tool_input={"command": "curl https://example.invalid", "description": "harmless lookup"})
    assert hook(root, doing).returncode == 2, "the command itself must still be matched"
    # No `command` string to narrow to → still matched on the whole payload, so nothing stops being seen.
    assert hook(root, {"tool_name": "Bash", "tool_input": {"argv": ["curl", "x"]}, "cwd": str(root)}).returncode == 2
    assert hook(root, {"tool_name": "Bash", "tool_input": "curl https://example.invalid", "cwd": str(root)}).returncode == 2


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
def test_outbound_emits_a_deny_both_pilots_honour(repo):
    """One decision, two exit codes (D56). The deny JSON must always carry a non-empty reason — Codex rejects a
    deny without one — and the exit code follows the payload: Codex (turn_id present) needs 0, Claude needs 2.
    Getting that backwards is silent: a hook that exits 2 has its stdout ignored by Codex, so the call goes through."""
    claude = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
              "tool_input": {"command": "curl -X POST https://x.invalid"}, "cwd": str(repo["root"])}
    codex = dict(claude, turn_id="t1", tool_use_id="u1")
    for label, payload, want_code in (("claude", claude, 2), ("codex", codex, 0)):
        r = hook(repo["root"], payload)
        assert r.returncode == want_code, (label, r.returncode, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny", label
        assert out["permissionDecisionReason"].strip(), label      # empty reason = the deny is rejected
        assert out["hookEventName"] == "PreToolUse", label
    assert (repo["hooks_dir"] / "outbound").exists()                # both sides still stamp


def test_a_harmless_call_produces_no_decision(repo):
    r = hook(repo["root"], {"hook_event_name": "PreToolUse", "turn_id": "t", "tool_name": "Bash",
                            "tool_input": {"command": "ls -la"}, "cwd": str(repo["root"])})
    assert r.returncode == 0 and "permissionDecision" not in r.stdout
