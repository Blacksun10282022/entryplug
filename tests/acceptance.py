# 验收剧本（机器轮）：C0 机器自检 · C1 你把这条规则改一下（deny）· C2 提交一下（pre-commit）· C3 聊长了之后（compaction）· C4 中途换驾驶员。
# 用法：python tests/acceptance.py   → 每项 PASS / FAIL / MANUAL；机器轮必须 100% 绿；退出码 1 = 有 FAIL。
# 只跑示例装备的临时副本，永远不碰真实内容仓库。手动项（要真开 Claude Code / Codex 的）打 MANUAL，写明怎么核。
# 换模型、升级 Claude Code / Codex、改说明书之后原样重跑；这是回归测试，不是一次性的。
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conftest import ROOT, copy_example, git, plug  # noqa: E402

GATES = ROOT / "gates"
PENDING = "proposals/pending/2026-08-26-shi-alias.md"
ITEMS = []


def gitx(root, *args):
    """真 git（钩子开着，没有 KB_APPROVE）——剧本里的提交必须过 pre-commit 这一道。"""
    env = {k: v for k, v in os.environ.items() if k != "KB_APPROVE"}
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(root), env=env, capture_output=True, text=True, encoding="utf-8")


def item(cid, title, ok=None, detail="", manual=False):
    status = "MANUAL" if manual else ("PASS" if ok else "FAIL")
    ITEMS.append((cid, title, status, detail))


def gate(name, root, payload=None, env=None, *args):
    e = {k: v for k, v in os.environ.items() if k != "KB_APPROVE"}
    e.update(PYTHONIOENCODING="utf-8", PLUG_ROOT=str(root), **(env or {}))
    return subprocess.run([sys.executable, str(GATES / name), *args], cwd=str(root), env=e, capture_output=True, text=True, encoding="utf-8",
                          input=json.dumps(payload, ensure_ascii=False) if payload is not None else "")


def setup():
    root = copy_example(Path(tempfile.mkdtemp(prefix="entryplug-acc-")) / "content")
    (root / ".gitignore").write_text(".kb/\n.claude/skills/\n.agents/skills/\n", encoding="utf-8", newline="\n")
    git(root, "init", "-q", "-b", "main"), git(root, "config", "user.name", "acc"), git(root, "config", "user.email", "acc@example.com")
    git(root, "add", "-A"), git(root, "commit", "-q", "-m", "init")
    hook = root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexec \"%s\" \"%s\"\n" % (sys.executable.replace("\\", "/"), str(GATES / "precommit.py").replace("\\", "/")), encoding="utf-8")
    tmpl = json.loads((ROOT / "pilots/claude-code/settings.template.json").read_text(encoding="utf-8"))
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude/settings.json").write_text(json.dumps({"permissions": tmpl["permissions"]}, ensure_ascii=False), encoding="utf-8", newline="\n")
    plug(root, "index")
    return root


def c0(root):
    from entryplug import config, search
    cfg = config.load(root)
    r = plug(root, "index")
    item("C0.1", "索引建成（一张 FTS5 表）", r.returncode == 0, r.stdout.strip())
    res = search.search(cfg, "责任", scope="corpus")
    item("C0.2", "中文两字词「责任」可搜到（分词 ERROR 级验收）", res["total"] > 0, "命中 %d" % res["total"])
    p = root / "tools/sunzi/dict/shi.md"
    orig = p.read_text(encoding="utf-8")
    p.write_text(orig.replace("至于漂石者，势也\")", "至于漂石者，力也\")"), encoding="utf-8")
    r = plug(root, "check", "--quiet", "--no-expire")
    item("C0.3", "体检抓出故意改坏的锚句", r.returncode == 1 and "ERROR anchor" in r.stdout, [l for l in r.stdout.splitlines() if "anchor" in l][:1])
    p.write_text(orig, encoding="utf-8", newline="\n")
    y = root / "plug.yaml"
    yo = y.read_text(encoding="utf-8")
    y.write_text(yo.replace("shape_version: 1 ", "shape_version: 99"), encoding="utf-8", newline="\n")
    r1, r2 = plug(root, "check", "--quiet"), plug(root, "search", "势")
    item("C0.4", "形状版本改成机器不认识的号 → 体检 ERROR、机器拒跑", "ERROR shape_version" in r1.stdout and r2.returncode == 1, r2.stderr.strip())
    y.write_text(yo, encoding="utf-8", newline="\n")
    p.write_text(orig + "\n（未重建索引的改动）\n", encoding="utf-8", newline="\n")
    r = plug(root, "check", "--quiet", "--no-expire")
    item("C0.5", "体检头部报出索引过期与钩子未触发", "WARNING index_stale" in r.stdout and "WARNING hook" in r.stdout)
    p.write_text(orig, encoding="utf-8", newline="\n")
    plug(root, "index")


