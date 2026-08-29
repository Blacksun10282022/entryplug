# 做什么：`plug init --pilot claude-code|codex|both`——把闸门和驾驶员薄壳装进一个内容仓库：pre-commit 钩子 · .claude/settings.json（deny 规则 + 钩子，合并不覆盖）
#         · .mcp.json · CLAUDE.md / AGENTS.md 地图（只在缺席时）· 说明书镜像 + agents/openai.yaml · .codex/hooks.json 与 .codex/config.toml（合并）· .gitignore 三行。
# 输入：cfg · pilot。机器位置 = 本包所在的仓库（gates/ 必须在）；解释器 = 当前 python（它装着 entryplug）。
# 输出：每个文件一行 写入 / 更新 / 已是最新 / 跳过 / 备份；退出码 0。重复运行幂等。
# 不做什么：不碰内容（self/ tools/ proposals/）；不改 plug.yaml；不写用户家目录（~/.codex 由主人自己合并）；不覆盖别人的 pre-commit（改名备份）。
# 谁调用：主人（每个内容仓库一次）· tests · acceptance（装好后 plug check --contact 应全绿）。
# 路径（D34）：生成的驾驶员文件里是真实绝对路径——deny 规则要 //c/… 形式，钩子命令用当前解释器的绝对路径；这些文件是本机的。
# 钩子装在 .git/hooks/pre-commit（git pull 不动它，Windows 下 git 用 sh 跑）；主人设了 core.hooksPath 就装到那个目录。
# 钩子写进 settings.json 的 hooks（Claude Code 不读 .claude/hooks.json；插件形式见 pilots/claude-code/）。
# 依赖：stdlib json · subprocess（只问 git）· config · index.mirror_skills。
import json, os, re, shutil, subprocess, sys
from pathlib import Path
from . import config, index

REPO, PY = Path(__file__).resolve().parents[1], Path(sys.executable).as_posix()
PROTECT = ["self/RULES.md", "self/facts/**", "self/style.md", "tools/**/SKILL.md", "tools/**/dict/**", "tools/**/playbooks/**",
           "tools/**/materials/**", "tools/**/checks/**", "plug.yaml"]


def posix_abs(p):
    """D:/dir/x → //d/dir/x（Claude Code 的绝对 deny 规则写法）；非 Windows 原样。"""
    return re.sub(r"^([A-Za-z]):", lambda m: "//" + m.group(1).lower(), Path(p).resolve().as_posix())


def put(path, text, log):
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return log.append(("已是最新", path))
    path.write_text(text, encoding="utf-8", newline="\n")
    log.append(("更新" if old is not None else "写入", path))


