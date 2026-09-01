# What: `plug status` — the boot self-check. One line per real check, then a verdict. Nothing here is a guess:
#       every line is a fact read off disk or measured (the index is really queried and timed).
# In:   cfg. `--emit` wraps the panel for a Claude Code SessionStart hook.
# Out:  the panel on stdout; exit code 0, or 1 only when the index layer itself is unusable (nothing can be
#       searched, so the pilot must know before it starts).
# Not:  never writes anything, never edits content, never injects rules or search results into the pilot;
#       it is a status panel, not a briefing. It does not run the equipment's checks/ (that is plug check).
# Who:  the owner (first command in a new terminal) · a SessionStart hook · AGENTS.md tells Codex-style pilots
#       to run it first thing · tests.
# Note: the sync rate is simply passed/total over the counted checks; .plug-off is informational and is not
#       counted. A failing line prints [NG] and the verdict becomes PATTERN ORANGE with the layer and a fix hint.
# Deps: stdlib json · sqlite3 (via search) · config · shapes.
import json, os, time
from pathlib import Path
from . import config, shapes, search

WIDTH = 20
DENY_FILES = (".claude/settings.json", ".claude/settings.local.json")


def dots(label, width=WIDTH):
    """`LCL pressure ....... ` — the label, dot leader to a fixed width, one space before the detail."""
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
    out = []
    for f in (".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json"):
        p = root / f
        if p.exists():
            out.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(out)


def precommit_path(root):
    hp = ""
    try:
        import subprocess
        hp = subprocess.run(["git", "config", "core.hooksPath"], cwd=str(root), capture_output=True, text=True).stdout.strip()
    except OSError:
        pass
    base = (Path(hp) if os.path.isabs(hp) else root / hp) if hp else root / ".git" / "hooks"
    return base / "pre-commit"


def check_index(cfg):
    """Really open the index and really run one query, so the number on the line is measured, not assumed."""
    if not cfg["index_path"].exists():
        return False, "%s missing — nothing can be searched" % cfg["index"]
    try:
        con = search.open_ro(cfg)
        docs = con.execute("select count(distinct doc) from fts").fetchone()[0]
        meta = dict(con.execute("select key, value from meta"))
        con.close()
        probe = next(iter(json.loads(meta.get("aliases", "{}")) or {"a": []}), "a")
        t0 = time.perf_counter()
        search.search(cfg, probe, scope="all", k=3)
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
    """Deny rules must cover self/ and every registered equipment; the pre-commit hook must be installed."""
    deny = deny_list(cfg["root"])
    self_ok = any(d.startswith("Edit(") and ("RULES.md" in d or "/%s/**" % cfg["self"] in d) for d in deny)
    missing = [t["name"] for t in cfg["tools"]
               if not any(str(t["path"]).strip("/") in d or "tools/**" in d for d in deny)]
    hook = precommit_path(cfg["root"])
    pre_ok = hook.exists() and "precommit" in hook.read_text(encoding="utf-8", errors="ignore")
    bits = ["deny armed (%d rules)" % len(deny) if self_ok and not missing else
            ("deny MISSING" if not deny else "deny does not cover " + ("self/" if not self_ok else ", ".join(missing))),
            "pre-commit armed" if pre_ok else "pre-commit NOT installed"]
    return (self_ok and not missing and pre_ok), " · ".join(bits)


def check_berserk(cfg):
    if os.environ.get("KB_APPROVE") == "1":
        return False, "DISARMED (KB_APPROVE=1 is set in this environment)"
    hook = precommit_path(cfg["root"])
    if not (hook.exists() and "precommit" in hook.read_text(encoding="utf-8", errors="ignore")):
        return False, "no pre-commit hook"
    return True, "armed"


def check_sortie(cfg):
    if not cfg["outbound"]:
        return False, "no outbound list in plug.yaml"
    if "outbound.py" not in hooks_text(cfg["root"]):
        return False, "hook not wired"
    if config.codex_trust(cfg):               # D58: Codex skips an untrusted hook silently — do not report armed
        return False, "armed for Claude Code; Codex has not trusted these hooks, so it skips them"
    return True, "armed" + (" (passing through: .plug-off)" if config.plug_off(cfg) else "")


def check_equipment(cfg):
    names = [t["name"] for t in cfg["tools"]]
    gone = [t["name"] for t in cfg["tools"] if not t["dir"].is_dir()]
    pend = cfg["proposals_dir"] / "pending"
    n = len(list(pend.glob("*.md"))) if pend.is_dir() else 0
    detail = "%d registered (%s) · %d pending" % (len(names), ", ".join(names) or "none", n)
    return (not gone), detail + ("" if not gone else " · MISSING: " + ", ".join(gone))


LAYERS = {"index": "the index layer", "base": "the Base", "at-field": "the AT-Field",
          "berserk": "the berserk lock", "sortie": "the sortie lock", "equipment": "the equipment bay"}
HINTS = {"index": "plug index", "base": "write self/RULES.md", "at-field": "plug init --pilot both",
         "berserk": "plug init --pilot both (and unset KB_APPROVE)",
         "sortie": "plug init --pilot both — and if it is the Codex trust line above, open an interactive codex once and trust the hooks",
         "equipment": "fix the tools: list in plug.yaml"}


def panel(cfg):
    """Returns (text, exit_code). Exit is nonzero only when the index layer itself is unusable."""
    res = {k: fn(cfg) for k, fn in (("index", check_index), ("base", check_base), ("at-field", check_atfield),
                                    ("berserk", check_berserk), ("sortie", check_sortie), ("equipment", check_equipment))}
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
    bad = [k for k, (ok, _) in res.items() if not ok]
    rate = 100.0 * (len(res) - len(bad)) / len(res)
    if bad:
        L.append("SYNC RATE %.1f%% — PATTERN ORANGE: %s degraded; run %s" %
                 (rate, " · ".join(LAYERS[k] for k in bad), HINTS[bad[0]]))
    else:
        L.append("SYNC RATE %.1f%% — ALL SYSTEMS NOMINAL. %s, LIFT OFF." % (rate, cfg["root"].name.upper()))
    return "\n".join(L), (0 if res["index"][0] else 1)


def run(cfg, emit=False):
    """--emit is fail-safe by contract: a boot panel is a diagnostic, so a degraded layer prints [NG] inside the
    panel and a crashed panel says so in one line — neither ends the session with a nonzero exit (D53). Only the
    plain (non-emit) form propagates the index-layer exit code, because there a human is reading it."""
    if emit:
        try:
            text = panel(cfg)[0]
        except Exception as e:                # never let a broken panel take the session down with it
            text = "ENTRY PLUG — INSERTION SEQUENCE\n[NG] panel ............... could not be built (%s: %s)" % (type(e).__name__, e)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}, ensure_ascii=False))
        return 0
    text, code = panel(cfg)
    print(text)
    return code
