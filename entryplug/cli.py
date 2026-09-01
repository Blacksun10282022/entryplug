# What: the `plug` command — five verbs (index · check · apply · eval · search) plus status · init · mcp · hash.
# In:   argv; --root names the content repo (otherwise PLUG_ROOT, otherwise walk up looking for plug.yaml).
# Out:  each verb's text report on stdout (forced UTF-8, so a Windows console does not mangle it);
#       exit 0 = passed, 1 = ERRORs / refused, 2 = no plug.yaml found.
# Not:  contains no domain logic; is not interactive; schedules nothing; injects nothing into the pilot.
# Who:  the owner (a terminal) · a pilot (Bash) · the hook scripts (gates/) · .mcp.json (plug mcp) · tests.
# Note: one module per verb; this file only dispatches arguments and imports on demand, so `plug search` never
#       loads check's code. When the shape version is unknown the machine refuses to run everything except
#       check and status — the two commands whose whole job is to tell you what is wrong.
# Deps: stdlib argparse. Versions live in entryplug/__init__.py.
import argparse, sys
from . import __version__, SHAPE_VERSION, config


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def parser():
    ap = argparse.ArgumentParser(prog="plug", description="entryplug (Entry Plug) · index · search · check · status · approve a proposal · eval")
    ap.add_argument("--root", help="content repo root (the directory holding plug.yaml)")
    ap.add_argument("--version", action="version", version="entryplug %s · shape v%d" % (__version__, SHAPE_VERSION))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index", help="build / incrementally rebuild the index, write index.md and the playbook directory, mirror the manuals")
    p.add_argument("--full", action="store_true", help="full rebuild")
    p = sub.add_parser("check", help="check-up: ERROR / WARNING list + header self-check + one page of report + sync rate")
    p.add_argument("--contact", choices=["claude-code", "codex"], help="first contact: the four-step integration smoke test")
    p.add_argument("--no-expire", action="store_true", help="do not move proposals unapproved for 30 days to rejected/")
    p.add_argument("--quiet", action="store_true", help="print the findings only, no report")
    p = sub.add_parser("status", help="boot self-check: one line per layer, then a verdict (EVA panel)")
    p.add_argument("--emit", action="store_true", help="print the panel as SessionStart additionalContext JSON")
    p = sub.add_parser("apply", help="approve one refit request: verify base → land → check → commit (owner only)")
    p.add_argument("proposal")
    p.add_argument("--reject", metavar="REASON", help="reject: move to rejected/ and write one line of reason")
    p.add_argument("--dry-run", action="store_true", help="show the diff only, land nothing (allowed for anyone)")
    p.add_argument("--owner", action="store_true", help="the owner is typing this: run even inside an agent environment")
    p = sub.add_parser("eval", help="gold-set recall@10; zero recall on Chinese queries is an ERROR")
    p.add_argument("goldset")
    p.add_argument("--k", type=int, default=10)
    p = sub.add_parser("search", help="search (the same function as MCP search; dict · playbooks · records by default, corpus needs --scope corpus)")
    p.add_argument("queries", nargs="+")
    p.add_argument("--scope", default="tools", choices=["tools", "corpus", "all"], help="tools = dict · playbooks · records (default) · corpus = the corpus · all")
    p.add_argument("--tool"), p.add_argument("--kind")
    p.add_argument("--k", type=int, default=8), p.add_argument("--per-doc", type=int, default=2)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("init", help="install the gates and pilot shells into a content repo (pre-commit · deny · hooks · .mcp.json · map · mirror); idempotent")
    p.add_argument("--pilot", choices=["claude-code", "codex", "both"], default="both")
    p.add_argument("--link-skills", action="store_true", help="also copy every SKILL.md into the user-level skills directory (manual trigger)")
    sub.add_parser("mcp", help="stdio MCP server (one tool: search)")
    p = sub.add_parser("hash", help="the base short hash of a file (for writing a proposal)")
    p.add_argument("file")
    return ap


def main(argv=None):
    _utf8()
    a = parser().parse_args(argv)
    try:
        cfg = config.load(a.root)
    except FileNotFoundError as e:
        print("plug: %s" % e, file=sys.stderr)
        return 2
    shape_ok, _ = config.version_ok(cfg)
    if not shape_ok and a.cmd not in ("check", "status"):
        print("plug: plug.yaml declares shape version %r, which this machine (v%d) does not know — refusing to run; "
              "start with plug check" % (cfg.get("shape_version"), SHAPE_VERSION), file=sys.stderr)
        return 1
    if a.cmd == "index":
        from . import index
        s = index.build(cfg, full=a.full)
        print("index: %d files · %d chunks · changed %d · removed %d · corpus docs %d" % (s["files"], s["chunks"], s["changed"], s["removed"], s["docs"]))
        for e in s["errors"]:
            print("  shape ERROR " + e)
        return 0
    if a.cmd == "check":
        if a.contact:
            from . import contact
            return contact.run(cfg, a.contact)
        from . import check, report
        r = check.run(cfg, expire=not a.no_expire)
        print(report.format_findings(r) if a.quiet else report.report(cfg, r))
        return 1 if r["errors"] else 0
    if a.cmd == "status":
        from . import status
        if not shape_ok:
            print("plug: plug.yaml declares shape version %r, unknown to this machine (v%d) — run plug check"
                  % (cfg.get("shape_version"), SHAPE_VERSION), file=sys.stderr)
        return status.run(cfg, emit=a.emit)
    if a.cmd == "apply":
        from . import apply
        return apply.run(cfg, a.proposal, reject=a.reject, dry_run=a.dry_run, owner=a.owner)
    if a.cmd == "eval":
        from . import eval as ev
        return ev.run(cfg, a.goldset, k=a.k)
    if a.cmd == "search":
        from . import search
        try:
            res = search.search(cfg, a.queries, scope=a.scope, tool=a.tool, kind=a.kind, k=a.k, per_doc=a.per_doc)
        except FileNotFoundError as e:
            print("plug: %s" % e, file=sys.stderr)
            return 1
        import json
        print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else search.format_rows(res))
        return 0
    if a.cmd == "init":
        from . import init
        return init.run(cfg, a.pilot, link=a.link_skills)
    if a.cmd == "mcp":
        from . import mcp
        return mcp.serve(cfg)
    if a.cmd == "hash":
        from . import apply
        print(apply.blob_hash(open(a.file, "rb").read()))
        return 0


if __name__ == "__main__":
    sys.exit(main())
