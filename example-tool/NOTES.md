# 示例装备《孙子兵法》· 说明

这是插入栓自带的**合成示例**内容仓库：一件装备（`tools/sunzi/`）+ 一个虚构主人的素体（`self/`）+ 几条改装申请。机器的测试与验收剧本只跑它。

## 来源与许可

- 教材 `tools/sunzi/corpus/raw/sunzi-01..13-*.md`：《孙子兵法》十三篇，**公有领域**。文字取自维基文库《孫子兵法》页面的 zh-hans（简体）变体，2026-08-29 通过 MediaWiki API 取得，按 `== 篇名 ==` 拆成十三个文件，去掉了页面附录「答话」与变体注释。维基文库该页标注的底本是通行本（十一家注 / 武经七书系统的通行文字）；与你手头的版本若有一两字之差，以本仓库文件为准——锚句核对只认这里的文本。
- 其余一切（说明书、打法、词典条目与观察行、记录、资料、规则、提议、讲座样例）由机器作者新写，**CC0 1.0**（见 `LICENSE-CC0`）。主人、公司、价格、对手全是虚构。
- 词典观察行的 `^pNNNN` 锚点与 `(src: doc#seq "锚句")` 全部指向上面的教材文件；`#seq` 是纯文本段里的段落序号（1 起）。

## 文件形状对照

- `tools/sunzi/corpus/raw/*.md`：教材，头部 `Title / ID / Kind / Date / Source` + `==== 纯文本 ====`。
- `tools/sunzi/corpus/raw/talk-2026-08-01-shi.txt`：讲座转写样例（`Title / BVID / Date` + 纯文本段 + 带时间戳段；机器只索引纯文本段）。
- `tools/sunzi/corpus/clean/talk-2026-08-01-shi.md`：同一讲的清洗稿（6 行头 + `====` + `[m:ss]` 段落）。同一 id 有清洗稿时只索引清洗稿。
- `self/records/`：驾驶日志（记录）；`proposals/pending/`：改装申请（提议）。

## 故意留下的 WARNING（示范体检报告，不是错误）

- `tools/sunzi/materials/2026-07-10-market-price.md`：kind=price，保质期 30 天，已过期。
- `self/records/2026-07-20-supplier-delay.md`：超过 30 天没填 outcome。
- `self/records/2026-08-27-choose-venue.md`：主人未答（chosen 为空），同步率里计「未答」。

`plug check` 在这里应当是 **0 ERROR**；每种 ERROR 由 `tests/test_check.py` 在临时副本里故意弄坏一次。
