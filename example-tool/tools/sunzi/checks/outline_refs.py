# 示例挂点（装备自带的检查）：记录与资料里点名的「X 篇」必须在教材里存在。
# 机器只提供挂点：plug check 以子进程跑本脚本，环境变量 PLUG_ROOT（内容仓库根）· PLUG_TOOL（装备名）· PLUG_TOOL_DIR（装备目录）。
# 约定：stdout 每行一条 WARNING；退出码 0 = 只有提醒，2 = ERROR（阻断批提议）。只读、无网络、限时 60 s。
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
                    print("%s:%d 点名的「%s篇」教材里没有" % (os.path.relpath(f, root).replace(os.sep, "/"), n, m.group(1)))
