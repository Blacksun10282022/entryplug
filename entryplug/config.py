# What: find the content repo's plug.yaml, parse it into a plain dict, resolve relative paths, list content files.
# In:   --root argument / PLUG_ROOT env var / walk up from the current directory looking for plug.yaml.
# Out:  cfg dict (root · self · records · proposals · index · tools[] · outbound · pilots · protected …);
#       walk(cfg) yields {path, rel, area, tool, sub} for every content file.
# Not:  never validates content (that is check's job); never reads the body of a content file; never writes.
# Who:  every verb and all four gates.
# Rule: plug.yaml is the only place in a content repo where paths may appear; the machine never knows where the
#       content repo is, it only knows root. Areas: rules · facts · style · record · manual · reading · playbook ·
#       dict · material · corpus · checks · proposal · numbers. work/ and workshop/ are unprotected, unindexed
#       zones. `corpus:` declares corpus outside an equipment; `protect:` adds to the berserk lock, both layers.
# Deps: stdlib + PyYAML. Shape version and machine version are pinned in entryplug/__init__.py.
import json, os, fnmatch, hashlib, re
from pathlib import Path
import yaml
from . import __version__, SHAPE_VERSION

DEFAULTS = {
    "self": "self", "proposals": "proposals", "index": ".kb/index.sqlite",
    "index_md": "index.md", "numbers": "self/数字.md", "hooks": ".kb/hooks", "pin": ".kb/pin.md",
    "language": "中文", "pilots": {"claude-code": {"skills": ".claude/skills"}, "codex": {"skills": ".agents/skills"}},
    "protected": ["self/RULES.md", "self/facts/**", "tools/**"],
    "unprotected": ["**/corpus/**", "work/**", "workshop/**"],
    "outbound": [], "tools": [], "exclude": [], "protect": [], "corpus": [],
}
PROPOSAL_DIRS = ("pending", "rejected", "applied", "tools")
FREE_ZONES = ("work", "workshop")          # products / development: never protected, never indexed
USER_SKILLS = {"claude-code": "~/.claude/skills", "codex": "~/.agents/skills"}
PLUG_OFF = ".plug-off"


def find_root(start=None):
    """PLUG_ROOT wins; otherwise walk up from start (default cwd) looking for plug.yaml. Raises FileNotFoundError."""
    env = os.environ.get("PLUG_ROOT")
    if env and (Path(env) / "plug.yaml").exists():
        return Path(env).resolve()
    p = Path(start or os.getcwd()).resolve()
    for d in (p, *p.parents):
        if (d / "plug.yaml").exists():
            return d
    raise FileNotFoundError("no plug.yaml found (pass --root <content repo>, or set PLUG_ROOT)")


def load(root=None):
    """Read plug.yaml → cfg. Relative paths resolve against root; each tool gets name/path/depends/ttl_days."""
    root = Path(root).resolve() if root else find_root()
    raw = yaml.safe_load((root / "plug.yaml").read_text(encoding="utf-8")) or {}
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if v is not None})
    cfg["root"] = root
    cfg["self_dir"] = root / cfg["self"]
    cfg["records_dir"] = cfg["self_dir"] / "records"
    cfg["proposals_dir"] = root / cfg["proposals"]
    cfg["index_path"] = root / cfg["index"]
    cfg["index_md_path"] = root / cfg["index_md"]
    cfg["numbers_path"] = root / cfg["numbers"]
    cfg["hooks_dir"] = root / cfg["hooks"]
    cfg["pin_path"] = root / cfg["pin"]
    cfg["machine_pin"] = str(raw.get("machine", "")).strip()
    cfg["shape_version"] = raw.get("shape_version")
    tools = []
    for t in raw.get("tools") or []:
        t = dict(t)
        t.setdefault("path", f"tools/{t['name']}")
        t["dir"] = root / t["path"]
        t.setdefault("depends", [])
        t.setdefault("ttl_days", {})
        tools.append(t)
    cfg["tools"] = tools
    return cfg


def version_ok(cfg):
    """Does the machine know this shape version, and is the pinned machine version the one installed?"""
    shape_ok = cfg.get("shape_version") == SHAPE_VERSION
    pin = cfg.get("machine_pin", "")
    machine_ok = (not pin) or pin.split()[-1] == __version__
    return shape_ok, machine_ok


def plug_off(cfg):
    """True when <root>/.plug-off exists: the sortie lock, the compaction pin and the record reminder all pass
    through (no Base lookups, no record nagging). Deny rules and pre-commit are NOT affected."""
    return (cfg["root"] / PLUG_OFF).exists()


