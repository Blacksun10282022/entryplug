# What: how old a content file is, in days — the one clock check reads for records, proposals, materials and entries,
#       plus the first-add commit SHA for each tracked file so numbers can read initial versions in one batch.
# In:   a walked file (path · rel) with its frontmatter; {rel: date first committed} from git_added / git_first; today.
# Out:  git_first(root) → ({rel: "YYYY-MM-DD"}, {rel: sha}); git_added(root) → {rel: "YYYY-MM-DD"}; age_days(...) → int.
# Not:  never writes anything, never reads file content (frontmatter arrives already parsed); asks git once per check.
# Who:  check.run · numbers (blind-valid initial commits). Moved here from check.py (D86).
# Note: the order is frontmatter `date` (materials, D11) → filename date prefix → date in `by` → git first commit → mtime;
#       a record's `due` is a separate thing (shapes.due_date) and never moves its age.
# Deps: stdlib (datetime · re · subprocess · time).
import re, subprocess, time
from datetime import date, datetime


def iso_day(v):
    """Parse a YAML date or YYYY-MM-DD string into a date, else None."""
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(v or "").strip())
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def git_first(root):
    """({rel: date first committed}, {rel: earliest add commit sha}); ({}, {}) outside a git repo."""
    try:
        out = subprocess.run(["git", "-c", "core.quotePath=false", "log", "--diff-filter=A", "--format=@%cs %H", "--name-only"],
                             cwd=str(root), capture_output=True, text=True, encoding="utf-8").stdout
    except OSError:
        return {}, {}
    added, commits, d, sha = {}, {}, None, None
    for line in out.splitlines():
        if line.startswith("@"):
            parts = line[1:].split()
            d, sha = (parts[0], parts[1]) if len(parts) >= 2 else (None, None)
        elif line.strip() and d and sha:
            rel = line.strip()
            added.setdefault(rel, d)
            commits[rel] = sha                          # log walks newest→oldest, so last write = earliest add commit
    return added, commits


def git_added(root):
    """{rel: date first committed}; {} when this is not a git repo."""
    return git_first(root)[0]


def unique_dest(directory, name):
    """Return directory/name if unused, else name-2, name-3, ... so moving an archived proposal never overwrites."""
    dst = directory / name
    if not dst.exists():
        return dst
    stem, suf, n = dst.stem, dst.suffix, 2
    while (directory / ("%s-%d%s" % (stem, n, suf))).exists():
        n += 1
    return directory / ("%s-%d%s" % (stem, n, suf))


def age_days(f, fm, added, today):
    """File age: frontmatter `date` → filename date prefix → date in `by` → date first committed → mtime."""
    fm_day = iso_day(fm.get("date"))
    if fm_day is not None:
        return (today - fm_day).days
    m = re.match(r"(\d{4}-\d{2}-\d{2})", f["path"].name) or re.search(r"(\d{4}-\d{2}-\d{2})", str(fm.get("by") or ""))
    s = m.group(1) if m else added.get(f["rel"])
    try:
        return (today - date.fromisoformat(s)).days if s else int((time.time() - f["path"].stat().st_mtime) // 86400)
    except ValueError:
        return 0
