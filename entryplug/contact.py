# 做什么：`plug check --contact claude-code|codex`——初期接触（接入 smoke）四步，每步一行结果，带 harness 版本戳：
#         ① 说明书在 skills 目录里可见、description 未被截（≤1,536）；② MCP search 能调通、中文查询非零；
#         ③ 一个假的对外动作被 outbound 钩子拦下并留下「上次触发」；④ 一个假的受保护写入被 deny（Claude Code，核文件）/ pre-commit（两边，真跑）拒绝。
# 输入：cfg · pilot 名。
# 输出：四行 + 结论行（「初期接触，无异常」或「接入坏了，别用（第 N 步）」）；结果追加到数字页末尾；退出码 0 / 1。
# 不做什么：不起 Claude Code / Codex 本身（deny 是否真的拦要在验收剧本里手动核一次）；不改内容；不给分。
# 谁调用：cli（plug check --contact）· tests/acceptance.py（C4）。升级 Claude Code 或 Codex 当天必跑。
# 第 ② 步真的起一个 `plug mcp` 子进程说 JSON-RPC；第 ③④ 步真的跑 gates/ 里的脚本（找不到 gates/ = 机器不是从仓库装的，FAIL）。
# 哪一步失败都算「接入坏了」——harness 升级后产品结构会变，接入会静默坏，这是分钟级的快检；验收剧本是慢的全套。
# 依赖：stdlib subprocess · json；search（取一个真实存在的词做查询）。
import json, os, re, subprocess, sys, time
from pathlib import Path
from . import __version__, config

GATES = Path(__file__).resolve().parents[1] / "gates"
DENY_FILES = (".claude/settings.json", ".claude/settings.local.json")


def harness_version(pilot):
    cmd = {"claude-code": ["claude", "--version"], "codex": ["codex", "--version"]}[pilot]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20, shell=(os.name == "nt"))
        out = (r.stdout or r.stderr).strip()
        return out.splitlines()[0][:48] if out else "版本未知"
    except (OSError, subprocess.TimeoutExpired):
        return "未装或不在 PATH"


def _run(args, cwd, env=None, stdin=None):
    return subprocess.run(args, cwd=str(cwd), env=dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {})), input=stdin,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)


def step_skills(cfg, pilot):
    d = cfg["pilots"].get(pilot, {}).get("skills")
    if not d:
        return False, "plug.yaml 没有给 %s 配 skills 目录" % pilot
    bad = []
    for t in cfg["tools"]:
        src, dst = t["dir"] / "SKILL.md", cfg["root"] / d / t["name"] / "SKILL.md"
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            bad.append("%s 未镜像或已过期（先 plug index）" % t["name"])
            continue
        m = re.search(r"^description:\s*(.+)$", src.read_text(encoding="utf-8"), re.M)
        if not m or len(m.group(1)) > 1536:
            bad.append("%s description 缺失或 >1,536 字符，列表里会被截" % t["name"])
    return (not bad), ("%d 本说明书可见于 %s，description 未截" % (len(cfg["tools"]), d) if not bad else "；".join(bad))


def step_mcp(cfg):
    q = None
    for t in cfg["tools"]:
        for p in sorted((t["dir"] / "dict").glob("*.md")):
            m = re.search(r"^title:\s*(.+)$", p.read_text(encoding="utf-8"), re.M)
            if m and re.search(r"[一-鿿]", m.group(1)):
                q = m.group(1).strip()
                break
        if q:
            break
    if not q:
        return False, "词典里没有中文标题可用作查询"
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search", "arguments": {"query": q, "scope": "all", "k": 3}}}]
    try:
        r = _run([sys.executable, "-m", "entryplug.cli", "--root", str(cfg["root"]), "mcp"], GATES.parent, stdin="".join(json.dumps(m) + "\n" for m in msgs))
        lines = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
        text = lines[1]["result"]["content"][0]["text"]
        n = int(re.search(r"已显示 (\d+)/(\d+)", text).group(2))
    except Exception as e:                                   # 任何异常 = 调不通
        return False, "MCP search 调不通：%s" % e
    return n > 0, "MCP search 通，中文查询「%s」命中 %d 条" % (q, n) if n else "MCP 通了，但中文查询「%s」返回 0 条（分词或索引坏了）" % q


