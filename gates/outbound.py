# 出击封锁（禁令②）：PreToolUse 钩子——不以主人名义对外做任何事，一律先问。
# 做什么：读钩子传来的 JSON（tool_name · tool_input · cwd），对照 plug.yaml 的 outbound 清单（tool 正则 + 可选 match 正则）；
#         命中 → stderr 一行理由，写 .kb/hooks/outbound 上次触发时间，exit 2（阻断，驾驶员看到理由）；没命中 → exit 0。
# 输入：stdin 的钩子 JSON；PLUG_ROOT 或从 cwd 向上找 plug.yaml。
# 输出：退出码 0 / 2；理由一行。
# 不做什么：不改写工具输入（明文禁止 updatedInput）；不读内容；找不到 plug.yaml 或 JSON 坏了就放行（钩子本来 fail-open，第二道是「能对外的工具本来就不给它」）。
# 谁调用：Claude Code hooks（pilots/claude-code/hooks/hooks.json）· Codex hooks（pilots/codex/hooks.json）——同一份清单、同一个脚本 · contact 第 3 步 · tests。
# 交互时阻塞式先问；无人值守（-p + ask 规则）官方语义是「自动拒绝、继续跑」，不挂起。
# 依赖：entryplug.config；未安装时回退到本仓库路径。
# 一个钩子一个动词；拒绝理由一行。
import json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entryplug import config  # noqa: E402


def match(rules, tool_name, tool_input):
    """命中清单里的一条 → 返回那条的说明；否则 None。"""
    blob = tool_input if isinstance(tool_input, str) else json.dumps(tool_input, ensure_ascii=False)
    for rule in rules or []:
        try:
            if re.search(rule.get("tool", ""), tool_name or "") and (not rule.get("match") or re.search(rule["match"], blob)):
                return rule.get("reason") or "tool=%s%s" % (rule.get("tool"), " match=%s" % rule["match"] if rule.get("match") else "")
        except re.error:
            continue
    return None


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        data = {}
    try:
        cfg = config.load(os.environ.get("PLUG_ROOT") or config.find_root(data.get("cwd")))
    except FileNotFoundError:
        print("出击封锁：找不到 plug.yaml，放行（fail-open）", file=sys.stderr)
        return 0
    reason = match(cfg["outbound"], data.get("tool_name", ""), data.get("tool_input", {}))
    if reason is None:
        return 0
    cfg["hooks_dir"].mkdir(parents=True, exist_ok=True)
    (cfg["hooks_dir"] / "outbound").write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    print("出击封锁：%s 是对外动作（清单 %s）——不以主人名义对外做任何事，先问主人再做" % (data.get("tool_name"), reason), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
