# What: `plug init --pilot claude-code|codex|both` — install the gates and the pilot shells into one content repo:
#       the pre-commit hook · .claude/settings.json (deny rules + hooks, merged, never overwritten) · .mcp.json ·
#       the CLAUDE.md / AGENTS.md map (only when absent) · the manual mirror + agents/openai.yaml ·
#       .codex/hooks.json and .codex/config.toml (merged) · three .gitignore lines · the work/ and workshop/ zones.
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
# Deps: stdlib json · subprocess (only to ask git) · config · index.
import json, os, re, shutil, subprocess, sys
from pathlib import Path
from . import config, index

REPO, PY = Path(__file__).resolve().parents[1], Path(sys.executable).as_posix()
SELF_PROTECT = ["self/RULES.md", "self/facts/**", "self/style.md", "plug.yaml"]
TOOL_PROTECT = ["SKILL.md", "READING.md", "dict/**", "playbooks/**", "materials/**", "checks/**"]
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


def codex_cmd(*parts):
    """Codex takes `command` as ONE string and splits it on whitespace without honouring quotes, so the Claude
    form (quoted paths) makes it try to spawn a program whose name contains quote characters — which is why every
    Codex hook reported Failed. Emit bare, space-separated words instead. A path containing a space cannot be
    expressed this way at all; spaced() reports that so init can warn instead of writing something that dies later."""
    return " ".join(str(p) for p in parts)


def spaced(*parts):
    return [str(p) for p in parts if " " in str(p)]


