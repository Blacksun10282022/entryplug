# 做什么：命令 `plug` 的入口——五个动词 index · check · apply · eval · search，外加 mcp（stdio 服务）与 hash（算提议的 base）。
# 输入：argv；--root 指内容仓库（否则 PLUG_ROOT / 向上找 plug.yaml）。
# 输出：各动词的文本报告到 stdout（强制 UTF-8，Windows 控制台也不乱码）；退出码 0 = 通过，1 = 有 ERROR / 被拒。
# 不做什么：不含任何领域逻辑；不做交互；不自动定时；不注入任何东西给驾驶员。
# 谁调用：主人（终端）· 驾驶员（Bash）· 钩子脚本（gates/）· .mcp.json（plug mcp）· 测试。
# 约定：每个动词一个模块，这里只做参数分发；模块按需 import，`plug search` 不必加载 check 的代码。
# 退出码：check/eval 有 ERROR → 1；apply 拒绝 → 1；找不到 plug.yaml → 2。
# 形状版本不认识时 index/check/apply/search 一律拒跑（config.version_ok）。
# 依赖：stdlib argparse。
# 版本：entryplug/__init__.py。
import argparse, sys
from . import __version__, SHAPE_VERSION, config


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def parser():
    ap = argparse.ArgumentParser(prog="plug", description="entryplug（插入栓）· 索引 · 查 · 体检 · 批提议 · 评测")
    ap.add_argument("--root", help="内容仓库根（含 plug.yaml）")
    ap.add_argument("--version", action="version", version="entryplug %s · shape v%d" % (__version__, SHAPE_VERSION))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index", help="建 / 增量重建索引，生成 index.md 与打法目录，镜像说明书")
    p.add_argument("--full", action="store_true", help="全量重建")
    p = sub.add_parser("check", help="体检：ERROR / WARNING 清单 + 头部自检 + 一页报告 + 同步率")
    p.add_argument("--contact", choices=["claude-code", "codex"], help="初期接触：接入 smoke 四步")
    p.add_argument("--no-expire", action="store_true", help="不把 30 天未批的提议移到 rejected/")
    p.add_argument("--quiet", action="store_true", help="只打印清单，不打印报告")
    p = sub.add_parser("apply", help="批一条改装申请：核 base → 落地 → 体检 → 提交")
    p.add_argument("proposal")
    p.add_argument("--reject", metavar="REASON", help="驳回：移到 rejected/ 并写一行理由")
    p.add_argument("--dry-run", action="store_true", help="只看 diff，不落地")
    p = sub.add_parser("eval", help="金标 recall@10；中文查询 recall 为零 = ERROR")
    p.add_argument("goldset")
    p.add_argument("--k", type=int, default=10)
    p = sub.add_parser("search", help="查（与 MCP search 同一函数）")
    p.add_argument("queries", nargs="+")
    p.add_argument("--scope", default="tools", choices=["tools", "corpus", "all"])
    p.add_argument("--tool"), p.add_argument("--kind")
    p.add_argument("--k", type=int, default=8), p.add_argument("--per-doc", type=int, default=2)
    p.add_argument("--json", action="store_true")
    sub.add_parser("mcp", help="stdio MCP 服务（唯一工具 search）")
    p = sub.add_parser("hash", help="算文件的 base 短哈希（写提议用）")
    p.add_argument("file")
    return ap


def main(argv=None):
    _utf8()
    a = parser().parse_args(argv)
    try:
        cfg = config.load(a.root)
    except FileNotFoundError as e:
        print("plug: %s" % e, file=sys.stderr)
        return 2
    shape_ok, _ = config.version_ok(cfg)
    if not shape_ok and a.cmd != "check":
        print("plug: plug.yaml 的形状版本 %r 机器不认识（本机 v%d）——拒跑；先 plug check" % (cfg.get("shape_version"), SHAPE_VERSION), file=sys.stderr)
        return 1
    if a.cmd == "index":
        from . import index
        s = index.build(cfg, full=a.full)
        print("index: %d 文件 · %d 块 · 变动 %d · 删除 %d · 教材 %d" % (s["files"], s["chunks"], s["changed"], s["removed"], s["docs"]))
        for e in s["errors"]:
            print("  形状 ERROR " + e)
        return 0
    if a.cmd == "check":
        if a.contact:
            from . import contact
            return contact.run(cfg, a.contact)
        from . import check, report
        r = check.run(cfg, expire=not a.no_expire)
        print(report.format_findings(r) if a.quiet else report.report(cfg, r))
        return 1 if r["errors"] else 0
    if a.cmd == "apply":
        from . import apply
        return apply.run(cfg, a.proposal, reject=a.reject, dry_run=a.dry_run)
    if a.cmd == "eval":
        from . import eval as ev
        return ev.run(cfg, a.goldset, k=a.k)
    if a.cmd == "search":
        from . import search
        res = search.search(cfg, a.queries, scope=a.scope, tool=a.tool, kind=a.kind, k=a.k, per_doc=a.per_doc)
        import json
        print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else search.format_rows(res))
        return 0
    if a.cmd == "mcp":
        from . import mcp
        return mcp.serve(cfg)
    if a.cmd == "hash":
        from . import apply
        print(apply.blob_hash(open(a.file, "rb").read()))
        return 0


if __name__ == "__main__":
    sys.exit(main())