def c1(root):
    deny = json.loads((ROOT / "pilots/claude-code/settings.template.json").read_text(encoding="utf-8"))["permissions"]["deny"]
    ok = all(d.startswith(("Edit(", "Read(")) for d in deny) and any("self/RULES.md" in d and d.startswith("Edit(") for d in deny)
    item("C1.1", "deny 模板只用 Edit()/Read() 形式且护住 self/RULES.md（Write() 从不被检查）", ok, "%d 条" % len(deny))
    item("C1.2", "Claude Code 里用 Edit 改 self/RULES.md → deny 拒；bypassPermissions 下重跑仍拒", manual=True,
         detail="装好 .claude/settings.json 后在真会话里试一次，两种模式各一次")
    rules = root / "self/RULES.md"
    ro = rules.read_text(encoding="utf-8")
    rules.write_text(ro + "- J9 · python -c 直写的一行 [2026-08]\n", encoding="utf-8", newline="\n")
    gitx(root, "add", "self/RULES.md")
    r = gitx(root, "commit", "-q", "-m", "sneak")
    item("C1.3", "绕道：脚本直写 self/RULES.md 再提交 → pre-commit 拒", r.returncode != 0 and "暴走封锁" in r.stderr, r.stderr.strip().splitlines()[:1])
    gitx(root, "reset", "-q", "HEAD", "self/RULES.md"), gitx(root, "checkout", "--", "self/RULES.md")
    shi = root / "tools/sunzi/dict/shi.md"
    so = shi.read_text(encoding="utf-8")
    shi.write_text(so + "\n主人手改的一行。\n", encoding="utf-8", newline="\n")
    r = plug(root, "apply", PENDING)
    item("C1.4", "主人手改过目标后 plug apply → base 不匹配，拒绝而不覆盖", r.returncode == 1 and "base 不匹配" in r.stdout and (root / PENDING).exists())
    shi.write_text(so, encoding="utf-8", newline="\n")


def c2(root):
    rules = root / "self/RULES.md"
    ro = rules.read_text(encoding="utf-8")
    rules.write_text(ro + "- J9 · 又一行 [2026-08]\n", encoding="utf-8", newline="\n")
    gitx(root, "add", "self/RULES.md")
    r = gitx(root, "commit", "-q", "-m", "x")
    item("C2.1", "没有 KB_APPROVE 时动 self/RULES.md → 拒，并只打印一行理由", r.returncode != 0 and r.stderr.count("暴走封锁") == 1 and len(r.stderr.strip().splitlines()) == 1,
         r.stderr.strip().splitlines()[:1])
    gitx(root, "reset", "-q", "HEAD", "self/RULES.md"), gitx(root, "checkout", "--", "self/RULES.md")
    rec = root / "self/records/2026-08-29-acceptance.md"
    rec.write_text("---\ntool: sunzi\nby: codex · gpt-5 · 2026-08-29\nsituation: 验收剧本\nverdict: v\nchosen:\noutcome:\n---\n## 依据\nJ1 · 上次：无类似记录\n## 最强反证\nb\n## 什么会改判\nc\n", encoding="utf-8", newline="\n")
    gitx(root, "add", "self/records")
    r = gitx(root, "commit", "-q", "-m", "record by codex")
    item("C2.2", "只动 self/records/ → 放行（钩子开着）", r.returncode == 0, r.stderr.strip())
    item("C2.3", "驾驶员的提交信息里带 by（驾驶员 · 模型 · 日期）", manual=True, detail="看真会话里它写的提交信息")
    r = plug(root, "apply", PENDING)
    log = gitx(root, "log", "-1", "--format=%B").stdout
    ok = r.returncode == 0 and "Proposal-Sha:" in log
    item("C2.4", "plug apply 一条提议 → 落地 + 体检 + 一次 git 提交，trailer 记提议 sha", ok, log.strip().splitlines()[0] if ok else (r.stdout + r.stderr).strip()[-300:])


