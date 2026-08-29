# SHAPES · 形状 v1（字段表）

`shape_version: 1`。三种形状 + 一个规则文件 + 两种索引专用的；只加可选字段，不改必填字段。三种形状的未知键是 ERROR。字段表的真相在 `entryplug/shapes.py` 的 `SHAPES`。

## 内容条目 entry（词典 `dict/*.md` 与打法 `playbooks/*.md` 同一形状）

| 字段 | 必填 | 说明 |
|---|---|---|
| kind | ✓ | concept / method / playbook |
| title | ✓ | 中文进这里；文件名一律 ASCII slug |
| aliases | concept ✓（≥1；<2 是 WARNING） | 中文写法、英文、缩写、教材里的 ASR 误写 |
| situation · when_not · stance | playbook ✓ | 打法的处境 / 反命中 / 姿态（warning · diagnostic · active …）|
| legacy_id · origin | 可选 | 旧 id；来源 |

正文小节：词典 `定义 · 观察 · 关系 · 注`；打法 `原理 · 问题 · 练习 · 信号 / 反模式 / 退出条件`（可有 `动作`）。链接 `[[标题或别名]]`，跨装备 `[[装备名/标题]]`（装备要在 plug.yaml 里声明 depends）。

观察行（`## 观察` 下的 `- ` 行）：

```
- 陈述 [[链接]]* ^pNNNN (src: doc-id#seq "锚句")      有据：锚句必须能在 doc 里 grep 到
- [?] 陈述 … (src: …)                                    未审（迁移对账用）
- 综合一句 ^pNNNN (src: ^p0001 ^p0002)                   综合：引其他行的锚点，必须存在
- 无原句的一句 (src: doc-id p.12 [未锚])                 只能来自主人批过的提议
```

## 记录 record（驾驶日志 `self/records/<日期>-<slug>.md`）

| 字段 | 必填 | 说明 |
|---|---|---|
| tool · by · situation · verdict | ✓ | by = 驾驶员 · 模型 · 日期；verdict 先写，主人看之前落盘 |
| chosen · outcome | 后补 | chosen = 主人选了什么（同意 / 同 verdict / 另一句）；outcome 里可写「它对 / 我对 / 说不清」|

正文三个固定小节：`依据`（点名的 R-id 必须存在；引 `records/…` 算引记录；带 `(src: doc#seq "原句")` 或 `^pNNNN` 算引文）· `最强反证` · `什么会改判`。分歧 = verdict ≠ chosen，现算不存。

## 提议 proposal（改装申请 `proposals/pending/<日期>-<slug>.md`）

| 字段 | 必填 | 说明 |
|---|---|---|
| target | ✓ | 目标文件路径（新文件也写路径）|
| base | ✓ | 目标文件当前内容的 git blob 短哈希（`plug hash <file>`）；新建写 `new` |
| from | ✓ | 触发它的记录路径，或「学:doc-id」|

正文三段：`改成什么`（整文件 ```` ```md ```` 代码块，或第一行 `retire`）· `为什么` · `最强反证`。批过的进 `applied/`，驳回 / 过期的进 `rejected/`（末尾一行 `rejected: 日期 · 理由`）。

## 规则文件 self/RULES.md（不是形状，一个文件）

文件头 `model: … reviewed: YYYY-MM-DD`；`## 小节` = 等级；每行 `- R12 · 陈述 [YYYY-MM · 来源]`；小节标题或行内的 `到期 YYYY-MM-DD`（过期整节失效 → WARNING）与 `复核 YYYY-MM`（已过 → WARNING）机器会读；文末 `## 已退役`。

## 资料 material（`tools/<t>/materials/*.md`）

`date`（必填，YYYY-MM-DD）· `kind`（保质期按 kind 查 plug.yaml 的 `ttl_days`）· `title` · `source` 可选。过期 = WARNING，用时报日期。

## 索引专用（不写文件）

- **doc**：从教材文件推出——`id`（frontmatter id → 头部 `BVID:` / `ID:` → 文件名）· `title` · `date` · `kind` · `speaker` · `series`（标题第一个分隔符前的原样前缀）。三种文件：frontmatter 文本；讲座（`Title / BVID / Date` 头 + `==== 纯文本 ====`，只索引这一段）；清洗稿（6 行头 + `====` + `[m:ss]` / `[¶n]` 段落）。
- **chunk**：所属 doc · 序号（段落号；单段文档为窗口号）· 行号范围 · 位置（时间戳）。

## plug.yaml

`machine`（钉机器版本）· `shape_version` · `self` · `proposals` · `index` · `index_md` · `numbers` · `hooks` · `pin` · `language` · `tools[{name, path, depends, ttl_days, unreviewed}]` · `pilots{name: {skills}}` · `outbound[{tool, match, reason}]` · `protected` / `unprotected`。内容仓库里唯一允许出现路径的地方。
