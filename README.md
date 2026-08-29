# entryplug · 插入栓

一个人把自己的判断做成文件、交给 agent 用时，中间那台机器：三种文件形状、一个只读查询接口、两条机器执行的禁令、一次体检。它不判断、不编排、不自学。附一件《孙子兵法》示例装备，五分钟跑完验收剧本，和一套谁都能复现的小基准。它是我自己在用的东西，不是给所有人准备的通用件。

*Entryplug is the plug any pilot (Claude Code / Codex) inserts into one person's Base (rules, flight log, facts) to fight with that person's Equipment (tools). The owner never pilots; the pilot never edits the Base.* 架构模式叫 **素体—装备 / Base & Equipment**。

## 它做什么（全部在机器里，内容永远不在）

| 动词 | 做什么 |
|---|---|
| `plug index` | 走内容仓库 → 形状校验 → 分块 → jieba 词 + 字二元组 → **一张 FTS5 表**；按文件哈希增量；生成人读的 `index.md`、每件装备的打法目录 `playbooks/INDEX.md`；把说明书镜像到驾驶员的 skills 目录 |
| `plug search` / MCP `search` | 唯一的查询接口，只读：收一条或多组查询 → 别名扩展 → 全文 → round-robin 合并 → 按讲座分组 → 紧凑行（id · 出处 · 文件#L起-L止 · kind · 摘录）。**不重排**：读窗口、打分是驾驶员的事 |
| `plug check` | 体检：ERROR / WARNING 逐项带时间戳，头部自检（形状版本 · 索引新旧 · 钩子上次触发 · 挂了哪些装备），跑装备自带的 `checks/`，30 天没批的改装申请移到 rejected/，一页报告 + 同步率（数字页）。永远没有总分。`--contact claude-code\|codex` = 初期接触四步 |
| `plug apply` | 批一条改装申请：核 base 短哈希 → add / replace / retire → 体检 0 ERROR → git 提交（trailer 记提议 sha）。base 不匹配整体拒绝，绝不静默覆盖 |
| `plug eval` | 金标 recall@10；中文查询 recall 为零 = ERROR |
| `plug init --pilot claude-code\|codex\|both` | 把闸门和驾驶员薄壳装进一个内容仓库：pre-commit 钩子、`.claude/settings.json` 的 deny 规则与钩子（合并，不覆盖）、`.mcp.json`、CLAUDE.md / AGENTS.md 地图（只在缺席时）、说明书镜像、`.codex/hooks.json` 与 `.codex/config.toml`——全部写真实绝对路径；幂等，打印每个文件的动作 |

两条禁令由 `gates/` 执行，不靠提示词：**暴走封锁**（不改规则和装备、不造新装备，只写改装申请）= git pre-commit + Claude Code deny 规则；**出击封锁**（不以主人名义对外做事，先问）= PreToolUse 钩子，Claude Code / Codex 用同一张清单。外加一个压缩钉子。

## 五分钟

```
git clone <this repo> entryplug && pip install -e ./entryplug
cd entryplug
plug --root example-tool index
plug --root example-tool search 诡道
plug --root example-tool check
plug --root example-tool eval bench/public/goldset-sunzi.yaml
python -m pytest            # 每个动词、每道闸门、每种 ERROR 各一组
python tests/acceptance.py  # 验收剧本 C0–C4，机器项 PASS/FAIL，手动项 MANUAL
```

自己的内容仓库照 `example-tool/` 的样子建（`plug.yaml` 是内容仓库里唯一允许出现路径的地方），然后在里面跑 `plug init --pilot both` 装闸门和驾驶员薄壳，再 `plug index` 与 `plug check --contact claude-code`（或 `codex`）四步全绿。接入细节见 `pilots/claude-code/` 与 `pilots/codex/`，闸门见 `gates/README.md`，形状见 `docs/SHAPES.md`。

`plug search` 默认只查词典 · 打法 · 记录；查教材要 `--scope corpus`（MCP 同样是 `scope=corpus`）。没有命中时尾行会说明范围与索引时间；没有索引会直接报「先 plug index」。

## 仓库

```
entryplug/   cli · config · shapes · index · search · mcp · check · numbers · contact · apply · eval（一个文件一个动词，每文件 ≤250 行，没有类和框架）
gates/       precommit · outbound · precompact + 钩子模板
pilots/      claude-code/（插件壳 · 地图 · deny 模板）· codex/（AGENTS.md · 钩子 · 目录链接说明）
example-tool/ 《孙子兵法》示例内容仓库（教材公有领域，其余 CC0）
tests/       每个动词一组、每道闸门一组、每种 ERROR 故意坏一次、防泄漏、验收剧本
bench/       跑分器输入格式 · 公开小金标 · 私有基准登记哈希
docs/        PLAN · DECISIONS · SHAPES
extras/      连接器外挂脚本的位置（不计入行数、不进测试）
```

依赖：Python 3.12 · stdlib（sqlite3 + FTS5）· jieba · PyYAML · git。Windows 原生可用，无编译依赖。向量检索是可选模块 `pip install entryplug[dense]`（本版只有接口桩）。

## 不做什么

不训模型、不让 LLM 给判断打分、没有总分；不写 agent 运行时、规则引擎、匹配器；入库不做 LLM 抽取；没有定时任务、没有无人值守的 LLM 任务；不做插件市场、多用户、云同步、web 查看器。

## 许可与立场

机器 MIT，示例内容 CC0。**开源，不开放贡献**（SQLite 的说法）：接受带复现步骤的 bug 报告，不接功能请求，欢迎 fork，没有路线图。只在自己的验收剧本全过时打 tag；最近一次验证见 `STATUS.md`。