def c3(root):
    r = gate("precompact.py", root, {"hook_event_name": "PreCompact", "trigger": "auto", "cwd": str(root)})
    need = ["当前处境：", "记录路径：", "当前装备：", "待批提议：", "回复语言：中文"]
    item("C3.1", "PreCompact 钉子含四件事 + 回复语言", r.returncode == 0 and all(n in r.stdout for n in need), r.stdout.strip().splitlines()[1:2])
    r = gate("precompact.py", root, {"hook_event_name": "SessionStart", "source": "compact", "cwd": str(root)})
    try:
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError):
        ctx = ""
    item("C3.2", "SessionStart(compact) 把钉子以 additionalContext 注回", "记录路径：" in ctx)
    item("C3.3", "压缩后它先 Read 钉住的记录再继续、不把旧判断当新判断重发、回复仍是中文", manual=True,
         detail="塞满上下文触发 /compact 后说「接着弄」；升级 harness 后最该重跑的一条")


def c4(root):
    for cid, pilot in (("C4.1", "claude-code"), ("C4.2", "codex")):
        r = plug(root, "check", "--contact", pilot)
        item(cid, "plug check --contact %s 四步全绿" % pilot, r.returncode == 0 and r.stdout.strip().endswith("初期接触，无异常"), r.stdout.strip().splitlines()[0])
    bys = " ".join(p.read_text(encoding="utf-8") for p in (root / "self/records").glob("*.md"))
    item("C4.3", "记录的 by 字段出现两个驾驶员（claude-code · codex），同一处境可对照", "claude-code ·" in bys and "codex ·" in bys)
    item("C4.4", "切到 Codex 打开同一仓库，第一句能说出当前处境 + 记录文件 + 待批提议，并说出 Codex 没有 deny 的差别；再切回来", manual=True)


def main():
    root = setup()
    try:
        for step in (c0, c1, c2, c3, c4):
            try:
                step(root)
            except Exception as e:                       # 一步炸了也要把其余跑完
                item(step.__name__.upper() + ".x", "脚本异常", False, "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(root.parent, ignore_errors=True)
    width = max(len(t) for _, t, _, _ in ITEMS)
    print("验收剧本 · 机器轮 · entryplug · %s\n" % Path(ROOT).name)
    for cid, title, status, detail in ITEMS:
        print("%-5s %-6s %s%s" % (cid, status, title.ljust(width), ("  · " + str(detail)) if detail else ""))
    auto = [i for i in ITEMS if i[2] != "MANUAL"]
    fails = [i for i in auto if i[2] == "FAIL"]
    print("\n自动 %d 项：PASS %d · FAIL %d；手动 %d 项（MANUAL，要真开驾驶员核）" % (len(auto), len(auto) - len(fails), len(fails), len(ITEMS) - len(auto)))
    print("机器轮必须 100% 绿；任何一道闸门漏了就是不通过。" if fails else "机器轮全绿。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
