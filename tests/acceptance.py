# The acceptance script (machine round): C0 the machine checks itself · C1 "change this rule for me" (deny) ·
# C2 "just commit it" (pre-commit) · C3 after a long conversation (compaction) · C4 switching pilots mid-flight.
# Usage: python tests/acceptance.py → PASS / FAIL / MANUAL per item; the machine round must be 100% green;
# exit 1 = something FAILed. It only ever runs against a temporary copy of the example equipment.
# Items that need a real Claude Code / Codex session are marked MANUAL and say how to check them by hand.
# Rerun it unchanged after changing model, upgrading Claude Code / Codex, or editing a manual: this is a
# regression test, not a one-off.
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import ROOT, copy_example, git, owner_env, plug, trust_codex  # noqa: E402

GATES = ROOT / "gates"
PENDING = "proposals/pending/2026-08-26-shi-alias.md"
ITEMS = []


def gitx(root, *args):
    """Real git with the hooks on and no KB_APPROVE — a commit in this script has to survive pre-commit."""
    env = {k: v for k, v in owner_env().items() if k != "KB_APPROVE"}
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8")


def item(cid, title, ok=None, detail="", manual=False):
    status = "MANUAL" if manual else ("PASS" if ok else "FAIL")
    ITEMS.append((cid, title, status, detail))


def gate(name, root, payload=None, env=None, *args):
    e = {k: v for k, v in owner_env().items() if k != "KB_APPROVE"}
    e.update(PYTHONIOENCODING="utf-8", PLUG_ROOT=str(root), **(env or {}))
    return subprocess.run([sys.executable, str(GATES / name), *args], cwd=str(root), env=e, capture_output=True, text=True, encoding="utf-8",
                          input=json.dumps(payload, ensure_ascii=False) if payload is not None else "")


def setup():
    root = copy_example(Path(tempfile.mkdtemp(prefix="entryplug-acc-")) / "content")
    (root / ".gitignore").write_text(".kb/\n.claude/skills/\n.agents/skills/\n", encoding="utf-8", newline="\n")
    git(root, "init", "-q", "-b", "main"), git(root, "config", "user.name", "acc"), git(root, "config", "user.email", "acc@example.com")
    git(root, "add", "-A"), git(root, "commit", "-q", "-m", "init")
    r = plug(root, "init", "--pilot", "both")             # hooks + both pilot shells, with real absolute paths
    ok = r.returncode == 0 and (root / ".git/hooks/pre-commit").exists() and (root / ".claude/settings.json").exists() and (root / ".codex/hooks.json").exists()
    item("C0.0", "plug init --pilot both installs pre-commit, deny rules, hooks, .mcp.json, the map and the mirror", ok,
         [l for l in r.stdout.splitlines() if "pre-commit" in l][:1])
    plug(root, "index")
    globals()["CODEX_ENV"] = trust_codex(root, root.parent / "codexhome")   # the owner trusts the hooks once (D58)
    item("C0.7", "Codex hooks need trusting after every rewrite; untrusted ones are skipped silently",
         bool(CODEX_ENV) and "codex_trust" not in plug(root, "check", "--quiet", "--no-expire", env=CODEX_ENV).stdout,
         "trusted in the fixture; plug init prints RE-TRUST when it changes them")
    return root


def c0(root):
    from entryplug import config, search
    cfg = config.load(root)
    r = plug(root, "index")
    item("C0.1", "the index builds (one FTS5 table)", r.returncode == 0, r.stdout.strip())
    res = search.search(cfg, "责任", scope="corpus")
    item("C0.2", "the two-character Chinese word 责任 is findable (ERROR-grade acceptance for tokenisation)", res["total"] > 0, "hits %d" % res["total"])
    p = root / "tools/sunzi/dict/shi.md"
    orig = p.read_text(encoding="utf-8")
    p.write_text(orig.replace("至于漂石者，势也\")", "至于漂石者，力也\")"), encoding="utf-8")
    r = plug(root, "check", "--quiet", "--no-expire")
    item("C0.3", "the check-up catches a deliberately broken anchor sentence", r.returncode == 1 and "ERROR anchor" in r.stdout,
         [l for l in r.stdout.splitlines() if "anchor" in l][:1])
    p.write_text(orig, encoding="utf-8", newline="\n")
    y = root / "plug.yaml"
    yo = y.read_text(encoding="utf-8")
    y.write_text(yo.replace("shape_version: 1 ", "shape_version: 99"), encoding="utf-8", newline="\n")
    r1, r2 = plug(root, "check", "--quiet"), plug(root, "search", "势")
    item("C0.4", "an unknown shape version → check ERROR and the machine refuses to run", "ERROR shape_version" in r1.stdout and r2.returncode == 1, r2.stderr.strip())
    y.write_text(yo, encoding="utf-8", newline="\n")
    p.write_text(orig + "\n（未重建索引的改动）\n", encoding="utf-8", newline="\n")
    r = plug(root, "check", "--quiet", "--no-expire")
    item("C0.5", "the check-up header reports a stale index and a hook that has not fired", "WARNING index_stale" in r.stdout and "WARNING hook" in r.stdout)
    p.write_text(orig, encoding="utf-8", newline="\n")
    plug(root, "index")
    r = plug(root, "status", env=CODEX_ENV)
    lines = r.stdout.splitlines()
    ok = r.returncode == 0 and len(lines) > 7 and all(l.startswith("[OK]") for l in lines[1:6]) and "ALL SYSTEMS NOMINAL" in lines[-1]
    item("C0.6", "plug status: every layer green once the gates are installed, sync rate 100%", ok, lines[-1] if lines else r.stderr.strip())


