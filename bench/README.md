# bench · 跑分器与基准

两层并列，永远没有总分（设计 §6.7 / §7.3）。

## 公开小基准（`bench/public/`）

在示例装备《孙子兵法》上跑，案例公开，任何人得同一张逐案表。第一版只有一个机械指标：金标 recall@10。

```
plug --root example-tool index
plug --root example-tool eval bench/public/goldset-sunzi.yaml
```

退出码 1 = 中文查询 recall 为零（ERROR 级验收，§6.1）；中文明显低于英文只是 WARNING。

## 金标 yaml 格式

```yaml
version: 1
scope: corpus                      # 缺省查哪一层：tools / corpus / all
cases:
  - id: zh-01                      # 可省，缺省用查询原文
    q: 诡道                        # 一条查询，或一组不同角度的查询列表
    expect: [sunzi-01-shiji]       # 期望进前 k 的 doc id / 条目 id / 块 id（任一命中即算）
    lang: zh                       # 可省：查询含中文即 zh，否则 en
    scope: tools                   # 可省：覆盖缺省 scope
    per_doc: 1                     # 可省：每讲座限额（recall 按文档算，默认 1）
```

## 私有真实基准（不公开案例）

主人的真实处境基准永远不进这个仓库：跑之前把案例文件的 sha256 + 协议版本 + 模型写进 `registry.md` 并提交，结果只引用那条登记，只发 n、比例与区间、按装备分、模型 / harness / 日期戳。逐案、处境原文、答案片段不发；从真实内容建的索引永远 gitignore。

## 不许说的话

「省 95% token」「10x」「比 X 好」、任何由 LLM 裁判得出的「判断质量」、把 n=1 说成普遍结论。区间下限没过 50% 不得写「比裸模型好」。
