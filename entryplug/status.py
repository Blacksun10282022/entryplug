# What: `plug status` — the boot self-check (EVA panel). One line per real check, then a verdict.
# In:   cfg; `--emit` wraps the panel for SessionStart (panel as systemMessage, one verdict line for the pilot).
# Out:  the panel on stdout; exit 0, or 1 only when the index layer itself is unusable.
# Not:  never writes anything, never edits content, never injects rules or search results; never runs checks/.
# Who:  the owner · SessionStart hook · AGENTS.md · tests.
# Note: .plug-off and `Records due` (D86) are [--] informational lines, never counted and never orange.
#       A stale index is [NG] with how far behind (D83), exit stays 0.
# Deps: stdlib json · config · shapes · search · trust · index · antigravity.
import json, os, re, time
from datetime import date
from pathlib import Path
from . import antigravity, config, shapes, search, trust, index

PILOT_ONLY = "(boot line for you, the pilot: never paste it, a hook or trust status, or index numbers into an answer for the owner)"
WIDTH, DUE_LABEL, HEAD_BYTES = 20, "Records due", 4096
DENY_FILES = (".claude/settings.json", ".claude/settings.local.json")
RE_DUE = re.compile(rb"(?m)^due[ \t]*:")
precommit_path = trust.precommit_path


def dots(label, width=WIDTH):
    return (label + " ").ljust(width, ".") + " "


def mark(ok):
    return "[OK]" if ok else "[NG]"


def deny_list(root):
    out = []
    for f in DENY_FILES:
        p = root / f
        if p.exists():
            try:
                out += (json.loads(p.read_text(encoding="utf-8")).get("permissions") or {}).get("deny") or []
            except ValueError:
                pass
    return out


def hooks_text(root):
    """Everything the pilots' hook configs say, as one blob — enough to see whether a gate is wired."""
    return "\n".join((root / f).read_text(encoding="utf-8", errors="ignore")
                     for f in (".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json",
                               antigravity.PLUGIN + "/hooks.json") if (root / f).exists())


def check_index(cfg):
    """Really open the index and really run one query, so the number on the line is measured, not assumed."""
    if not cfg["index_path"].exists():
        return False, "%s missing — nothing can be searched" % cfg["index"]
    try:
        con = search.open_ro(cfg)
        try:
            docs = con.execute("select count(distinct doc) from fts").fetchone()[0]
            meta = dict(con.execute("select key, value from meta"))
        finally:
            con.close()
        aliases = json.loads(meta.get("aliases", "{}"))
        probe = next((k for k, v in aliases.items() if all(len(m) <= 4 for m in [k] + v if index.CJK.search(m))), "a")
        t0 = time.perf_counter()
        search.search(cfg, probe, scope="all", k=3, auto_index=False, check_stale=False)  # pure query ms; stale checked once in panel()
        ms = int((time.perf_counter() - t0) * 1000)
    except Exception as e:
        return False, "%s unreadable (%s: %s)" % (cfg["index"], type(e).__name__, e)
    return True, "%s (%d docs, %dms)" % (Path(cfg["index"]).name, docs, ms)


def check_base(cfg):
    s = cfg["self_dir"]
    rules = s / "RULES.md"
    if not rules.exists():
        return False, "%s/RULES.md missing — the Base is the point of this repo" % cfg["self"]
    n = len(shapes.parse_rules(rules.read_text(encoding="utf-8"))["ids"])
    facts = len(list((s / "facts").glob("*.md"))) if (s / "facts").is_dir() else 0
    recs = len(list(cfg["records_dir"].glob("*.md"))) if cfg["records_dir"].is_dir() else 0
    parts = ["RULES %d" % n] + (["style"] if (s / "style.md").exists() else []) + ["facts %d" % facts, "records %d" % recs]
    return True, "%s/ (%s)" % (cfg["self"], " · ".join(parts))


