# Working on the machine (<=30 lines)

This is the entry plug's machine repo. Here you only fix the machine; you never touch content.

## How to run it

- `python -m pytest`: one group per verb, one per gate, one deliberate break for every kind of ERROR in the
  example equipment, plus no-leak. All of it has to pass.
- `python tests/acceptance.py`: the acceptance script C0–C4. Automated items must be 100% PASS; MANUAL items say
  how to verify them by hand.
- Against `example-tool/` only: `plug --root example-tool index | status | check | search … | eval bench/public/goldset-sunzi.yaml`.

## What you must not touch

- Any real content repo (Base, equipment, corpus, records, proposals) — never here, and never pointed at from
  here. The machine does not know where a content repo is.
- No user absolute paths, BV ids, secrets, real equipment names or content in this repo; `tests/test_no_leak.py`
  catches them, do not work around it.
- Shape v1's required fields (`entryplug/shapes.py` SHAPES): only optional fields may be added. Changing a
  required field means shape v2 and a `plug migrate`, not an edit to the table. The Chinese section headings
  (依据 / 最强反证 / 什么会改判 / 改成什么 / 为什么 / 观察 …) are on-disk shape vocabulary, not prose: they stay
  as they are even though everything the machine says is in English.
- The gates only block at the tool-call boundary: no rewriting tool input with updatedInput, no pushing search
  results into the prompt, no injecting the rules in full at boot, and no Stop hook that blocks. The Stop hook
  (`gates/stop.py`) is reminder-level — it prints at most one nudge and always exits 0.

## What "fixed" means

Fixed = `python -m pytest` all green **and** `python tests/acceptance.py` all machine items PASS. Tests an agent
wrote for itself can lie; the acceptance script is the real test. If you change a test, say why.

## Boundaries

One verb per file, <=250 lines per file, no class frameworks and no decorator magic; a 10-line header comment on
every file (what / in / out / not / who).
No domain logic in the machine (an equipment's own `checks/` is a mount point, not machine code); no reranking,
no LLM calls, no vectors (`search.dense_candidates` is a stub).
When a spec question is genuinely open, write one line into `docs/DECISIONS.md` rather than choosing silently.
