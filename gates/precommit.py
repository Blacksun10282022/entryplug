# 暴走封锁（禁令①）最硬的一道：git pre-commit。
# 做什么：提交触及受保护路径（默认 self/RULES.md · self/facts/** · tools/**，教材目录除外；见 plug.yaml protected/unprotected）
#         且没有 KB_APPROVE=1 → 拒绝，一行理由；其余提交：重建索引 + 体检 0 ERROR 才放行；写 .kb/hooks/precommit 上次触发时间。
# 输入：git 暂存区（git diff --cached --name-only）；测试与初期接触可用环境变量 PLUG_STAGED（换行分隔的路径）代替 git。
# 输出：退出码 0 放行 / 1 拒绝；理由一行打到 stderr。找不到 plug.yaml 也拒绝（这一道 fail-closed）。
# 不做什么：不读不改内容；不区分谁在提交（主人也一样：批准 = plug apply，它会设 KB_APPROVE=1）；不 git add 生成物（D19）。
# 谁调用：内容仓库的 .git/hooks/pre-commit（模板 gates/hooks/pre-commit，一行 exec python <本文件>）· contact 第 4 步 · tests。
# 跨 harness：Claude Code、Codex、任何脚本直写都过这一道；Codex 没有 permissions.deny，这是它那边禁令①唯一的一道。
# 依赖：entryplug（pip install -e .）；未安装时回退到本仓库路径。
# 记录 / 提议 / 教材 / 资料以外的 tools/** 都受保护——驾驶员随时可写可提交的只有 records/ proposals/ corpus/。
import os, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entryplug import config  # noqa: E402


def staged(root):
    env = os.environ.get("PLUG_STAGED")
    if env is not None:
        return [l.strip().replace("\\", "/") for l in env.splitlines() if l.strip()]
    r = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRD"], cwd=str(root),
                       capture_output=True, text=True, encoding="utf-8")
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def stamp(cfg, name):
    cfg["hooks_dir"].mkdir(parents=True, exist_ok=True)
    (cfg["hooks_dir"] / name).write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    try:
        cfg = config.load(os.environ.get("PLUG_ROOT") or config.find_root())
    except FileNotFoundError as e:
        print("暴走封锁：%s——没有 plug.yaml 的仓库不该装这个钩子；先修配置" % e, file=sys.stderr)
        return 1
    files = staged(cfg["root"])
    stamp(cfg, "precommit")
    hit = [f for f in files if config.is_protected(cfg, f)]
    if hit and os.environ.get("KB_APPROVE") != "1":
        more = "（共 %d 个）" % len(hit) if len(hit) > 1 else ""
        print("暴走封锁：提交触及受保护路径 %s%s——规则和装备只能写改装申请（proposals/pending/）；主人批准 = plug apply" % (hit[0], more), file=sys.stderr)
        return 1
    from entryplug import check, index
    index.build(cfg)
    r = check.run(cfg, expire=False)
    if r["errors"]:
        e = r["errors"][0]
        print("体检 %d 个 ERROR，提交被拒：%s · %s · %s" % (len(r["errors"]), e["code"], e["file"], e["msg"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
