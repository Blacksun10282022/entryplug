# BENCH · the blind A/B for an equipment manual

Three things get measured here, by three different means, and they are never mixed into one number. The two locks
are checked by the acceptance script (`tests/acceptance.py`). Retrieval is checked against a public gold set that
anyone can reproduce (`bench/README.md`, `plug eval`). Whether an equipment *manual* earns its place is the one
question a script cannot answer, so it is settled by a blind A/B on the owner's own situations. This file is that
protocol, written plainly enough that anyone with their own content repo can run it on their own equipment.

The test measures one manual against the *same model with the equipment taken away*. It never measures one model
against another. The cases are the owner's real situations and they never enter this repo (`bench/README.md`, the
private benchmark). Everything below uses neutral placeholders in their place, and the blind A/B for an equipment
lives in the content repo under `workshop/<equipment>/bench/`.

## Two arms

Every situation is answered twice, by the same model on the same harness, changing one thing only: the Base and
the equipment.

**A, equipped.** The pilot (Claude Code or Codex) runs inside a clean copy of the content repo, following the
manual as it is actually installed (`.claude/skills` for Claude Code, `.agents/skills` for Codex). Hooks are
bypassed for the duration, and the flight-log records are reset to empty between runs, so one answer never reads a
record another just wrote. The equipped runs are **serialised**: they share the one copy of the repo, so two at
once would see each other's records and each other's index churn. Run them one at a time.

**B0, bare.** The true bare model: no tools, no MCP, no web, nothing but the situation text. Reaching genuinely
bare takes more than an empty working directory, because the harness still shows its user-level servers there. The
trap met in practice: a directory with no project config is not bare while global MCP servers are still visible to
the session.

```
# Claude Code, bare
claude -p --tools "" --strict-mcp-config --mcp-config <an empty mcp-config file> \
       --append-system-prompt "You have no tools; answer from the prompt alone."
# the system-prompt line earns its keep: with tools off and nothing said, the model narrates tool calls it cannot make.

# Codex, bare
CODEX_HOME=<a temporary dir> codex ...
# that CODEX_HOME holds a config.toml registering no MCP servers, with web_search disabled.
```

Bare runs share no state, so they may run in **parallel**.

## Packing

Each situation becomes one pack file: the situation first, then answer X, then answer Y. Which arm is X and which
is Y is decided by a **seeded coin**, and the mapping is written to a `KEY.json` that the judge is never handed and
never opens. The same seed packs the same way, so a rerun stays comparable to the first pass.

Feed a multi-line prompt to the harness on **stdin**, never as an argument. On Windows `cmd.exe` truncates an argv
string at the first newline, so a prompt pasted as an argument silently loses everything after line one.

## The judge

A separate session scores the packs. Its input is the pack files, and nothing tells it which arm is which. It is
given the reader's context, because a judgment answer is good or bad only against the person who has to act on it:
who is asking, what materials that person already holds, what they actually asked for at the end, and the owner's
standing rulings. It scores five criteria from 1 to 5, each with a one-sentence reason.

Two rules, both learned from a judge that went wrong:

1. **Cite two specifics, or the verdict is void.** Every verdict must quote at least two concrete things locatable
   in the pack text. A judge whose file-reading tool had been denied once wrote a complete, confident verdict from
   the file *names* alone; requiring two locatable citations catches that, because invented praise cannot be found
   in the text.
2. **The judge must be able to open what the answers cite.** The criterion that scores evidence and honesty needs
   read-only reach into the same materials the answers cite. Denied that, the judge marks the owner's true,
   correctly-cited facts as "unverifiable" and docks them, punishing the very honesty the criterion exists to
   reward.

## The pass line

Per equipment, per pilot, over the six situations:

- the equipped arm **wins or ties on the summed score**, and
- it **loses no single pair by more than two points**.

Report the per-pair scores, the sum, and the win / tie / loss count, stamped with which judge, which model, which
harness, and the date. A win on the sum with one bad blow-out is not a pass: the second clause is what stops a good
average from hiding a case where the equipment actively hurt.

These scores describe the owner's own iteration of his own manual on his own private situations, and they stay in
the content repo's workshop. What is allowed to leave this repo is only what `bench/registry.md` permits: a
registered case-file hash, and then n, the proportion, and its interval, split by equipment, stamped with model
and date. Never a per-case score, never the situation text, never a total.

## When judges disagree

Run more than one judge, and treat a disagreement as a finding, not as noise to average away. Report each judge
separately. When two judges split on a case, name the **criterion** they split on. The split seen in practice:
whether an answer that reaches for the owner's own recorded facts to strengthen a reading of another party's motive
should be credited for grounding or docked for over-reaching. That is a real question about the manual, and
averaging it into one number throws away the one thing the test found.

## Cost

Record, for every answer in both arms: wall-clock time, turns (Claude Code) or tool calls (Codex), tokens, and
dollars where the harness reports them. Report the equipped-over-bare multiple. Equipment buys judgment quality
with time and tokens, and a manual that wins by a hair at several times the cost is a different verdict from one
that wins cheaply.

## What this does not measure

It does not measure the model's quality on a public corpus it already knows. A benchmark built on the Sunzi
example would set the model against its own memory of Sunzi and say nothing about the equipment. The test is
private on purpose, because the owner's situations are the only ones the model has not read before.

It does not measure the machine either. The machine's value is measured mechanically and stays mechanical:
`plug eval` for gold-set recall, `tests/acceptance.py` for the two locks. The blind A/B is only ever about a
manual, and a bad result on it is a verdict on that manual, not on the machine that carried it.