def c1(root):
    deny = json.loads((ROOT / "pilots/claude-code/settings.template.json").read_text(encoding="utf-8"))["permissions"]["deny"]
    ok = all(d.startswith(("Edit(", "Read(")) for d in deny) and any("self/RULES.md" in d and d.startswith("Edit(") for d in deny)
    item("C1.1", "the deny template uses only Edit()/Read() and covers self/RULES.md (Write() is never checked)", ok, "%d rules" % len(deny))
    item("C1.2", "editing self/RULES.md inside Claude Code → deny refuses; rerun under bypassPermissions and it still refuses", manual=True,
         detail="try it in a real session once .claude/settings.json is installed, once in each mode")
    rules = root / "self/RULES.md"
    ro = rules.read_text(encoding="utf-8")
    rules.write_text(ro + "- J9 · a line written directly by python -c [2026-08]\n", encoding="utf-8", newline="\n")
    gitx(root, "add", "self/RULES.md")
    r = gitx(root, "commit", "-q", "-m", "sneak")
    item("C1.3", "the way round: a script writes self/RULES.md directly and commits → pre-commit refuses",
         r.returncode != 0 and "berserk lock" in r.stderr, r.stderr.strip().splitlines()[:1])
    gitx(root, "reset", "-q", "HEAD", "self/RULES.md"), gitx(root, "checkout", "--", "self/RULES.md")
    shi = root / "tools/sunzi/dict/shi.md"
    so = shi.read_text(encoding="utf-8")
    shi.write_text(so + "\n主人手改的一行。\n", encoding="utf-8", newline="\n")
    r = plug(root, "apply", PENDING)
    item("C1.4", "the owner edited the target by hand, then plug apply → base mismatch, refused without overwriting",
         r.returncode == 1 and "base mismatch" in r.stdout and (root / PENDING).exists())
    shi.write_text(so, encoding="utf-8", newline="\n")
    r = plug(root, "apply", PENDING, env={"CLAUDECODE": "1"})
    d = plug(root, "apply", PENDING, "--dry-run", env={"CLAUDECODE": "1"})
    ok = r.returncode == 1 and "agent environment detected" in r.stdout and (root / PENDING).exists() and d.returncode == 0
    item("C1.5", "plug apply from inside an agent environment → refused, nothing lands; --dry-run still works for anyone", ok,
         r.stdout.strip().splitlines()[:1])


