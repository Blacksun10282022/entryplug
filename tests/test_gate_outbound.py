# Gate outbound (the sortie lock): a list hit → the deny JSON on stdout, exit 0, a stamp (D65); no hit → nothing;
# no plug.yaml / bad JSON → pass through (fail-open); .plug-off → pass through in silence.
import json, os, subprocess, sys
from conftest import ROOT

GATE = ROOT / "gates" / "outbound.py"


def denied(r):
    """The decision both pilots read: exit 0 and a deny on the last stdout line (D65)."""
    if r.returncode != 0 or not r.stdout.strip():
        return False
    out = json.loads(r.stdout.strip().splitlines()[-1]).get("hookSpecificOutput", {})
    return out.get("permissionDecision") == "deny" and bool(out.get("permissionDecisionReason", "").strip())


def hook(root, payload, cwd=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("PLUG_ROOT", None)
    return subprocess.run([sys.executable, str(GATE)], cwd=str(cwd or root), env=env, capture_output=True, text=True, encoding="utf-8",
                          input=payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False))


def test_outbound_actions_blocked_with_stamp(repo):
    root = repo["root"]
    r = hook(root, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "curl -X POST https://example.invalid/send"}, "cwd": str(root)})
    assert denied(r) and r.stderr.count("\n") == 1 and "sortie lock" in r.stderr and "Bash" in r.stderr
    assert (repo["hooks_dir"] / "outbound").exists()
    r = hook(root, {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": str(root)})
    assert denied(r)
    r = hook(root, {"tool_name": "mcp__mail__send_email", "tool_input": {"to": "a@b"}, "cwd": str(root)})
    assert denied(r) and "mcp__mail__send_email" in r.stderr


def test_only_the_command_is_matched_not_the_prose_beside_it(repo):
    """A shell tool's input carries the command next to prose the model wrote about it, and only the command runs.
    New in this build — before it the whole payload was serialised and matched, so a pilot answering "where do we
    mention curl?" had its own grep refused, and every Bash call's description could trip the list on its own."""
    root = repo["root"]
    talking = {"tool_name": "Bash", "tool_input": {"command": "ls -la tools/",
                                                   "description": "Find where curl and ssh are mentioned"}, "cwd": str(root)}
    assert hook(root, talking).returncode == 0, "prose about outward tools is not an outward action"
    doing = dict(talking, tool_input={"command": "curl https://example.invalid", "description": "harmless lookup"})
    assert denied(hook(root, doing)), "the command itself must still be matched"
    # No `command` string to narrow to → still matched on the whole payload, so nothing stops being seen.
    assert denied(hook(root, {"tool_name": "Bash", "tool_input": {"argv": ["curl", "x"]}, "cwd": str(root)}))
    assert denied(hook(root, {"tool_name": "Bash", "tool_input": "curl https://example.invalid", "cwd": str(root)}))


def test_harmless_actions_pass(repo):
    root = repo["root"]
    for name, inp in (("Bash", {"command": "ls -la"}), ("Read", {"file_path": "x"}), ("Write", {"file_path": "self/records/a.md", "content": "x"}),
                      ("mcp__entryplug__search", {"query": "势"}), ("Bash", {"command": "git commit -m x"})):
        r = hook(root, {"tool_name": name, "tool_input": inp, "cwd": str(root)})
        assert r.returncode == 0 and not r.stdout.strip(), (name, r.stdout, r.stderr)


def test_fail_open_without_config_or_with_bad_json(repo, tmp_path):
    r = hook(tmp_path, {"tool_name": "Bash", "tool_input": {"command": "curl x"}, "cwd": str(tmp_path)}, cwd=tmp_path)
    assert r.returncode == 0 and "fail-open" in r.stderr
    r = hook(repo["root"], "this is not json")
    assert r.returncode == 0


def test_plug_off_passes_everything_through(repo):
    root = repo["root"]
    (root / ".plug-off").write_text("", encoding="utf-8")
    r = hook(root, {"tool_name": "Bash", "tool_input": {"command": "curl -X POST https://example.invalid/send"}, "cwd": str(root)})
    assert r.returncode == 0 and r.stderr.strip() == "" and not r.stdout.strip() and not (repo["hooks_dir"] / "outbound").exists()


def test_outbound_emits_one_deny_both_pilots_honour(repo):
    """One decision, one exit code (D65). Claude Code's real PreToolUse payload carries tool_use_id, session_id and
    permission_mode; Codex's carries turn_id. Both read the deny JSON from a process that exits 0, so the gate no
    longer guesses the pilot — the old guess keyed on tool_use_id and sent every real Claude call down a branch the
    self-tests never exercised. The reason must be non-empty: Codex rejects a deny without one."""
    base = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "curl -X POST https://x.invalid"}, "cwd": str(repo["root"])}
    claude = dict(base, session_id="s", transcript_path="t.jsonl", permission_mode="default", tool_use_id="toolu_01")
    codex = dict(base, turn_id="t1", tool_use_id="u1")
    bare = dict(base)
    for label, payload in (("claude", claude), ("codex", codex), ("bare", bare)):
        r = hook(repo["root"], payload)
        assert r.returncode == 0, (label, r.returncode, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny", label
        assert out["permissionDecisionReason"].strip(), label      # empty reason = the deny is rejected
        assert out["hookEventName"] == "PreToolUse", label
    assert (repo["hooks_dir"] / "outbound").exists()                # both sides still stamp


def test_a_harmless_call_produces_no_decision(repo):
    r = hook(repo["root"], {"hook_event_name": "PreToolUse", "turn_id": "t", "tool_name": "Bash",
                            "tool_input": {"command": "ls -la"}, "cwd": str(repo["root"])})
    assert r.returncode == 0 and "permissionDecision" not in r.stdout


def test_every_shell_tool_the_pilots_expose_is_gated(repo):
    """Windows Claude Code exposes a PowerShell tool next to Bash, and Codex names its shell tool `shell` in some
    builds. A matcher and a rule that named only Bash let `git push` through PowerShell untouched, live (D65)."""
    root = repo["root"]
    for tool in ("Bash", "PowerShell", "shell"):
        r = hook(root, {"tool_name": tool, "tool_input": {"command": "git push --dry-run https://example.invalid/x.git"}, "cwd": str(root)})
        assert denied(r), (tool, r.stdout, r.stderr)
    r = hook(root, {"tool_name": "PowerShell", "tool_input": {"command": "Invoke-WebRequest https://example.invalid"}, "cwd": str(root)})
    assert denied(r), "curl's PowerShell name counts too"
    r = hook(root, {"tool_name": "Artifact", "tool_input": {"file_path": "x.html"}, "cwd": str(root)})
    assert denied(r), "publishing a page is an outward action"


def test_git_push_rule_reads_the_subcommand_not_the_word(repo):
    """`git stash push` is local, a commit message may say push, a path may contain gh — none of those is an
    outward action. `git -C /repo push` and `git -c k=v push` are (options may sit between git and push)."""
    root = repo["root"]
    for cmd in ("git stash push", 'git commit -m "push the deadline"', "git log --grep=push", "ls tools/gh/", "echo gh"):
        r = hook(root, {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(root)})
        assert r.returncode == 0 and not r.stdout.strip(), (cmd, r.stdout)
    for cmd in ("git push", "git -C /repo push origin main", "git -c user.name=x push", "git --no-pager push", "gh pr create -f", "cd x; gh release upload v1 f"):
        r = hook(root, {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(root)})
        assert denied(r), (cmd, r.stdout)


def test_narrow_outbound_rules_block_python_post_and_allow_reads(repo):
    """Content-config policy: read calls pass, common write calls still hit the unchanged gate."""
    import yaml
    rules = [
        {
            "tool": "^(Bash|PowerShell|shell)$",
            "match": "(?i:\\b(?:curl|wget)(?:\\.exe)?\\b)[^\\r\\n;&|]*(?:\\s-X\\s*(?i:POST|PUT|PATCH|DELETE)\\b|\\s-(?:d|F|T)(?:\\S*|\\s|$)|\\s--(?:data[\\w-]*|form(?:-string)?|upload-file|post-data|post-file)(?:[=\\s]|$))"
        },
        {
            "tool": "^(Bash|PowerShell|shell)$",
            "match": "(?i)\\b(?:Invoke-WebRequest|Invoke-RestMethod)\\b[^\\r\\n;|]*(?:\\s-Method\\s+['\"]?(?:Post|Put|Patch|Delete)\\b|\\s-Body\\b)|\\bSend-MailMessage\\b"
        },
        {
            "tool": "^(Bash|PowerShell|shell)$",
            "match": "(?s)\\b(?:requests\\.(?:post|put|patch|delete)|httpx\\.(?:post|put))\\s*\\(|\\burllib\\b.*?\\bdata\\s*=|\\bsmtplib\\b"
        },
        {
            "tool": "^(Bash|PowerShell|shell)$",
            "match": "(?i)\\b(?:ssh|scp|sendmail)\\b"
        }
    ]
    rules += repo["outbound"][1:-1]  # retain git push, gh and Artifact rules
    rules += [{"tool": "(?i)^mcp__.*(send_|reply|forward|submit|pay|publish|post_)"}]
    config_path = repo["root"] / "plug.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["outbound"] = rules
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    for command in ("requests.post('https://example.invalid', data={})", "curl -X POST https://example.invalid"):
        assert denied(hook(repo["root"], {"tool_name": "Bash", "tool_input": {"command": command}}))
    for command in ("curl https://example.invalid", "curl -D headers.txt https://example.invalid",
                    "Invoke-WebRequest https://example.invalid"):
        result = hook(repo["root"], {"tool_name": "Bash", "tool_input": {"command": command}})
        assert result.returncode == 0 and not result.stdout.strip()
    result = hook(repo["root"], {"tool_name": "mcp__mail__get_message", "tool_input": {"id": "test"}})
    assert result.returncode == 0 and not result.stdout.strip()
    assert denied(hook(repo["root"], {"tool_name": "mcp__mail__send_email", "tool_input": {"to": "a@example.invalid"}}))