def rel(cfg, path):
    return Path(path).resolve().relative_to(cfg["root"]).as_posix()


def tool_dirs(cfg):
    """Registered equipment directories, relative to root. Anything under tools/ that is not one of these is
    unregistered (workshop-grade) and therefore not protected."""
    return [str(t["path"]).strip("/").replace("\\", "/") for t in cfg["tools"]]


def matches(patterns, relpath):
    """Glob match against a relative posix path; ** counts as any depth (fnmatch does not know it)."""
    rp = str(relpath).replace("\\", "/").lstrip("./")
    for pat in patterns or []:
        if fnmatch.fnmatch(rp, pat) or fnmatch.fnmatch(rp, pat.replace("**/", "")):
            return True
        if pat.endswith("/**") and rp.startswith(pat[:-3] + "/"):
            return True
    return False


def excluded(cfg, relpath):
    """plug.yaml `exclude:` — files walk() must not enumerate, so they never reach the index or the check-up.
    It is a visibility switch only: it does NOT unprotect anything (is_protected is consulted separately), and
    pre-commit still refuses a protected path whether or not it is excluded here."""
    return matches(cfg.get("exclude"), relpath)


def protect_patterns(cfg):
    """Everything the berserk lock covers: the `protected` list plus the extra `protect` list. One list, and both
    layers read it — plug init turns it into deny rules and pre-commit refuses it. Protection is never one-layered."""
    return list(cfg["protected"]) + list(cfg.get("protect") or [])


def is_protected(cfg, relpath):
    """Protected (berserk lock): matches protect_patterns and not unprotected. ** means any depth (fnmatch).
    Two hard exemptions come first and `protect:` cannot override them: the free zones work/ and workshop/, and
    anything under tools/ that belongs to no equipment registered in plug.yaml."""
    rp = str(relpath).replace("\\", "/").lstrip("./")
    if rp.split("/")[0] in FREE_ZONES:
        return False
    if rp.startswith("tools/") and not any(rp == d or rp.startswith(d + "/") for d in tool_dirs(cfg)):
        return False
    return matches(protect_patterns(cfg), rp) and not matches(cfg["unprotected"], rp)


CODEX_EVENTS = {"PreToolUse": "pre_tool_use", "PermissionRequest": "permission_request", "PostToolUse": "post_tool_use",
                "PreCompact": "pre_compact", "PostCompact": "post_compact", "SessionStart": "session_start",
                "SessionEnd": "session_end", "UserPromptSubmit": "user_prompt_submit", "SubagentStart": "subagent_start",
                "SubagentStop": "subagent_stop", "Stop": "stop", "Interrupt": "interrupt"}
CODEX_CONTEXT = ("pre_tool_use", "post_tool_use", "session_start", "user_prompt_submit", "subagent_start")


