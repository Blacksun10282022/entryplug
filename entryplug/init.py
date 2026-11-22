# What: `plug init --pilot claude-code|codex|antigravity|both|all` — install the gates and the pilot shells into one
#       content repo: the pre-commit hook · .claude/settings.json (deny rules + hooks, merged, never overwritten) ·
#       .mcp.json · the CLAUDE.md / AGENTS.md / GEMINI.md maps (only when absent) · the manual mirror +
#       agents/openai.yaml · .codex/hooks.json and .codex/config.toml (merged) · Antigravity's workspace plugin
#       .agents/plugins/entryplug/ (D87) · the .gitignore lines · the work/ and workshop/ zones.
#       `--link-skills` additionally copies every SKILL.md into the user-level skills directory (manual trigger).
# In:   cfg · pilot. The machine's location = the repo this package lives in (gates/ must be there); the
#       interpreter = the current python (the one entryplug is installed into).
# Out:  one line per file: written / updated / already current / skipped / backed up; exit code 0. Idempotent.
# Not:  never touches content (self/ tools/ proposals/); never edits plug.yaml; never writes into the user's home
#       except under --link-skills; never overwrites someone else's pre-commit (it renames it aside).
#       No user-level MCP registration, ever.
#       The maps (CLAUDE.md / AGENTS.md) are written ONLY when absent, because they are edited after install. The
#       cost is that a corrected template never reaches a repo that already has one: fixing pilots/codex/AGENTS.md
#       fixes the next install, not the last. Existing installs must be updated by hand — `plug check` catches the
#       one claim that matters (code `map_claim`, D53), the rest is a diff against the template.
# Who:  the owner (once per content repo) · tests · acceptance (after install, plug check --contact must be green).
# Note: paths (D34) — generated pilot files carry real absolute paths; deny rules want the //c/… form and hook
#       commands use the current interpreter's absolute path. The hook goes into .git/hooks/pre-commit (git pull
#       leaves it alone; on Windows git runs it with sh); if the owner set core.hooksPath it goes there instead.
#       Hooks belong in settings.json (Claude Code does not read .claude/hooks.json; the plugin form is in pilots/).
# Deps: stdlib json · subprocess (only to ask git) · config · index · antigravity (its plugin files).
import json, os, re, shutil, sys
from pathlib import Path
from . import antigravity, codex as codex_mod, config, index, mirror, trust
from .mirror import user_skills_dir  # noqa: F401  (re-exported after move for 250-line budget)

REPO, PY = Path(__file__).resolve().parents[1], Path(sys.executable).as_posix()
SELF_PROTECT = ["self/RULES.md", "self/facts/**", "self/style.md", "plug.yaml"]
MATCHER, CODEX_MATCHER = config.MATCHER, config.CODEX_MATCHER    # the tools the pilots really expose (D65)
TOOL_PROTECT = ["SKILL.md", "READING.md", "dict/**", "playbooks/**", "materials/**", "kit/**", "checks/**"]
ZONE_NOTE = {"work": "Products land here, one directory per equipment. Not indexed, not protected, freely writable.\n",
             "workshop": "Where new equipment is built before it is registered in plug.yaml. Not indexed, not protected.\n"}


def posix_abs(p):
    """D:/dir/x → //d/dir/x (how Claude Code writes an absolute deny rule); unchanged off Windows."""
    return re.sub(r"^([A-Za-z]):", lambda m: "//" + m.group(1).lower(), Path(p).resolve().as_posix())


def deny_rules(cfg):
    """Deny rules cover self/, the equipment registered in plug.yaml, and whatever plug.yaml's `protect:` adds —
    nothing else. work/ and workshop/ and any unregistered directory under tools/ are deliberately left writable.
    `protect:` is read here and by config.is_protected, so deny and pre-commit always cover the same set: a path
    the owner declares protected is protected in both layers or in neither."""
    base = posix_abs(cfg["root"])
    rules = ["Edit(%s/%s)" % (base, x) for x in SELF_PROTECT]
    for t in cfg["tools"]:
        p = str(t["path"]).strip("/").replace("\\", "/")
        rules += ["Edit(%s/%s/%s)" % (base, p, x) for x in TOOL_PROTECT]
    rules += ["Edit(%s/%s)" % (base, str(x).strip("/").replace("\\", "/")) for x in cfg.get("protect") or []]
    # The hook stamps: deny the WRITE, not the read. A pilot that cannot read them cannot check whether a gate
    # actually fired — and `plug check` prints them in its header anyway, so denying the read hid nothing while
    # turning verification into hearsay. Forging one, on the other hand, silences the "this hook has not fired"
    # warning, and .kb/ is gitignored so pre-commit never sees it. That is the direction worth closing.
    return rules + ["Edit(%s/%s/**)" % (base, cfg["hooks"])]


def put(path, text, log):
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return log.append(("already current", path))
    path.write_text(text, encoding="utf-8", newline="\n")
    log.append(("updated" if old is not None else "written", path))