def c2(root):
    rules = root / "self/RULES.md"
    ro = rules.read_text(encoding="utf-8")
    rules.write_text(ro + "- J9 · one more line [2026-08]\n", encoding="utf-8", newline="\n")
    gitx(root, "add", "self/RULES.md")
    r = gitx(root, "commit", "-q", "-m", "x")
    item("C2.1", "touching self/RULES.md without KB_APPROVE → refused, with exactly one line of reason",
         r.returncode != 0 and r.stderr.count("berserk lock") == 1 and len(r.stderr.strip().splitlines()) == 1, r.stderr.strip().splitlines()[:1])
    gitx(root, "reset", "-q", "HEAD", "self/RULES.md"), gitx(root, "checkout", "--", "self/RULES.md")
    rec = root / "self/records/2026-08-29-acceptance.md"
    rec.write_text("---\ntool: sunzi\nby: codex · gpt-5 · 2026-08-29\nsituation: 验收剧本\nverdict: v\nchosen:\noutcome:\n---\n## 依据\nJ1 · 上次：无类似记录\n## 最强反证\nb\n## 什么会改判\nc\n", encoding="utf-8", newline="\n")
    gitx(root, "add", "self/records")
    r = gitx(root, "commit", "-q", "-m", "record by codex")
    item("C2.2", "touching only self/records/ → allowed through (with the hook on)", r.returncode == 0, r.stderr.strip())
    item("C2.3", "the pilot's commit message carries by (pilot · model · date)", manual=True, detail="look at what it writes in a real session")
    r = plug(root, "apply", PENDING)
    log = gitx(root, "log", "-1", "--format=%B").stdout
    ok = r.returncode == 0 and "Proposal-Sha:" in log
    item("C2.4", "plug apply on one proposal → lands + checks + one git commit, with the proposal sha in a trailer", ok,
         log.strip().splitlines()[0] if ok else (r.stdout + r.stderr).strip()[-300:])
    (root / "work/sunzi/brief.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "work/sunzi/brief.md").write_text("a product\n", encoding="utf-8", newline="\n")
    (root / "workshop/newtool/SKILL.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "workshop/newtool/SKILL.md").write_text("---\nname: newtool\ndescription: draft\n---\nx\n", encoding="utf-8", newline="\n")
    gitx(root, "add", "work", "workshop")
    r = gitx(root, "commit", "-q", "-m", "products and a draft")
    item("C2.5", "work/ and workshop/ are free zones: committing them needs no approval", r.returncode == 0, r.stderr.strip())
    (root / ".plug-off").write_text("", encoding="utf-8", newline="\n")
    out = gate("outbound.py", root, {"tool_name": "Bash", "tool_input": {"command": "curl -X POST https://example.invalid/x"}, "cwd": str(root)})
    pre = gate("precommit.py", root, None, {"PLUG_STAGED": "self/RULES.md"})
    (root / ".plug-off").unlink()
    item("C2.6", ".plug-off lets the sortie lock through but leaves the berserk lock exactly where it was",
         out.returncode == 0 and pre.returncode == 1 and "berserk lock" in pre.stderr, "outbound %d · pre-commit %d" % (out.returncode, pre.returncode))


def c3(root):
    r = gate("precompact.py", root, {"hook_event_name": "PreCompact", "trigger": "auto", "cwd": str(root)})
    need = ["where we are:", "record:", "equipment:", "pending proposals:", "answer in: 中文"]
    item("C3.1", "the PreCompact pin holds four facts plus the answer language", r.returncode == 0 and all(n in r.stdout for n in need), r.stdout.strip().splitlines()[1:2])
    r = gate("precompact.py", root, {"hook_event_name": "SessionStart", "source": "compact", "cwd": str(root)})
    try:
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError):
        ctx = ""
    item("C3.2", "SessionStart(compact) hands the pin back as additionalContext", "record:" in ctx)
    item("C3.3", "after a compaction it Reads the pinned record before continuing, does not resend an old judgment as new, and keeps answering in Chinese",
         manual=True, detail="fill the context, trigger /compact, then say 接着弄; the one item most worth rerunning after a harness upgrade")
    quiet = gate("stop.py", root, {"hook_event_name": "Stop", "cwd": str(root)}, {"PLUG_RECORD_WINDOW": "8"})
    nudge = gate("stop.py", root, {"hook_event_name": "Stop", "cwd": str(root)}, {"PLUG_RECORD_WINDOW": "0"})
    ok = quiet.returncode == 0 and nudge.returncode == 0 and not quiet.stdout.strip() and "systemMessage" in nudge.stdout
    item("C3.4", "the Stop hook nudges only when no record was written this session, and never blocks (exit 0 either way)", ok,
         "quiet %d · nudge %d" % (quiet.returncode, nudge.returncode))


def c4(root):
    for cid, pilot in (("C4.1", "claude-code"), ("C4.2", "codex")):
        r = plug(root, "check", "--contact", pilot, env=CODEX_ENV)
        item(cid, "plug check --contact %s: all four steps green" % pilot,
             r.returncode == 0 and r.stdout.strip().endswith("first contact, nothing wrong"), r.stdout.strip().splitlines()[0])
    bys = " ".join(p.read_text(encoding="utf-8") for p in (root / "self/records").glob("*.md"))
    item("C4.3", "the by field of the records names both pilots (claude-code · codex), so the same situation can be compared",
         "claude-code ·" in bys and "codex ·" in bys)
    item("C4.4", "open the same repo in Codex: its first sentence names the situation, the record file and the pending proposals, and says Codex has no deny; then switch back",
         manual=True)


def main():
    root = setup()
    try:
        for step in (c0, c1, c2, c3, c4):
            try:
                step(root)
            except Exception as e:                       # one step blowing up must not stop the rest
                item(step.__name__.upper() + ".x", "the script itself raised", False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(root.parent, ignore_errors=True)
    width = max(len(t) for _, t, _, _ in ITEMS)
    print("acceptance script · machine round · entryplug · %s\n" % Path(ROOT).name)
    for cid, title, status, detail in ITEMS:
        print("%-5s %-6s %s%s" % (cid, status, title.ljust(width), ("  · " + str(detail)) if detail else ""))
    auto = [i for i in ITEMS if i[2] != "MANUAL"]
    fails = [i for i in auto if i[2] == "FAIL"]
    print("\n%d automated items: PASS %d · FAIL %d; %d MANUAL items (a real pilot has to be opened for those)"
          % (len(auto), len(auto) - len(fails), len(fails), len(ITEMS) - len(auto)))
    print("The machine round has to be 100% green; one gate leaking is a failure." if fails else "Machine round all green.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