def codex_hooks(hooks_json):
    """Every handler in a Codex hooks.json as (trust key, the hash Codex expects it to have).
    Key: <abs path>:<event_snake>:<group index>:<handler index>. Hash: sha256 over the canonical JSON of the
    handler after Codex normalises it — Codex's own recipe (D58), checked against five hashes Codex wrote."""
    try:
        cfg = (json.loads(hooks_json.read_text(encoding="utf-8")) or {}).get("hooks") or {}
    except (OSError, ValueError, AttributeError):
        return []
    out = []
    for ev, groups in cfg.items():
        snake = CODEX_EVENTS.get(ev, ev.lower())
        for gi, g in enumerate(groups or []):
            for hi, h in enumerate((g or {}).get("hooks") or []):
                t, short = h.get("timeout"), snake in ("session_end", "interrupt")
                t = min(max(1 if t is None else t, 1), 3) if short else max(600 if t is None else t, 1)
                hook = {"type": "command", "command": h.get("command") or "", "timeout": t, "async": bool(h.get("async"))}
                if h.get("statusMessage") is not None:
                    hook["statusMessage"] = h["statusMessage"]
                if h.get("additionalContextLimit") not in (None, 2500) and snake in CODEX_CONTEXT:
                    hook["additionalContextLimit"] = h["additionalContextLimit"]
                obj = {"event_name": snake, "hooks": [hook]}
                if (g or {}).get("matcher") is not None:
                    obj["matcher"] = g["matcher"]
                blob = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
                out.append(("%s:%s:%d:%d" % (hooks_json, snake, gi, hi), "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()))
    return out


def codex_trust(cfg, codex_home=None):
    """Whether Codex will really run the hooks installed here, decided the way Codex decides it.
    Codex runs a hook only while the `trusted_hash` recorded in ~/.codex/config.toml still matches the hook as
    it stands now. A hook that changed is skipped SILENTLY — no error, no line printed — so every `plug init`
    that rewrites hooks.json disarms the Codex side until the owner trusts it again (D58). We recompute Codex's
    own hash rather than guess from timestamps, so this says what Codex will do. None when every hook will run,
    otherwise one line: what is wrong and how to fix it."""
    hooks = cfg["root"] / ".codex" / "hooks.json"
    if not hooks.exists():
        return None
    conf = Path(codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
    fix = "open an interactive `codex` in this repo once; it shows a `Hooks need review` screen — trust them there."
    if not conf.exists():
        return "Codex hooks are installed but %s does not exist, so nothing has ever been trusted and none of them runs. %s" % (conf, fix)
    text = conf.read_text(encoding="utf-8", errors="replace")
    state = {m.group(1).lower(): m.group(2) for m in re.finditer(r"\[hooks\.state\.'([^']+)'\]([^\[]*)", text)}
    want = codex_hooks(hooks)
    off = [k for k, _ in want if re.search(r"enabled\s*=\s*false", state.get(k.lower(), ""))]
    bad = [k for k, h in want if k not in off and ('"%s"' % h) not in state.get(k.lower(), "")]
    if off:
        return "%d of the %d Codex hooks are switched off in %s, so Codex skips them. Turn them back on there." % (len(off), len(want), conf)
    if not bad:
        return None
    if len(bad) == len(want):
        return "none of the %d Codex hooks is trusted as it now stands, so Codex runs none of them and the sortie lock is off on that side. %s" % (len(want), fix)
    return "%d of the %d Codex hooks changed since they were trusted, so Codex skips those silently. %s" % (len(bad), len(want), fix)


def _md_files(d):
    return sorted(p for p in d.glob("*.md") if p.is_file()) if d.is_dir() else []


def walk(cfg):
    """Every content file: path · rel · area · tool · sub. Corpus takes .md/.txt, everything else .md only.
    work/ and workshop/ are never walked — products and drafts do not enter the index. Anything matching
    plug.yaml `exclude:` is skipped here too (a visibility switch, never a protection one)."""
    out, root, s = [], cfg["root"], cfg["self_dir"]
    def add(path, area, tool=None, sub=None):
        rel = path.relative_to(root).as_posix()
        if excluded(cfg, rel):
            return
        out.append({"path": path, "rel": rel, "area": area, "tool": tool, "sub": sub})
    if (s / "RULES.md").exists():
        add(s / "RULES.md", "rules")
    if (s / "style.md").exists():
        add(s / "style.md", "style")
    for p in _md_files(s / "facts"):
        add(p, "facts")
    for p in _md_files(s / "records"):
        add(p, "record")
    for t in cfg["tools"]:
        d, n = t["dir"], t["name"]
        if (d / "SKILL.md").exists():
            add(d / "SKILL.md", "manual", n)
        if (d / "READING.md").exists():
            add(d / "READING.md", "reading", n)
        for p in _md_files(d / "playbooks"):
            if p.name != "INDEX.md":
                add(p, "playbook", n)
        for p in _md_files(d / "dict"):
            add(p, "dict", n)
        for p in _md_files(d / "materials"):
            add(p, "material", n)
        for sub in ("clean", "raw"):
            cd = d / "corpus" / sub
            if cd.is_dir():
                for p in sorted(cd.rglob("*")):
                    if p.is_file() and p.suffix.lower() in (".md", ".txt"):
                        add(p, "corpus", n, sub)
        for p in sorted((d / "checks").glob("*.py")) if (d / "checks").is_dir() else []:
            add(p, "checks", n)
    for c in cfg["corpus"]:                     # corpus declared at any path (it need not sit under an equipment)
        cd = root / str(c["path"])
        if cd.is_dir():
            for p in sorted(cd.rglob("*")):
                if p.is_file() and p.suffix.lower() in (".md", ".txt"):
                    add(p, "corpus", c.get("tool"), c.get("sub", "clean"))
    for sub in PROPOSAL_DIRS:
        pd = cfg["proposals_dir"] / sub
        if pd.is_dir():
            for p in sorted(pd.rglob("*.md")):
                add(p, "proposal", None, sub)
    return out