def merge_json(path, mutate, log):
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    mutate(data)
    put(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", log)


def copy_if_absent(src, dst, log):
    log.append(("skipped (exists)", dst)) if dst.exists() else put(dst, src.read_text(encoding="utf-8"), log)


def hook_cmd(script, *args):
    return '"%s" "%s"%s' % (PY, (REPO / "gates" / script).as_posix(), "".join(" " + a for a in args))


def cli_cmd(cfg, *args):
    return '"%s" -m entryplug.cli --root "%s" %s' % (PY, cfg["root"].as_posix(), " ".join(args))


def spaced(*parts):
    return [str(p) for p in parts if " " in str(p)]


def codex_hooks(cfg):
    return codex_mod.hooks_config(cfg, PY, REPO, CODEX_MATCHER)


def _hook_tag(cmd):
    """Identify which entryplug hook a command runs so rerunning init after moving python/repo updates it in place."""
    s = str(cmd or "").replace("\\", "/")
    if "gates/outbound.py" in s:
        return "outbound"
    if "gates/precompact.py" in s:
        return "precompact-emit" if "--emit" in s else "precompact"
    if "entryplug.cli" in s and "status" in s and "--emit" in s:
        return "status"
    if "gates/stop.py" in s:
        return "stop"
    return None


def merge_hooks(cfg):
    """Five hooks merged into `hooks`: updates entryplug's own entries in place (command + matcher) and leaves
    every other hook in the file untouched."""
    want = {"PreToolUse": [{"matcher": MATCHER, "hooks": [{"type": "command", "command": hook_cmd("outbound.py"), "timeout": 30}]}],
            "PreCompact": [{"hooks": [{"type": "command", "command": hook_cmd("precompact.py"), "timeout": 30}]}],
            "SessionStart": [{"matcher": "compact", "hooks": [{"type": "command", "command": hook_cmd("precompact.py", "--emit"), "timeout": 30}]},
                             {"matcher": "startup|resume|clear", "hooks": [{"type": "command", "command": cli_cmd(cfg, "status", "--emit"), "timeout": 30}]}],
            "Stop": [{"hooks": [{"type": "command", "command": hook_cmd("stop.py"), "timeout": 20}]}]}
    def mutate(d):
        hooks = d.setdefault("hooks", {})
        for event, groups in want.items():
            have = hooks.setdefault(event, [])
            for g in groups:
                cmd, tag = g["hooks"][0]["command"], _hook_tag(g["hooks"][0]["command"])
                mine = [x for x in have if any(h.get("command") == cmd or (tag and _hook_tag(h.get("command")) == tag)
                                               for h in x.get("hooks", []))]
                if not mine:
                    have.append(g)
                else:
                    for h in mine[0].get("hooks", []):
                        if h.get("command") == cmd or (tag and _hook_tag(h.get("command")) == tag):
                            h["command"] = cmd
                    if "matcher" in g and mine[0].get("matcher") != g["matcher"]:
                        mine[0]["matcher"] = g["matcher"]      # a widened matcher must reach installs made earlier (D65)
    return mutate


def install_hook(cfg, log):
    root = cfg["root"]
    if not (root / ".git").exists():
        return log.append(("skipped", "pre-commit: not a git repo (git init first, then plug init)"))
    target = trust.precommit_path(root)
    if target.exists() and "precommit.py" not in target.read_text(encoding="utf-8", errors="ignore"):
        shutil.move(str(target), str(target) + ".before-entryplug")
        log.append(("backed up", target.with_name("pre-commit.before-entryplug")))
    put(target, "#!/bin/sh\n# entryplug berserk lock — written by plug init, rerunning overwrites it.\n"
                "# Do not use --no-verify and do not set KB_APPROVE by hand.\nexec %s\n" % hook_cmd("precommit.py"), log)
    os.chmod(target, 0o755)


def gitignore(cfg, log):
    p = cfg["root"] / ".gitignore"
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    need = list(dict.fromkeys(x for x in [Path(cfg["index"]).parts[0] + "/"] + [v["skills"].rstrip("/") + "/" for v in cfg["pilots"].values()]
                              if x not in old.splitlines()))     # Codex and Antigravity share .agents/skills: one line, not two
    put(p, old.rstrip("\n") + ("\n" if old else "") + "\n".join(need) + "\n", log) if need else log.append(("already current", p))


def zones(cfg, log):
    """The two free zones. Created empty when absent; never touched again."""
    for name, note in ZONE_NOTE.items():
        d = cfg["root"] / name
        if (d / "README.md").exists():
            log.append(("already current", d / "README.md"))
        else:
            put(d / "README.md", "# %s/\n\n%s" % (name, note), log)


def claude(cfg, log):
    root = cfg["root"]
    rules, hooks = deny_rules(cfg), merge_hooks(cfg)
    def mutate(d):
        deny = d.setdefault("permissions", {}).setdefault("deny", [])
        deny.extend(x for x in rules if x not in deny)
        hooks(d)
    merge_json(root / ".claude" / "settings.json", mutate, log)
    server = {"command": PY, "args": ["-m", "entryplug.cli", "--root", root.as_posix(), "mcp"], "env": {"PYTHONIOENCODING": "utf-8"}}
    merge_json(root / ".mcp.json", lambda d: d.setdefault("mcpServers", {}).__setitem__("entryplug", server), log)
    copy_if_absent(REPO / "pilots" / "claude-code" / "CLAUDE.md", root / "CLAUDE.md", log)


def codex(cfg, log):
    copy_if_absent(REPO / "pilots" / "codex" / "AGENTS.md", cfg["root"] / "AGENTS.md", log)
    bad = spaced(PY, (REPO / "gates").as_posix(), cfg["root"].as_posix())
    if bad:
        log.append(("WARNING", "Codex hooks: a path contains a space (%s) — Codex splits `command` on whitespace "
                               "and honours no quoting, so its hooks will not start. Move the machine, the content "
                               "repo or python somewhere without spaces." % bad[0]))
    hooks_json = cfg["root"] / ".codex" / "hooks.json"
    before = hooks_json.read_text(encoding="utf-8") if hooks_json.exists() else None
    put(hooks_json, json.dumps(codex_hooks(cfg), ensure_ascii=False, indent=2) + "\n", log)
    if before != hooks_json.read_text(encoding="utf-8"):   # changed content = Codex will skip them until re-trusted
        log.append(("RE-TRUST", "Codex hooks changed. Codex runs a hook only while its recorded trusted_hash still "
                                "matches, and skips it SILENTLY otherwise — open an interactive `codex` in this repo "
                                "once and trust them on its `Hooks need review` screen, or the sortie lock does "
                                "not run on that side."))
    toml = cfg["root"] / ".codex" / "config.toml"
    old = toml.read_text(encoding="utf-8") if toml.exists() else ""
    block = '[mcp_servers.entryplug]\ncommand = "%s"\nargs = ["-m", "entryplug.cli", "--root", "%s", "mcp"]\n' % (PY, cfg["root"].as_posix())
    if "[mcp_servers.entryplug]" in old:
        new = re.sub(r"(?ms)^\[mcp_servers\.entryplug\][ \t]*\n.*?(?=^\[|\Z)", lambda _: block + "\n", old).rstrip("\n") + "\n"
        return put(toml, new, log)
    put(toml, old.rstrip("\n") + ("\n\n" if old else "") + block, log)


def agy(cfg, log):
    """Antigravity: the desktop app and the agy CLI read the same .agents/, so one wiring serves both (D87) — the
    workspace plugin (MCP server + hooks, rewritten whole: it is the machine's own folder), and GEMINI.md plus the
    AGENTS.md map it overlays, each only when absent. Nothing user-level, and no deny layer exists on this side."""
    bad = spaced(PY, (REPO / "gates").as_posix(), cfg["root"].as_posix())
    if bad:
        log.append(("WARNING", "Antigravity hooks: a path contains a space (%s) — they run under `cmd /c` as bare "
                               "words, so they will not start. Move the machine, the content repo or python "
                               "somewhere without spaces." % bad[0]))
    for rel, data in antigravity.plugin_files(cfg, PY, REPO).items():
        put(cfg["root"] / rel, json.dumps(data, ensure_ascii=False, indent=2) + "\n", log)
    for name, src in (("AGENTS.md", "codex"), ("GEMINI.md", "antigravity")):
        copy_if_absent(REPO / "pilots" / src / name, cfg["root"] / name, log)


def link_skills(cfg, log, pilots):
    mirror.link_skills(cfg, log, pilots, put)


def run(cfg, pilot, link=False):
    if not (REPO / "gates").is_dir():
        print("init: gates/ not found — install the machine from the repo (pip install -e <entryplug>)")
        return 1
    log = []
    install_hook(cfg, log), gitignore(cfg, log), zones(cfg, log)
    pilots = {"both": ["claude-code", "codex"], "all": ["claude-code", "codex", "antigravity"]}.get(pilot, [pilot])
    if "claude-code" in pilots:
        claude(cfg, log)
    if "codex" in pilots:
        codex(cfg, log)
    if "antigravity" in pilots:
        agy(cfg, log)
    index.mirror_skills(cfg)
    log.append(("mirrored", "manuals → " + " · ".join(dict.fromkeys(v["skills"] for v in cfg["pilots"].values()))))
    if link:
        link_skills(cfg, log, pilots)
    for status, path in log:
        shown = path if isinstance(path, str) else (config.rel(cfg, path) if cfg["root"] in path.resolve().parents else str(path))
        print("%-16s %s" % (status, shown))
    print("next: plug index → plug status → plug check --contact %s" % (" and ".join(pilots)))
    if not link:
        print("equipment is available inside this repo only; `plug init --link-skills` also installs the manuals user-level.")
    return 0