def codex_hooks(cfg):
    """The same five gates, in Codex 0.152's shape: {hooks: {<Event>: [{matcher, hooks: [handler]}]}} with
    handler {type, command, timeout}. Event names are PascalCase, the payload is Claude-shaped, so the gate
    scripts are unchanged. PreToolUse blocks here as it does on Claude Code: the deny decision goes on stdout and
    the process exits 0 (D56) — outbound.py handles both. (D53 first concluded that Codex hooks cannot veto; that
    was wrong, and D57 says why: the three forms tried are each marked unsupported in Codex's own binary.)
    What Codex still has no equivalent of is `permissions.deny`, so the berserk lock leans on pre-commit alone."""
    gate = lambda s, *a: codex_cmd(PY, (REPO / "gates" / s).as_posix(), *a)
    cli = codex_cmd(PY, "-m", "entryplug.cli", "--root", cfg["root"].as_posix(), "status", "--emit")
    return {"hooks": {
        "PreToolUse": [{"matcher": "Bash|shell|mcp__.*", "hooks": [{"type": "command", "command": gate("outbound.py"), "timeout": 30}]}],
        "PreCompact": [{"hooks": [{"type": "command", "command": gate("precompact.py"), "timeout": 30}]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": cli, "timeout": 30}]}],
        "Stop": [{"hooks": [{"type": "command", "command": gate("stop.py"), "timeout": 20}]}],
    }}


def merge_hooks(cfg):
    """Five hooks merged into `hooks`, returned as a mutator: sortie lock (PreToolUse) · compaction pin
    (PreCompact) · pin re-injection and the boot panel (SessionStart) · record reminder (Stop). A command that is
    already there is not added twice, and nothing else in the file is touched."""
    want = {"PreToolUse": [{"matcher": "Bash|WebFetch|mcp__.*", "hooks": [{"type": "command", "command": hook_cmd("outbound.py"), "timeout": 30}]}],
            "PreCompact": [{"hooks": [{"type": "command", "command": hook_cmd("precompact.py"), "timeout": 30}]}],
            "SessionStart": [{"matcher": "compact", "hooks": [{"type": "command", "command": hook_cmd("precompact.py", "--emit"), "timeout": 30}]},
                             {"matcher": "startup|resume|clear", "hooks": [{"type": "command", "command": cli_cmd(cfg, "status", "--emit"), "timeout": 30}]}],
            "Stop": [{"hooks": [{"type": "command", "command": hook_cmd("stop.py"), "timeout": 20}]}]}
    def mutate(d):
        hooks = d.setdefault("hooks", {})
        for event, groups in want.items():
            have = hooks.setdefault(event, [])
            for g in groups:
                if not any(h.get("command") == g["hooks"][0]["command"] for x in have for h in x.get("hooks", [])):
                    have.append(g)
    return mutate


def install_hook(cfg, log):
    root = cfg["root"]
    if not (root / ".git").exists():
        return log.append(("skipped", "pre-commit: not a git repo (git init first, then plug init)"))
    hp = subprocess.run(["git", "config", "core.hooksPath"], cwd=str(root), capture_output=True, text=True).stdout.strip()
    target = ((Path(hp) if os.path.isabs(hp) else root / hp) if hp else root / ".git" / "hooks") / "pre-commit"
    if target.exists() and "precommit.py" not in target.read_text(encoding="utf-8", errors="ignore"):
        shutil.move(str(target), str(target) + ".before-entryplug")
        log.append(("backed up", target.with_name("pre-commit.before-entryplug")))
    put(target, "#!/bin/sh\n# entryplug berserk lock — written by plug init, rerunning overwrites it.\n"
                "# Do not use --no-verify and do not set KB_APPROVE by hand.\nexec %s\n" % hook_cmd("precommit.py"), log)
    os.chmod(target, 0o755)


def gitignore(cfg, log):
    p = cfg["root"] / ".gitignore"
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    need = [x for x in [Path(cfg["index"]).parts[0] + "/"] + [v["skills"].rstrip("/") + "/" for v in cfg["pilots"].values()] if x not in old.splitlines()]
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
    merge_json(root / ".mcp.json", lambda d: d.setdefault("mcpServers", {}).setdefault("entryplug", server), log)
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
    if "[mcp_servers.entryplug]" in old:
        return log.append(("already current", toml))
    put(toml, old.rstrip("\n") + ("\n\n" if old else "") + '[mcp_servers.entryplug]\ncommand = "%s"\nargs = ["-m", "entryplug.cli", "--root", "%s", "mcp"]\n' % (PY, cfg["root"].as_posix()), log)


def user_skills_dir(cfg, pilot):
    """Where a pilot looks for user-level skills: plug.yaml's pilots.<name>.user_skills, else the default for
    that pilot. PLUG_USER_SKILLS redirects every pilot at once into <it>/<pilot> (tests and unusual layouts)."""
    override = os.environ.get("PLUG_USER_SKILLS")
    if override:
        return Path(os.path.expanduser(override)) / pilot
    d = cfg["pilots"].get(pilot, {}).get("user_skills") or config.USER_SKILLS.get(pilot, "~/.%s/skills" % pilot)
    return Path(os.path.expanduser(d))


def link_skills(cfg, log, pilots):
    """Equipment = skill: copy each SKILL.md into the user-level skills directory so the equipment is available
    outside the content repo. Manual trigger only. A copy (not a symlink) so the content repo's absolute path can
    be stamped in — that is what tells the equipment where products go. `disable-model-invocation: true` rides
    along in the frontmatter and is passed through to Codex's openai.yaml."""
    for pilot in pilots:
        base = user_skills_dir(cfg, pilot)
        for t in cfg["tools"]:
            src = t["dir"] / "SKILL.md"
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8")
            stamp = ("\n---\n\nInstalled by `plug init --link-skills` from `%s`.\n"
                     "Base repo: `%s`. Products go to `%s/work/%s/` unless the owner names somewhere else.\n"
                     "Outside that repo the Base (self/) is not loaded: say so instead of inventing the owner's rules.\n"
                     % (config.rel(cfg, src), cfg["root"].as_posix(), cfg["root"].as_posix(), t["name"]))
            put(base / t["name"] / "SKILL.md", text.rstrip("\n") + "\n" + stamp, log)
            if pilot == "codex":
                (base / t["name"] / "agents").mkdir(parents=True, exist_ok=True)
                index.write_openai_yaml(base / t["name"] / "agents" / "openai.yaml", not index.model_invocation_disabled(text))


def run(cfg, pilot, link=False):
    if not (REPO / "gates").is_dir():
        print("init: gates/ not found — install the machine from the repo (pip install -e <entryplug>)")
        return 1
    log = []
    install_hook(cfg, log), gitignore(cfg, log), zones(cfg, log)
    pilots = ["claude-code", "codex"] if pilot == "both" else [pilot]
    if "claude-code" in pilots:
        claude(cfg, log)
    if "codex" in pilots:
        codex(cfg, log)
    index.mirror_skills(cfg)
    log.append(("mirrored", "manuals → " + " · ".join(v["skills"] for v in cfg["pilots"].values())))
    if link:
        link_skills(cfg, log, pilots)
    for status, path in log:
        shown = path if isinstance(path, str) else (config.rel(cfg, path) if cfg["root"] in path.resolve().parents else str(path))
        print("%-16s %s" % (status, shown))
    print("next: plug index → plug status → plug check --contact %s" % (" and ".join(pilots)))
    if not link:
        print("equipment is available inside this repo only; `plug init --link-skills` also installs the manuals user-level.")
    return 0
