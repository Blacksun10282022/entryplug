# What: mirror every equipment's SKILL.md into each pilot's repo-level skills directory, keep Codex's openai.yaml
#       in step with `disable-model-invocation`, and copy manuals user-level on `plug init --link-skills` (D39).
# In:   cfg (config.load); pilots and a put callback for link_skills().
# Out:  files under <root>/<pilot skills dir>/<tool>/ (and user-level skills under --link-skills); no-op when identical.
# Not:  never edits a manual; never registers user-level MCP; never deletes hand-written skills it did not mirror.
# Who:  index (every build ends by mirroring) · init · tests.
# Note: split out of index.py / init.py to keep both files within the 250-line budget.
# Deps: stdlib json · os · shutil · pathlib · config · shapes.
import json, os, shutil
from pathlib import Path
from . import config, shapes


def mirror_skills(cfg):
    """Copy every equipment's SKILL.md into each pilot's repo-level skills directory (no-op when identical) and
    remove mirrors left behind by equipment dropped from plug.yaml (tracked in .kb/mirrored.json so hand-written
    skills in the same directory are never touched)."""
    cur = sorted({t["name"] for t in cfg["tools"] if (t["dir"] / "SKILL.md").exists()})
    stamp = cfg["index_path"].parent / "mirrored.json"
    try:
        prev = json.loads(stamp.read_text(encoding="utf-8")) if stamp.exists() else []
    except (OSError, ValueError):
        prev = []
    stale = [name for name in prev if name not in cur]
    for name, pilot in cfg["pilots"].items():
        base = cfg["root"] / pilot["skills"]
        for old in stale:
            shutil.rmtree(base / old, ignore_errors=True)
        for t in cfg["tools"]:
            src = t["dir"] / "SKILL.md"
            if not src.exists():
                continue
            dst = base / t["name"] / "SKILL.md"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                shutil.copyfile(src, dst)
            if name == "codex":
                implicit = not model_invocation_disabled(src.read_text(encoding="utf-8"))
                (dst.parent / "agents").mkdir(exist_ok=True)
                write_openai_yaml(dst.parent / "agents" / "openai.yaml", implicit)
    if cur != prev:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps(cur, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def model_invocation_disabled(text):
    """`disable-model-invocation: true` in a manual's frontmatter = sensitive equipment, owner-triggered only."""
    fm, _, _ = shapes.split_frontmatter(text)
    return bool((fm or {}).get("disable-model-invocation"))


def write_openai_yaml(path, implicit):
    """Written when absent; rewritten only when the switch disagrees with the manual's frontmatter, so a hand-edited
    file is left alone as long as it still says the same thing."""
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old is not None and ("allow_implicit_invocation: true" in old) == implicit:
        return
    path.write_text("policy:\n  allow_implicit_invocation: %s\n" % ("true" if implicit else "false"),
                    encoding="utf-8", newline="\n")


def user_skills_dir(cfg, pilot):
    """Where a pilot looks for user-level skills: plug.yaml's pilots.<name>.user_skills, else the default for
    that pilot. PLUG_USER_SKILLS redirects every pilot at once into <it>/<pilot> (tests and unusual layouts)."""
    override = os.environ.get("PLUG_USER_SKILLS")
    if override:
        return Path(os.path.expanduser(override)) / pilot
    d = cfg["pilots"].get(pilot, {}).get("user_skills") or config.USER_SKILLS.get(pilot, "~/.%s/skills" % pilot)
    return Path(os.path.expanduser(d))


def link_skills(cfg, log, pilots, put):
    """Equipment = skill: copy each SKILL.md into the user-level skills directory with the content repo's path
    stamped in (manual trigger only, D39). `disable-model-invocation: true` rides along into Codex's openai.yaml."""
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
                write_openai_yaml(base / t["name"] / "agents" / "openai.yaml", not model_invocation_disabled(text))
