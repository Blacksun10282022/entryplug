# 修机器的说明书（≤30 行）

这是插入栓（entryplug）的机器仓库。你在这里只修机器，不碰内容。

## 怎么跑

- `python -m pytest`：每个动词一组、每道闸门一组、示例装备里每种 ERROR 故意坏一次、防泄漏。全部要过。
- `python tests/acceptance.py`：验收剧本 C0–C4。自动项必须 100% PASS；MANUAL 项写明怎么手核。
- 只对 `example-tool/` 跑：`plug --root example-tool index | check | search … | eval bench/public/goldset-sunzi.yaml`。

## 什么不能碰

- 任何真实内容仓库（素体、装备、教材、记录、提议）——永远不在这里，也不从这里指过去。机器不知道内容仓库在哪。
- 不往仓库里放用户绝对路径、BV 号、密钥、真实工具名或内容；`tests/test_no_leak.py` 会拦，别绕它。
- 形状 v1 的必填字段（`entryplug/shapes.py` SHAPES）：只加可选字段。要改必填字段 = 形状 v2 = 写 `plug migrate`，不是改字段表。
- 闸门只做工具调用点的阻断：不用 updatedInput 改写工具输入、不往 prompt 塞检索结果、不开机注入规则全文、没有 Stop 钩子催写。

## 修好的定义

修好 = `python -m pytest` 全过 **且** `python tests/acceptance.py` 机器项全 PASS。agent 自己写的测试会作假，验收剧本才是真测试；改了测试要说明为什么。

## 边界

一个文件一个动词，每文件 ≤250 行，没有类框架、没有装饰器魔法；每文件头 10 行注释（做什么 / 输入 / 输出 / 不做什么 / 谁调用）。
机器里不许出现领域逻辑（装备自带的 `checks/` 是挂点，不是机器）；不重排、不调 LLM、不做向量（`search.dense_candidates` 是桩）。
拿不准的规格问题写一行进 `docs/DECISIONS.md`，别默默选。
