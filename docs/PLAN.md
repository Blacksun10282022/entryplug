# PLAN · entryplug（插入栓）模块边界

目标：≈1,000 行（≤ ~1,300）的机器，一个文件一个动词，每文件 ≤250 行，无类框架、无装饰器魔法。
依赖：stdlib（sqlite3 + FTS5）· jieba · PyYAML · git。MCP 用 stdio JSON-RPC 手写（≈70 行），不依赖 mcp 包。

## 包 `entryplug/`

| 文件 | 动词 / 职责 | 输入 → 输出 | 调用者 |
|---|---|---|---|
| `config.py` | 找 plug.yaml、解析路径、常量（形状版本、机器版本、默认目录） | root → cfg dict | 所有动词 |
| `shapes.py` | 形状：frontmatter 解析、字段表、逐文件校验、观察行 / 规则行 / [[链接]] 解析 | 文件文本 → 结构 + 错误列表 | index · check · apply |
| `index.py` | `plug index`：走内容仓库 → 形状校验 → 分块（600/100；清洗稿按段落）→ tokens（jieba 词 + 字二元组）→ 一张 FTS5 表；按文件哈希增量；生成 index.md + playbooks/INDEX.md；镜像 SKILL.md 到驾驶员 skills 目录 | cfg → sqlite + 两个 md | cli · precommit |
| `search.py` | `plug search` = MCP `search` 同一函数：多组查询 → 别名扩展 → FTS5 OR → round-robin 合并 → 按讲座分组 → 紧凑行；不重排 | queries → rows + 尾行 | cli · mcp · eval · contact |
| `mcp.py` | stdio JSON-RPC 服务，唯一工具 `search` | stdin → stdout | 驾驶员（.mcp.json） |
| `check.py` | `plug check`：ERROR / WARNING 清单（带时间戳）· 头部自检 · 跑工具 checks/ · 30 天未批提议移到 rejected · 一页报告 | cfg → findings + report | cli · precommit · apply |
| `numbers.py` | 同步率（数字页）：从 records 算机械准与同意率，写 self/数字.md；永远没有总分 | records + git 历史 → md | check |
| `contact.py` | `plug check --contact <pilot>`：初期接触四步 smoke | cfg + pilot → 四行结果 | cli |
| `apply.py` | `plug apply <proposal>`：核 base 短哈希 → add / replace / retire → check 0 ERROR → git commit（trailer 记提议 sha）；`--reject` 移到 rejected | proposal → commit | 主人 |
| `eval.py` | `plug eval <goldset.yaml>`：recall@10；中文查询 recall 为零 = ERROR | goldset → 表 | 主人 · bench |
| `init.py` | `plug init --pilot …`：把 pre-commit 钩子、deny 规则与钩子（合并）、.mcp.json、地图、说明书镜像、.codex 配置装进内容仓库（真实绝对路径、幂等） | cfg + pilot → 文件动作清单 | 主人 · acceptance |
| `report.py` | check 结果的排版：逐项清单 + 一页报告 | check.run 结果 → 文本 | cli · apply |
| `cli.py` | argparse 分发五个动词 + `mcp` · `init` · `hash`；stdout 强制 UTF-8 | argv → exit code | 命令 `plug` |

## 仓库其余

- `gates/precommit.py`（暴走封锁：受保护路径无 KB_APPROVE=1 即拒；顺带 check 0 ERROR + 重建索引）· `gates/outbound.py`（出击封锁：PreToolUse，按 plug.yaml 的 outbound 清单 exit 2）· `gates/precompact.py`（压缩钉子：当前处境 · 记录路径 · 当前工具 · 待批提议数 · 回复语言）。每个钩子写 `.kb/hooks/<name>` 上次触发时间。
- `pilots/claude-code/`：plugin.json · hooks.json · .mcp.json · CLAUDE.md 地图模板 · settings.deny 模板（只用 Edit()/Read()，占位路径 `//c/<content-repo>/...`）。
- `pilots/codex/`：AGENTS.md 模板 · `.agents/skills` 目录链接说明 · hooks.json（同一张 outbound 清单，同一个脚本）。
- `example-tool/`：《孙子兵法》示例内容仓库（plug.yaml · self/ · tools/sunzi/ · proposals/），CC0。
- `tests/`：每个动词一组、每道闸门一组、每种 ERROR 故意坏一次、`acceptance.py`（C1–C4，手动项标 MANUAL）、`test_no_leak.py`。
- `bench/`：registry.md 骨架 + 公开小金标（示例工具）+ 金标 yaml 格式说明。

## 数据落点（内容仓库）

`.kb/index.sqlite`（gitignored）· `.kb/hooks/*`（上次触发）· `.kb/pin.md`（压缩钉子）· `index.md`（人读索引）· `tools/<t>/playbooks/INDEX.md` · `self/数字.md`。

## 顺序

config + shapes → example-tool → index + search + cli → mcp → check + numbers → apply → eval + bench → gates + pilots + contact → no-leak + acceptance + README/STATUS。每步一个 commit。