def step_outbound(cfg):
    if not (GATES / "outbound.py").exists():
        return False, "找不到 gates/outbound.py（机器要从仓库 pip install -e）"
    if not cfg["outbound"]:
        return False, "plug.yaml 没有 outbound 清单"
    stamp = cfg["hooks_dir"] / "outbound"
    before = stamp.read_text(encoding="utf-8") if stamp.exists() else None
    time.sleep(1.05)
    fake = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "curl -X POST https://example.invalid/send"}, "cwd": str(cfg["root"])}
    fake2 = {"hook_event_name": "PreToolUse", "tool_name": "mcp__mail__send_email", "tool_input": {"to": "x"}, "cwd": str(cfg["root"])}
    codes = [_run([sys.executable, str(GATES / "outbound.py")], cfg["root"], {"PLUG_ROOT": str(cfg["root"])}, json.dumps(f)).returncode for f in (fake, fake2)]
    after = stamp.read_text(encoding="utf-8") if stamp.exists() else None
    ok = 2 in codes and after is not None and after != before
    return ok, ("假对外动作被拦（exit 2），上次触发 %s" % after) if ok else "假对外动作没被拦（退出码 %s）或没留下上次触发" % codes


def step_protected(cfg, pilot):
    root = cfg["root"]
    if not (GATES / "precommit.py").exists():
        return False, "找不到 gates/precommit.py"
    env = {"PLUG_ROOT": str(root), "PLUG_STAGED": "self/RULES.md"}
    env.pop("KB_APPROVE", None)
    r = _run([sys.executable, str(GATES / "precommit.py")], root, env)
    parts, ok = [], r.returncode == 1 and "暴走封锁" in r.stderr
    parts.append("pre-commit 拒绝了假的受保护写入" if ok else "pre-commit 没拒绝（退出码 %d）" % r.returncode)
    hook = root / ".git" / "hooks" / "pre-commit"
    hp = subprocess.run(["git", "config", "core.hooksPath"], cwd=str(root), capture_output=True, text=True).stdout.strip()
    installed = (hook.exists() and "precommit" in hook.read_text(encoding="utf-8", errors="ignore")) or \
                (hp and (Path(hp) if os.path.isabs(hp) else root / hp).joinpath("pre-commit").exists())
    if not installed:
        ok, parts = False, parts + ["但内容仓库没装 pre-commit 钩子（gates/hooks/pre-commit）"]
    if pilot == "claude-code":
        deny = []
        for f in DENY_FILES:
            p = root / f
            if p.exists():
                try:
                    deny += (json.loads(p.read_text(encoding="utf-8")).get("permissions") or {}).get("deny") or []
                except ValueError:
                    parts.append("%s 不是合法 JSON" % f)
        edits = [d for d in deny if d.startswith("Edit(") and ("RULES.md" in d or "/self/**" in d)]
        if edits:
            parts.append("deny 里有 Edit() 规则护住 self/RULES.md（%d 条 deny）" % len(deny))
        else:
            ok, parts = False, parts + ["deny 里没有 Edit(…self/RULES.md) 规则（模板 pilots/claude-code/settings.template.json）"]
        if any(d.startswith("Write(") for d in deny):
            parts.append("注意：Write() 规则从不被检查，等于没写")
    else:
        parts.append("Codex 没有 permissions.deny，禁令①只有 pre-commit 这一道")
    return ok, "；".join(parts)


def run(cfg, pilot):
    hv = harness_version(pilot)
    steps = [("① 说明书可见", *step_skills(cfg, pilot)), ("② MCP search", *step_mcp(cfg)), ("③ 出击封锁", *step_outbound(cfg)),
             ("④ 受保护写入", *step_protected(cfg, pilot))]
    lines = ["初期接触 · %s · harness %s · entryplug %s · %s" % (pilot, hv, __version__, time.strftime("%Y-%m-%d %H:%M"))]
    lines += ["%s %s · %s" % (name, "OK  " if ok else "FAIL", msg) for name, ok, msg in steps]
    bad = [i + 1 for i, s in enumerate(steps) if not s[1]]
    lines.append("初期接触，无异常" if not bad else "接入坏了，别用（第 %s 步失败）" % "、".join(map(str, bad)))
    print("\n".join(lines))
    np = cfg["numbers_path"]
    if np.parent.exists():
        with open(np, "a", encoding="utf-8") as f:
            f.write("\n初期接触 %s · %s · harness %s：%s\n" % (pilot, time.strftime("%Y-%m-%d"), hv, lines[-1]))
    return 0 if not bad else 1