def merge_json(path, mutate, log):
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    mutate(data)
    put(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", log)


def copy_if_absent(src, dst, log):
    log.append(("跳过（已存在）", dst)) if dst.exists() else put(dst, src.read_text(encoding="utf-8"), log)


def hook_cmd(script, *args):
    return '"%s" "%s"%s' % (PY, (REPO / "gates" / script).as_posix(), "".join(" " + a for a in args))


def merge_hooks(d):
    """三个钩子（出击封锁 · 压缩钉子 · 注回）合进 hooks；同一条命令已在就不重复。"""
    want = {"PreToolUse": [{"matcher": "Bash|WebFetch|mcp__.*", "hooks": [{"type": "command", "command": hook_cmd("outbound.py"), "timeout": 30}]}],
            "PreCompact": [{"hooks": [{"type": "command", "command": hook_cmd("precompact.py"), "timeout": 30}]}],
            "SessionStart": [{"matcher": "compact", "hooks": [{"type": "command", "command": hook_cmd("precompact.py", "--emit"), "timeout": 30}]}]}
    hooks = d.setdefault("hooks", {})
    for event, groups in want.items():
        have = hooks.setdefault(event, [])
        for g in groups:
            if not any(h.get("command") == g["hooks"][0]["command"] for x in have for h in x.get("hooks", [])):
                have.append(g)


def install_hook(cfg, log):
    root = cfg["root"]
    if not (root / ".git").exists():
        return log.append(("跳过", "pre-commit：不是 git 仓库（先 git init 再 plug init）"))
    hp = subprocess.run(["git", "config", "core.hooksPath"], cwd=str(root), capture_output=True, text=True).stdout.strip()
    target = ((Path(hp) if os.path.isabs(hp) else root / hp) if hp else root / ".git" / "hooks") / "pre-commit"
    if target.exists() and "precommit.py" not in target.read_text(encoding="utf-8", errors="ignore"):
        shutil.move(str(target), str(target) + ".before-entryplug")
        log.append(("备份", target.with_name("pre-commit.before-entryplug")))
    put(target, "#!/bin/sh\n# entryplug 暴走封锁——plug init 写入，重复运行会覆盖。不要 --no-verify，不要手设 KB_APPROVE。\nexec %s\n" % hook_cmd("precommit.py"), log)
    os.chmod(target, 0o755)


def gitignore(cfg, log):
    p = cfg["root"] / ".gitignore"
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    need = [x for x in [Path(cfg["index"]).parts[0] + "/"] + [v["skills"].rstrip("/") + "/" for v in cfg["pilots"].values()] if x not in old.splitlines()]
    put(p, old.rstrip("\n") + ("\n" if old else "") + "\n".join(need) + "\n", log) if need else log.append(("已是最新", p))


def claude(cfg, log):
    root, base = cfg["root"], posix_abs(cfg["root"])
    rules = ["Edit(%s/%s)" % (base, x) for x in PROTECT] + ["Read(%s/%s/**)" % (base, cfg["hooks"])]
    def mutate(d):
        deny = d.setdefault("permissions", {}).setdefault("deny", [])
        deny.extend(x for x in rules if x not in deny)
        merge_hooks(d)
    merge_json(root / ".claude" / "settings.json", mutate, log)
    server = {"command": PY, "args": ["-m", "entryplug.cli", "--root", root.as_posix(), "mcp"], "env": {"PYTHONIOENCODING": "utf-8"}}
    merge_json(root / ".mcp.json", lambda d: d.setdefault("mcpServers", {}).setdefault("entryplug", server), log)
    copy_if_absent(REPO / "pilots" / "claude-code" / "CLAUDE.md", root / "CLAUDE.md", log)


def codex(cfg, log):
    copy_if_absent(REPO / "pilots" / "codex" / "AGENTS.md", cfg["root"] / "AGENTS.md", log)
    merge_json(cfg["root"] / ".codex" / "hooks.json", merge_hooks, log)
    toml = cfg["root"] / ".codex" / "config.toml"
    old = toml.read_text(encoding="utf-8") if toml.exists() else ""
    if "[mcp_servers.entryplug]" in old:
        return log.append(("已是最新", toml))
    put(toml, old.rstrip("\n") + ("\n\n" if old else "") + '[mcp_servers.entryplug]\ncommand = "%s"\nargs = ["-m", "entryplug.cli", "--root", "%s", "mcp"]\n' % (PY, cfg["root"].as_posix()), log)


def run(cfg, pilot):
    if not (REPO / "gates").is_dir():
        print("init: 找不到 gates/——机器要从仓库装（pip install -e <entryplug>）")
        return 1
    log = []
    install_hook(cfg, log), gitignore(cfg, log)
    if pilot in ("claude-code", "both"):
        claude(cfg, log)
    if pilot in ("codex", "both"):
        codex(cfg, log)
    index.mirror_skills(cfg)
    log.append(("镜像", "说明书 → " + " · ".join(v["skills"] for v in cfg["pilots"].values())))
    for status, path in log:
        shown = path if isinstance(path, str) else (config.rel(cfg, path) if cfg["root"] in path.resolve().parents else str(path))
        print("%-10s %s" % (status, shown))
    print("下一步：plug index → plug check --contact %s" % ("claude-code 与 codex" if pilot == "both" else pilot))
    return 0
