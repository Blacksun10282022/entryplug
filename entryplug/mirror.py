# What: mirror every equipment's SKILL.md into each pilot's repo-level skills directory, and keep Codex's
#       openai.yaml switch in step with the manual's `disable-model-invocation` frontmatter.
# In:   cfg (config.load).
# Out:  files under <root>/<pilot skills dir>/<tool>/; a no-op when the mirror is already identical.
# Not:  never edits a manual; never installs user-level skills (that is plug init --link-skills).
# Who:  index (every build ends by mirroring) · init · tests.
# Note: split out of index.py on 2026-09-04 to keep that file inside the 250-line rule after D76.
# Deps: stdlib shutil · shapes (frontmatter).
import shutil
from . import shapes


def mirror_skills(cfg):
    """Copy every equipment's SKILL.md into each pilot's repo-level skills directory (no-op when identical).
    `disable-model-invocation: true` in the manual's frontmatter is passed through to Codex's openai.yaml,
    whose implicit-invocation switch does not live in the frontmatter."""
    for name, pilot in cfg["pilots"].items():
        for t in cfg["tools"]:
            src = t["dir"] / "SKILL.md"
            if not src.exists():
                continue
            dst = cfg["root"] / pilot["skills"] / t["name"] / "SKILL.md"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                shutil.copyfile(src, dst)
            if name == "codex":
                implicit = not model_invocation_disabled(src.read_text(encoding="utf-8"))
                (dst.parent / "agents").mkdir(exist_ok=True)
                write_openai_yaml(dst.parent / "agents" / "openai.yaml", implicit)


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