def check_atfield(cfg):
    """Deny rules must cover self/, registered equipment and `protect:` when Claude Code is wired (or before any
    pilot is wired). Codex and Antigravity have no repo-level deny layer, so pre-commit alone holds there."""
    root = cfg["root"]
    has_claude = any((root / f).exists() for f in DENY_FILES)
    has_other = (root / ".codex" / "hooks.json").exists() or antigravity.installed(cfg)
    hook = precommit_path(root)
    pre_ok = trust.hook_ok(hook)
    pre_msg = "pre-commit armed" if pre_ok else ("pre-commit NOT installed" if not hook.exists() else "pre-commit is NOT the plug init hook (run plug init)")
    if not has_claude and has_other:
        return pre_ok, "no deny layer (pre-commit only) · " + pre_msg
    deny = deny_list(root)
    self_ok = any(d.startswith("Edit(") and ("RULES.md" in d or "/%s/**" % cfg["self"] in d) for d in deny)
    missing = [t["name"] for t in cfg["tools"] if not any(str(t["path"]).strip("/") in d or "tools/**" in d for d in deny)]
    extra = [str(p).strip("/").replace("\\", "/") for p in cfg.get("protect") or []]
    miss_extra = [p for p in extra if not any(d.startswith("Edit(") and d.endswith("/" + p + ")") for d in deny)]
    deny_ok = self_ok and not missing and not miss_extra
    deny_msg = ("deny written (%d rules)" % len(deny) if deny_ok else
                ("deny MISSING" if not deny else "deny does not cover " + ("self/" if not self_ok else ", ".join(missing + miss_extra))))
    return (deny_ok and pre_ok), "%s · %s" % (deny_msg, pre_msg)


def check_berserk(cfg):
    if os.environ.get("KB_APPROVE") == "1":
        return False, "DISARMED (KB_APPROVE=1 is set in this environment)"
    hook = precommit_path(cfg["root"])
    if not hook.exists():
        return False, "no pre-commit hook"
    if not trust.hook_ok(hook):                   # a stub that only says exit 0 must not read as armed (D68)
        return False, "pre-commit hook is not the one plug init writes"
    return True, "armed"


def check_sortie(cfg):
    if not cfg["outbound"]:
        return False, "no outbound list in plug.yaml"
    if "outbound.py" not in hooks_text(cfg["root"]):
        return False, "hook not wired"
    if config.codex_trust(cfg):               # D58: Codex skips an untrusted hook silently — do not report armed
        return False, "armed for Claude Code; Codex has not trusted these hooks, so it skips them"
    agy = antigravity.problem(cfg)            # D88: plugin switched off, or no outbound rule names its shell tool
    if agy:
        return False, agy
    return True, "armed" + (" (passing through: .plug-off)" if config.plug_off(cfg) else "")


def check_equipment(cfg):
    names = [t["name"] for t in cfg["tools"]]
    gone = [t["name"] for t in cfg["tools"] if not t["dir"].is_dir()]
    pend = cfg["proposals_dir"] / "pending"
    n = len(list(pend.glob("*.md"))) if pend.is_dir() else 0
    detail = "%d registered (%s) · %d pending" % (len(names), ", ".join(names) or "none", n)
    return (not gone), detail + ("" if not gone else " · MISSING: " + ", ".join(gone))


def due_records(cfg, today=None):
    """Records whose `due` day has come and whose outcome is empty, oldest first: [(day, stem)]. This runs at every
    boot over every record, so a file is YAML-parsed only when its frontmatter bytes hold a `due:` line (D86); the
    rule itself is shapes.outcome_owed, the same one check and numbers read."""
    d, today, out = cfg["records_dir"], today or date.today(), []
    for p in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            with open(p, "rb") as fh:
                raw = fh.read(HEAD_BYTES)                # the frontmatter is near the top; the body is most of the bytes
                end = raw.find(b"\n---", 3)              # the frontmatter's closing line
                if end < 0 and raw.startswith(b"---"):
                    raw += fh.read()                     # a frontmatter longer than the head: read the rest
                    end = raw.find(b"\n---", 3)
        except OSError:                                  # a directory named *.md, an unreadable file: not a record
            continue
        if not raw.startswith(b"---") or end < 0 or not RE_DUE.search(raw, 0, end):
            continue
        if config.excluded(cfg, p.relative_to(cfg["root"]).as_posix()):     # walk() skips these too
            continue
        fm = shapes.split_frontmatter(raw.decode("utf-8", errors="replace"))[0] or {}
        day = shapes.due_date(fm)
        if day and shapes.outcome_owed(fm, 0, today):     # with a due day the age is never read
            out.append((day, p.stem))
    return sorted(out)


def due_line(cfg):
    """One [--] line for the records due and unsettled, or None when there are none: a to-do, not a broken layer,
    so it is not counted in the sync rate and never turns the verdict orange (D86)."""
    due = due_records(cfg)
    if not due:
        return None
    (day, stem), more = due[0], len(due) - 1
    return "[--] %s%d due, no outcome yet: %s%s (due %s)%s — settle %s by filling outcome" % (
        dots(DUE_LABEL), len(due), "oldest " if more else "", stem, day, ", and %d more" % more if more else "",
        "them" if more else "it")


