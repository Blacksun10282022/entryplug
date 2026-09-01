# What: `plug check --contact claude-code|codex` — first contact (the integration smoke test), four steps, one
#       line each, stamped with the harness version: ① the manual is visible in the skills directory and its
#       description is not truncated (<=1,536); ② MCP search answers, and a real query is non-zero whenever the
#       repo has something to probe with; ③ a fake outbound action is blocked by the sortie-lock hook and leaves a
#       "last fired" stamp; ④ a fake write to a protected path is refused by pre-commit (both pilots, really run)
#       while deny is checked for presence only — deny binds a session whose project root is this repo, which no
#       file check can prove.
# In:   cfg · pilot name.
# Out:  four lines + a verdict ("first contact, nothing wrong" or "the integration is broken, do not use (step N)");
#       the result is appended to the numbers page; exit code 0 / 1.
# Not:  never starts Claude Code / Codex itself (whether deny really blocks is a MANUAL item in the acceptance
#       script); never edits content; never gives a score.
# Who:  cli (plug check --contact) · tests/acceptance.py (C4). Run it the day you upgrade Claude Code or Codex.
# Note: step ② really spawns a `plug mcp` subprocess and speaks JSON-RPC; steps ③④ really run the scripts in
#       gates/ (no gates/ = the machine was not installed from the repo, which is a FAIL). Any failing step means
#       the integration is broken: after a harness upgrade the product surface changes and integrations break
#       silently. This is the minute-long quick check; the acceptance script is the slow full round.
# Deps: stdlib subprocess · json; search (to pick a real title as the query).
import json, os, re, subprocess, sys, time
from pathlib import Path
from . import __version__, config

GATES = Path(__file__).resolve().parents[1] / "gates"
DENY_FILES = (".claude/settings.json", ".claude/settings.local.json")


def harness_version(pilot):
    cmd = {"claude-code": ["claude", "--version"], "codex": ["codex", "--version"]}[pilot]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20, shell=(os.name == "nt"))
        out = (r.stdout or r.stderr).strip()
        return out.splitlines()[0][:48] if out else "version unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "not installed or not on PATH"


def _run(args, cwd, env=None, stdin=None):
    return subprocess.run(args, cwd=str(cwd), env=dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {})), input=stdin,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)


def step_skills(cfg, pilot):
    d = cfg["pilots"].get(pilot, {}).get("skills")
    if not d:
        return False, "plug.yaml gives %s no skills directory" % pilot
    bad = []
    for t in cfg["tools"]:
        src, dst = t["dir"] / "SKILL.md", cfg["root"] / d / t["name"] / "SKILL.md"
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            bad.append("%s is not mirrored or is out of date (run plug index)" % t["name"])
            continue
        m = re.search(r"^description:\s*(.+)$", src.read_text(encoding="utf-8"), re.M)
        if not m or len(m.group(1)) > 1536:
            bad.append("%s description missing or >1,536 chars, it will be truncated in the list" % t["name"])
    return (not bad), ("%d manual(s) visible in %s, description not truncated" % (len(cfg["tools"]), d) if not bad else "; ".join(bad))


def probe_query(cfg):
    """(query, where it came from). A dictionary title when the repo has one — byte-for-byte the old behaviour for
    a repo that does — otherwise a real fragment lifted out of the index itself, which is guaranteed to be findable
    because it is the very text that was indexed. (None, None) when there is nothing to probe with: that is a repo
    without a dictionary, not a broken integration, and it must not be reported as one."""
    for t in cfg["tools"]:
        for p in sorted((t["dir"] / "dict").glob("*.md")):
            m = re.search(r"^title:\s*(.+)$", p.read_text(encoding="utf-8"), re.M)
            if m and re.search(r"[一-鿿]", m.group(1)):
                return m.group(1).strip(), "dict"
    from . import search
    try:
        con = search.open_ro(cfg)
        rows = con.execute("select excerpt from fts where scope='tools' limit 60").fetchall() \
            or con.execute("select excerpt from fts limit 60").fetchall()
        con.close()
    except Exception:
        return None, None
    for (ex,) in rows:
        w = re.findall(r"[一-鿿]{2,4}", ex or "")
        if w:
            return w[0], "index"
    return None, None


def step_mcp(cfg):
    q, src = probe_query(cfg)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "search", "arguments": {"query": q or "entryplug", "scope": "all", "k": 3}}}]
    try:
        r = _run([sys.executable, "-m", "entryplug.cli", "--root", str(cfg["root"]), "mcp"], GATES.parent, stdin="".join(json.dumps(m) + "\n" for m in msgs))
        lines = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        text = lines[1]["result"]["content"][0]["text"]
        n = int(re.search(r"showing (\d+)/(\d+)", text).group(2))
    except Exception as e:                                   # any exception = it does not answer
        return False, "MCP search does not answer: %s" % e
    if q is None:                    # nothing to probe with: MCP answered, and that is what this step is for
        return True, "MCP search answers; no dictionary and nothing indexed to probe with, so the hit count is not asserted"
    return n > 0, ("MCP search answers, Chinese query %r (%s) hit %d" % (q, src, n) if n else
                   "MCP answers but the Chinese query %r returned 0 (tokenizer or index is broken)" % q)


