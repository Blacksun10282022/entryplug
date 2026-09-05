# bench · the benchmark runner and its inputs

Two layers side by side, and never a total score (design §6.7 / §7.3).

## The public mini benchmark (`bench/public/`)

Run against the Sunzi example equipment; the cases are public, so anyone gets the same per-case table. The first
version has exactly one mechanical metric: gold-set recall@10.

```
plug --root example-tool index
plug --root example-tool eval bench/public/goldset-sunzi.yaml
```

Exit code 1 = zero recall on Chinese queries (ERROR-grade acceptance, §6.1); Chinese far below English is only a
WARNING.

The set holds 50 cases — 28 Chinese and 22 English/pinyin — across the corpus layer (all thirteen chapters plus
the lecture transcript) and the tools layer (all ten dictionary entries and all three playbooks); each case's
comment names the angle it tests: verbatim term, synonym rewrite, concept without the original word, cross-chapter,
an English gloss reaching the Chinese corpus, a described situation reaching a playbook. Measured on the example
equipment (2026-09-05): overall recall@10 0.98, Chinese 0.96, English 1.00; the single miss is the deliberate
homophone typo, kept on purpose. `tests/test_eval_goldset.py` holds this in CI with a floor of 0.93 — the measured
0.98 minus a 0.05 margin — plus a separate assertion that Chinese recall is never zero.

## Gold set yaml format

```yaml
version: 1
scope: corpus                      # default layer to search: tools / corpus / all
cases:
  - id: zh-01                      # optional; defaults to the query text
    q: 诡道                        # one query, or a list of queries taking different angles
    expect: [sunzi-01-shiji]       # doc id / entry id / chunk id expected in the top k (any one counts)
    lang: zh                       # optional: a query containing Chinese is zh, otherwise en
    scope: tools                   # optional: override the default scope
    per_doc: 1                     # optional: per-document cap (recall is per document; default 1)
```

## The private, real benchmark (cases never published)

The owner's real situations never enter this repo. Before a run, write the case file's sha256 + the protocol
version + the model into `registry.md` and commit that; results may only cite that entry, and may only report n,
the proportion, the interval, split by equipment, stamped with model / harness / date. Per-case results, the
situation text and answer fragments are never published, and an index built from real content is always gitignored.

## Things not to say

"Saves 95% of your tokens", "10x", "better than X"; any "judgment quality" number that came from an LLM judge;
an n=1 result stated as a general conclusion. If the lower bound of the interval has not cleared 50%, you do not
get to write "better than the bare model".
