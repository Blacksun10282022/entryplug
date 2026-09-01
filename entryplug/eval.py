# What: `plug eval <goldset.yaml>` — recall@k against a gold set (default k=10): every case runs the same search
#       and we count how many of the expected doc / entry ids made the top k.
# In:   cfg · a gold set yaml (format in bench/README.md: version · scope · cases[{id, q, expect[], lang?, scope?}]) · k.
# Out:  one line per case plus a summary (overall recall · by language zh / en · n); zero recall on Chinese
#       queries is an ERROR (exit 1); Chinese far below English is a WARNING.
# Not:  never touches the index; no reranking; no LLM judging; never scores "judgment quality" — mechanical only.
# Who:  the owner (after changing the index or the tokenizer) · bench/'s public mini-benchmark · tests.
# Note: when a case has no lang, a query containing Chinese counts as zh, otherwise en. An id in `expect` may be
#       a corpus doc id (sunzi-05-bingshi), an entry id (shi) or a chunk id (sunzi-05-bingshi#6). The per-doc cap
#       is 1 (recall is per document, so the top k rows are the top k documents); a case may override per_doc.
#       Why zero-recall Chinese is ERROR-grade (§6.1): a 13k-star tool of the same kind silently returned nothing
#       for every Chinese query for three and a half months.
# Deps: PyYAML · search.
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
        print("%-24s %s  recall@%d %.2f  candidates %d" % (rows[-1][0][:24], lang, k, rec, res["total"]))
    if not rows:
        print("eval: the gold set has no cases")
        return 1
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    zh, en = mean([r[2] for r in rows if r[1] == "zh"]), mean([r[2] for r in rows if r[1] == "en"])
    print("recall@%d %.2f · n=%d · zh %s (n=%d) · en %s (n=%d)" % (
        k, mean([r[2] for r in rows]), len(rows), "%.2f" % zh if zh is not None else "-", sum(r[1] == "zh" for r in rows),
        "%.2f" % en if en is not None else "-", sum(r[1] == "en" for r in rows)))
    code = 0
    if zh is not None and zh == 0:
        print("ERROR recall on Chinese queries is zero — the tokenizer or the index is broken (ERROR-grade acceptance, §6.1)")
        code = 1
    elif zh is not None and en is not None and zh < 0.5 * en:
        print("WARNING Chinese recall is far below English (%.2f vs %.2f)" % (zh, en))
    return code
