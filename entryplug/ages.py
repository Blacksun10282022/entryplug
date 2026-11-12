# What: how old a content file is, in days — the one clock check reads for records, proposals, materials and entries.
# In:   a walked file (path · rel) with its frontmatter; {rel: date first committed} from git_added(root); today.
# Out:  git_added(root) → {rel: "YYYY-MM-DD"} ({} outside a git repo); age_days(...) → an int (0 on an unreadable date).
# Not:  never writes anything, never reads file content (the `by` date arrives already parsed in fm); asks git
#       once per check, not once per file.
# Who:  check.run (the 30-day outcome rule, proposal expiry, material shelf life, the new-entry inbound rule). Moved
#       here unchanged from check.py to keep that file within 250 lines (D86).
# Note: the order is the file name's date prefix → the date in `by` → the day git first saw the file → its mtime;
#       a record's `due` is a separate thing (shapes.due_date) and never moves its age.
# Deps: stdlib (subprocess only to ask git).
import re, subprocess, time
from datetime import date


def git_added(root):
    """{rel: date first committed}; {} when this is not a git repo."""
    try:
        out = subprocess.run(["git", "-c", "core.quotePath=false", "log", "--diff-filter=A", "--format=@%cs", "--name-only"], cwd=str(root),
                             capture_output=True, text=True, encoding="utf-8").stdout
    except OSError:
        return {}
    added, d = {}, None
    for line in out.splitlines():
        if line.startswith("@"):
            d = line[1:]
        elif line.strip() and d:
            added.setdefault(line.strip(), d)
    return added


def age_days(f, fm, added, today):
    """File age: date prefix in the filename → date in the `by` field → date first committed → mtime."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", f["path"].name) or re.search(r"(\d{4}-\d{2}-\d{2})", str(fm.get("by") or ""))
    s = m.group(1) if m else added.get(f["rel"])
    try:
        return (today - date.fromisoformat(s)).days if s else int((time.time() - f["path"].stat().st_mtime) // 86400)
    except ValueError:
        return 0
