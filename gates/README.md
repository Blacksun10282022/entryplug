# gates · 两道封锁 + 压缩钉子

三个脚本，一个钩子一个动词，拒绝理由一行，每个都写 `.kb/hooks/<name>` 上次触发时间（`plug check` 头部会报「最近没触发」）。

| 脚本 | 禁令 | 挂在哪 | 硬度 |
|---|---|---|---|
| `precommit.py` | ① 暴走封锁：不改规则和装备、不造新装备，只写改装申请 | 内容仓库 `.git/hooks/pre-commit`（模板 `hooks/pre-commit`） | 最硬：跨 harness、跨语言，脚本直写也拦 |
| `outbound.py` | ② 出击封锁：不以主人名义对外做事，先问 | PreToolUse（Claude Code `pilots/claude-code/hooks/hooks.json` · Codex `pilots/codex/hooks.json`），同一张清单 `plug.yaml: outbound` | 钩子 fail-open；第二道是能对外的工具本来就不给它 |
| `precompact.py` | （不是禁令）压缩钉子 | PreCompact + SessionStart(compact) | 只钉五行事实 |

三道防线按硬度：pre-commit ＞ permissions.deny（只有 Claude Code 有；`Edit(path)` 形式，见 `pilots/claude-code/settings.template.json`）＞ 钩子。原生 Windows 没有沙箱，deny 挡不住子进程直写，所以 pre-commit 是唯一密不透风的一层。

## 安装（每个内容仓库一次）

```
cp gates/hooks/pre-commit <内容仓库>/.git/hooks/pre-commit   # 改里面的路径
# Claude Code：把 pilots/claude-code/settings.template.json 合进 <内容仓库>/.claude/settings.json，改占位路径
# Codex：把 pilots/codex/hooks.json 合进 ~/.codex/hooks.json（或仓库级），改占位路径；每个钩子要手动信任一次
plug check --contact claude-code     # 初期接触四步，全绿才算接上
plug check --contact codex
```

规矩：钩子不改写工具输入（updatedInput）、不往 prompt 塞检索结果、不开机注入规则全文、没有 Stop 钩子催写。
