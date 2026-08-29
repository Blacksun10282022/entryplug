# 压缩钉子：把「当前处境 · 记录路径 · 当前装备 · 待批提议数 · 回复语言」钉过上下文压缩（不是禁令，挂在闸门层的工程事）。
# 做什么：PreCompact 时算出钉子，写 .kb/pin.md 并打印，写 .kb/hooks/precompact 上次触发时间；
#         SessionStart(matcher=compact) 或 --emit 时把钉子以 additionalContext 注回（D17：PreCompact 的 stdout 不保证进上下文）。
# 输入：stdin 的钩子 JSON（hook_event_name 决定模式；没有 stdin 时按 argv：--emit = 注回，否则 = 钉）；PLUG_ROOT 或向上找 plug.yaml。
# 输出：钉子文本（PreCompact）或 {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": …}}（注回）；退出码 0。
# 不做什么：不注入规则全文、不注入检索结果、不催写（明文禁止）；只钉五行事实，全部从文件推出（最新的记录 + pending 计数 + plug.yaml）。
# 谁调用：Claude Code hooks（PreCompact · SessionStart compact）· Codex hooks 同事件 · contact / acceptance · tests。
# origin：2026-02 一位用户写在指令里的「先确认再动」被压缩丢掉，agent 删空了收件箱；压缩后串英文是真实事故 → 第 5 行是回复语言。
# 依赖：entryplug.config · shapes；未安装时回退到本仓库路径。
# 找不到 plug.yaml → 放行（exit 0，不钉）。
import json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entryplug import config, shapes  # noqa: E402


def pin(cfg):
    recs = sorted(cfg["records_dir"].glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True) if cfg["records_dir"].is_dir() else []
    situation = tool = "（还没有记录）"
    path = "（无）"
    if recs:
        fm, _, _ = shapes.split_frontmatter(recs[0].read_text(encoding="utf-8"))
        fm = fm or {}
        situation, tool, path = str(fm.get("situation") or "?"), str(fm.get("tool") or "?"), config.rel(cfg, recs[0])
    pend = cfg["proposals_dir"] / "pending"
    n = len(list(pend.glob("*.md"))) if pend.is_dir() else 0
    return "\n".join(["[插入栓 · 压缩钉子 · %s]" % time.strftime("%Y-%m-%d %H:%M"), "当前处境：%s" % situation,
                      "记录路径：%s（继续前先 Read 它，不凭印象续；重新判断就写新记录）" % path, "当前装备：%s" % tool,
                      "待批提议：%d 条（%s/pending/）" % (n, cfg["proposals"]), "回复语言：%s" % cfg["language"]])


def main(argv):
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    data = {}
    if not sys.stdin.isatty():
        try:
            data = json.load(sys.stdin)
        except (ValueError, OSError):
            data = {}
    try:
        cfg = config.load(os.environ.get("PLUG_ROOT") or config.find_root(data.get("cwd")))
    except FileNotFoundError:
        print("压缩钉子：找不到 plug.yaml，不钉", file=sys.stderr)
        return 0
    event = data.get("hook_event_name") or ("SessionStart" if "--emit" in argv else "PreCompact")
    if event == "PreCompact":
        text = pin(cfg)
        cfg["pin_path"].parent.mkdir(parents=True, exist_ok=True)
        cfg["pin_path"].write_text(text + "\n", encoding="utf-8")
        cfg["hooks_dir"].mkdir(parents=True, exist_ok=True)
        (cfg["hooks_dir"] / "precompact").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
        print(text)
        return 0
    text = cfg["pin_path"].read_text(encoding="utf-8") if cfg["pin_path"].exists() else pin(cfg)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
