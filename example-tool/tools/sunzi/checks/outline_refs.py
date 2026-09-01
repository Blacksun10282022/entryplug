# Example equipment check (an equipment brings its own): every "X 篇" a record or a material names must exist in the corpus.
# The machine only provides the mount point: plug check runs this as a subprocess with PLUG_ROOT (content repo
# root) · PLUG_TOOL (equipment name) · PLUG_TOOL_DIR (equipment directory) in the environment.
# Contract: one WARNING per line on stdout; exit 0 = reminders only, 2 = ERROR (which blocks plug apply).
# Read-only, no network, 60 s limit.
import glob, os, re, sys

sys.stdout.reconfigure(encoding="utf-8")
root = os.environ.get("PLUG_ROOT", ".")
tool_dir = os.environ.get("PLUG_TOOL_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
names = set()
for f in glob.glob(os.path.join(tool_dir, "corpus", "raw", "sunzi-*.md")):
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("Title:"):
                names.add(re.sub(r"第.+$", "", line.split("｜")[-1].strip()))
                break
targets = glob.glob(os.path.join(root, "self", "records", "*.md")) + glob.glob(os.path.join(tool_dir, "materials", "*.md"))
for f in sorted(targets):
    with open(f, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            for m in re.finditer(r"([一-鿿]{2})篇", line):
                if m.group(1) not in names:
                    print("%s:%d names 「%s篇」, which the corpus does not have" % (os.path.relpath(f, root).replace(os.sep, "/"), n, m.group(1)))
