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
import os, fnmatch
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