def step_outbound(cfg):
    if not (GATES / "outbound.py").exists():
        return False, "gates/outbound.py not found (install the machine from the repo: pip install -e)"
    if not cfg["outbound"]:
        return False, "plug.yaml has no outbound list"
    if config.plug_off(cfg):
        return False, ".plug-off is present, so the sortie lock passes everything through — remove it before testing"
    stamp = cfg["hooks_dir"] / "outbound"
    before = stamp.read_text(encoding="utf-8") if stamp.exists() else None
    time.sleep(1.05)
    fake = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "curl -X POST https://example.invalid/send"}, "cwd": str(cfg["root"])}
    fake2 = {"hook_event_name": "PreToolUse", "tool_name": "mcp__mail__send_email", "tool_input": {"to": "x"}, "cwd": str(cfg["root"])}
    codes = [_run([sys.executable, str(GATES / "outbound.py")], cfg["root"], {"PLUG_ROOT": str(cfg["root"])}, json.dumps(f)).returncode for f in (fake, fake2)]
    after = stamp.read_text(encoding="utf-8") if stamp.exists() else None
    ok = 2 in codes and after is not None and after != before
    return ok, ("fake outbound action blocked (exit 2), last fired %s" % after) if ok else \
        "the fake outbound action was not blocked (exit codes %s) or left no stamp" % codes


def step_protected(cfg, pilot):
    root = cfg["root"]
    if not (GATES / "precommit.py").exists():
        return False, "gates/precommit.py not found"
    env = {"PLUG_ROOT": str(root), "PLUG_STAGED": "self/RULES.md"}
    env.pop("KB_APPROVE", None)
    r = _run([sys.executable, str(GATES / "precommit.py")], root, env)
    parts, ok = [], r.returncode == 1 and "berserk lock" in r.stderr.lower()
    parts.append("pre-commit refused a fake write to a protected path" if ok else "pre-commit did not refuse (exit %d)" % r.returncode)
    hook = root / ".git" / "hooks" / "pre-commit"
    hp = subprocess.run(["git", "config", "core.hooksPath"], cwd=str(root), capture_output=True, text=True).stdout.strip()
    installed = (hook.exists() and "precommit" in hook.read_text(encoding="utf-8", errors="ignore")) or \
                (hp and (Path(hp) if os.path.isabs(hp) else root / hp).joinpath("pre-commit").exists())
    if not installed:
        ok, parts = False, parts + ["but the content repo has no pre-commit hook installed (gates/hooks/pre-commit)"]
    if pilot == "claude-code":
        deny = []
        for f in DENY_FILES:
            p = root / f
            if p.exists():
                try:
                    deny += (json.loads(p.read_text(encoding="utf-8")).get("permissions") or {}).get("deny") or []
                except ValueError:
                    parts.append("%s is not valid JSON" % f)
        edits = [d for d in deny if d.startswith("Edit(") and ("RULES.md" in d or "/self/**" in d)]
        if edits:
            parts.append("deny rules written, covering self/RULES.md (%d rules) — written, NOT proven in force: they "
                         "bind only a session whose project root is this repo, so prove it from one" % len(deny))
        else:
            ok, parts = False, parts + ["deny has no Edit(…self/RULES.md) rule (template pilots/claude-code/settings.template.json)"]
        if any(d.startswith("Write(") for d in deny):
            parts.append("note: Write() rules are never checked, they do nothing")
    else:
        parts.append("Codex has no permissions.deny; pre-commit is the only berserk lock on that side")
    return ok, "; ".join(parts)


def run(cfg, pilot):
    hv = harness_version(pilot)
    steps = [("① manual visible", *step_skills(cfg, pilot)), ("② MCP search", *step_mcp(cfg)),
             ("③ sortie lock", *step_outbound(cfg)), ("④ protected write", *step_protected(cfg, pilot))]
    lines = ["first contact · %s · harness %s · entryplug %s · %s" % (pilot, hv, __version__, time.strftime("%Y-%m-%d %H:%M"))]
    lines += ["%s %s · %s" % (name, "OK  " if ok else "FAIL", msg) for name, ok, msg in steps]
    bad = [i + 1 for i, s in enumerate(steps) if not s[1]]
    lines.append("first contact, nothing wrong" if not bad else "the integration is broken, do not use (step %s failed)" % ", ".join(map(str, bad)))
    print("\n".join(lines))
    np = cfg["numbers_path"]
    if np.parent.exists():
        with open(np, "a", encoding="utf-8") as f:
            f.write("\nfirst contact %s · %s · harness %s: %s\n" % (pilot, time.strftime("%Y-%m-%d"), hv, lines[-1]))
    return 0 if not bad else 1