LAYERS = {"index": "the index layer", "base": "the Base", "at-field": "the AT-Field",
          "berserk": "the berserk lock", "sortie": "the sortie lock", "equipment": "the equipment bay"}
HINTS = {"index": "plug index", "base": "write self/RULES.md", "at-field": "plug init --pilot both",
         "berserk": "plug init --pilot both (and unset KB_APPROVE)",
         "sortie": "plug init --pilot both — and if it is the Codex trust line above, open an interactive codex once and trust the hooks; if it is Antigravity's, do what that line says",
         "equipment": "fix the tools: list in plug.yaml"}


def panel(cfg):
    """Returns (text, exit_code). Exit is nonzero only when the index layer itself is unusable."""
    res = {k: fn(cfg) for k, fn in (("index", check_index), ("base", check_base), ("at-field", check_atfield),
                                    ("berserk", check_berserk), ("sortie", check_sortie), ("equipment", check_equipment))}
    # D83: a stale index used to pass as [OK] while the read-only MCP search could not see the newest pages.
    lag = res["index"][0] and index.stale(cfg)
    if lag:
        res["index"] = (False, "%s · STALE: %s (MCP search reads it as is)" % (res["index"][1], lag))
    off = config.plug_off(cfg)
    L = ["ENTRY PLUG — INSERTION SEQUENCE",
         "%s %s%s" % (mark(res["index"][0]), dots("LCL pressure"), res["index"][1]),
         "%s %s%s" % (mark(res["base"][0]), dots("A10 nerve link"), res["base"][1]),
         "%s %s%s" % (mark(res["at-field"][0]), dots("AT-Field"), res["at-field"][1]),
         "%s %s%-14s %s %s%s" % (mark(res["berserk"][0]), dots("Berserk lock"), res["berserk"][1],
                                 mark(res["sortie"][0]), dots("Sortie lock", 15), res["sortie"][1]),
         "%s %s%s" % (mark(res["equipment"][0]), dots("Equipment bay"), res["equipment"][1]),
         "[--] %s%s" % (dots("plug-off"), "present — sortie lock, compaction pin and record reminder pass through"
                        if off else "not present")]
    due = None if off else due_line(cfg)           # the plug is out: no record business
    if due:
        L.append(due)
    bad = [k for k, (ok, _) in res.items() if not ok]
    rate = 100.0 * (len(res) - len(bad)) / len(res)
    if bad:
        L.append("SYNC RATE %.1f%% — PATTERN ORANGE: %s degraded; run %s" %
                 (rate, " · ".join(LAYERS[k] for k in bad), HINTS[bad[0]]))
    else:
        L.append("SYNC RATE %.1f%% — ALL SYSTEMS NOMINAL. %s, LIFT OFF." % (rate, cfg["root"].name.upper()))
    return "\n".join(L), (0 if res["index"][0] or lag else 1)


def brief(text):
    """The one line the pilot gets (D74): verdict, every [NG] segment (including Sortie lock when Berserk lock is
    [OK] on the same line), and the records-due line (D86)."""
    lines, ng = text.splitlines(), []
    for l in lines:
        s = l.strip()
        if s.startswith("[--] " + dots(DUE_LABEL)):
            ng.append(s)
        elif "[NG]" in s:
            ng += [m.strip() for m in re.findall(r"\[NG\].*?(?=\s+\[(?:OK|NG)\]|$)", s)]
    verdict = lines[-1].strip() if lines else ""
    return " · ".join(["entry plug boot: " + verdict] + ng) + " " + PILOT_ONLY


def run(cfg, emit=False):
    """--emit is fail-safe by contract: a boot panel is a diagnostic, so a degraded layer prints [NG] inside the
    panel and a crashed panel says so in one line — neither ends the session with a nonzero exit (D53). Only the
    plain (non-emit) form propagates the index-layer exit code, because there a human is reading it."""
    if emit:
        try:
            text = panel(cfg)[0]
        except Exception as e:                # never let a broken panel take the session down with it
            text = "ENTRY PLUG — INSERTION SEQUENCE\n[NG] panel ............... could not be built (%s: %s)" % (type(e).__name__, e)
        out = antigravity.boot(text, brief(text)) if emit == "antigravity" else \
            {"systemMessage": text, "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": brief(text)}}
        print(json.dumps(out, ensure_ascii=False))
        return 0
    text, code = panel(cfg)
    print(text)
    return code
