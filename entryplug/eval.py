# 做什么：`plug eval <goldset.yaml>`——金标 recall@k（默认 10）：每条查询跑同一个 search，看期望的 doc / 条目 id 有几个进了前 k。
# 输入：cfg · goldset yaml（格式见 bench/README.md：version · scope · cases[{id, q, expect[], lang?, scope?}]）· k。
# 输出：逐案一行 + 汇总（总 recall · 按语言 zh / en · n）；中文查询 recall 为零 = ERROR（退出码 1）；中文明显低于英文 = WARNING。
# 不做什么：不改索引；不重排；不做 LLM 裁判；不给「判断质量」打分——只有机械指标。
# 谁调用：主人（换索引、换分词后重跑）· bench/ 的公开小基准 · tests。
# 语言：case 没写 lang 时，查询含中文即 zh，否则 en。
# expect 里的 id 既可以是教材 doc id（sunzi-05-bingshi）也可以是条目 id（shi）或块 id（sunzi-05-bingshi#6）。
# 每讲座限额按 1 取（recall 按文档算，前 k 行就是前 k 个文档）；case 可用 per_doc 覆盖。
# 依据 §6.1：一个 1.3 万星的同类工具所有中文查询静默返回 0 条长达三个半月——所以中文为零是 ERROR 级验收。
# 依赖：PyYAML · search。
import yaml
from .index import CJK
from . import search


def run(cfg, goldset, k=10):
    g = yaml.safe_load(open(goldset, encoding="utf-8")) or {}
    cases, scope = g.get("cases") or [], g.get("scope", "corpus")
    rows = []
    for c in cases:
        q = c["q"]
        lang = c.get("lang") or ("zh" if CJK.search(" ".join(q) if isinstance(q, list) else q) else "en")
        res = search.search(cfg, q, scope=c.get("scope", scope), k=k, per_doc=c.get("per_doc", 1))
        hits = {r["doc"] for r in res["rows"]} | {r["id"] for r in res["rows"]}
        expect = set(map(str, c.get("expect") or []))
        rec = len(expect & hits) / len(expect) if expect else 0.0
        rows.append((str(c.get("id", q)), lang, rec, res["total"]))
        print("%-24s %s  recall@%d %.2f  候选 %d" % (rows[-1][0][:24], lang, k, rec, res["total"]))
    if not rows:
        print("eval: 金标里没有 cases")
        return 1
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    zh, en = mean([r[2] for r in rows if r[1] == "zh"]), mean([r[2] for r in rows if r[1] == "en"])
    print("recall@%d %.2f · n=%d · zh %s (n=%d) · en %s (n=%d)" % (
        k, mean([r[2] for r in rows]), len(rows), "%.2f" % zh if zh is not None else "-", sum(r[1] == "zh" for r in rows),
        "%.2f" % en if en is not None else "-", sum(r[1] == "en" for r in rows)))
    code = 0
    if zh is not None and zh == 0:
        print("ERROR 中文查询 recall 为零——分词或索引坏了（ERROR 级验收，§6.1）")
        code = 1
    elif zh is not None and en is not None and zh < 0.5 * en:
        print("WARNING 中文 recall 明显低于英文（%.2f vs %.2f）" % (zh, en))
    return code
