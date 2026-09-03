# STATUS

Last verified on a real Claude Code 2.1.257 / codex-cli 0.152.0: **2026-09-02** (C1.2 deny under bypass: refused; the sortie
lock in both pilots: refused; C2.3 / C3.3 / C4.4 still open). The four things that can only be seen in a live
session — deny refusing an Edit, still refusing under bypass, carrying on after a compaction, switching pilots —
are the MANUAL items of the acceptance script (C1.2 / C2.3 / C3.3 / C4.4). The owner fills the version numbers
into this line once he has run them in his own pilot.

The build machine has Claude Code 2.1.252 and codex-cli 0.128.0 (the version stamps `plug check --contact`
reads). First contact is four-for-four green on both sides against a temporary copy of the example equipment
(manual mirrored · Chinese MCP query non-zero · fake outbound action blocked · pre-commit refusing a protected
write, plus the deny rules file checked).

Machine itself: 2026-09-03 · Windows 11 · Python 3.12.4 · SQLite 3.45.3 (FTS5) · git 2.51.1 · jieba 0.42.1 —
`python -m pytest` 120 passed; `python tests/acceptance.py` 24 automated items PASS, 0 FAIL, 4 MANUAL
(the example equipment). Build machine: Claude Code 2.1.257, codex-cli 0.152.0.

## Changed on 2026-09-03 (the review round, D65–D72)

A full review on 2026-09-02 found eight defects that a green test suite and a green acceptance script had walked
past, all in the locks' real strength: the sortie lock never saw the `PowerShell` tool, its self-tests exercised a
branch production never takes, pre-commit could not see a Chinese file name under git's default `quotePath`, two
environment variables replaced what it looked at, a stub hook read as armed, `plug apply` swept the whole index
into its commit, an untracked equipment check ran on every commit, and `plug.yaml` was not in the default protected
list. Each fix landed with a test that fails on the old code; the decisions are D65–D72. Verified live the same day
in `claude -p --dangerously-skip-permissions` and `codex exec` sessions: deny refuses Edit and Write under bypass;
the sortie lock refuses Bash curl and a subagent's Bash curl; Codex refuses curl and git push.

## Changed on 2026-09-01 (the W2 machine-side round, before installing into a content repo)

- `plug apply` is owner-only: an agent environment (CLAUDECODE, CLAUDE_CODE_ENTRYPOINT, CODEX_SANDBOX, … —
  presence only) is refused, with the owner's two copy-paste lines printed. `--dry-run` stays open to everyone;
  `--owner` / `PLUG_OWNER=1` is the escape hatch (D36).
- `.plug-off` at a content repo root: the sortie lock, the compaction pin and the record reminder pass straight
  through. Deny rules and pre-commit are untouched (D37).
- Two free zones, `work/<equipment>/` and `workshop/<equipment>/`: never protected, never indexed. Deny
  generation and pre-commit now only cover `self/` and the equipment registered in plug.yaml — anything else
  under `tools/` is unprotected until it is registered (D38).
- Equipment = skill: `plug init --link-skills` installs the manuals user-level (a copy, with the content repo's
  path stamped in), no user-level MCP, and `disable-model-invocation: true` rides along into Codex's
  `openai.yaml` (D39).
- New Stop hook `gates/stop.py`: the record reminder. It never blocks and always exits 0 (D40). The old rule
  "there is no Stop hook" is superseded — it was written against a *blocking* one.
- New verb `plug status`: the boot self-check, EVA panel, wired into SessionStart by `plug init` and documented
  for hand-installation in the README (D41).
- The owner's copy-paste block now lives in the map templates, in the footer of every proposal file (check warns
  with code `footer` when a pending one lacks it) and in `plug check`'s report, all generated from
  `apply.owner_lines()`. It has a terminal form and a chat form; the chat form carries `--owner`, because a bare
  `!`-prefixed approval would be refused by D36's own gate (D43).
- The whole public repo now speaks English: comments, docstrings, CLI help and error text, README, STATUS, docs,
  CLAUDE.md. Content stays in its own language, and shape v1's on-disk vocabulary does not move (D42).

- Field note on the D20 mount point: the first equipment check to run for real caught two genuine pilot errors
  on its first outing — a half-width colon inside YAML frontmatter, and a heading level that made a required
  section read as empty. Evidence that the contract (no args, one WARNING per stdout line, exit 0/2) is worth
  having. It also produced one false finding, by auditing the newest record regardless of which equipment owns
  it; a proposal narrowing it to `tool: <this equipment>` is pending. A check that cries wolf gets ignored
  within a fortnight, so scoping matters more than coverage here.
- A deployed map does not update when its template does (D55): `plug init` writes the maps only when absent, so
  unit-01 kept the pre-D53 sortie-lock claim after the template was corrected. Fixed in place, and `plug check`
  now raises `map_claim` if a deployed AGENTS.md still asserts a lock Codex has not got.
- Codex hooks work at all now (D53): every one of them had reported `Failed` since install, because Codex takes
  `command` as one whitespace-split string and we were emitting Claude's quoted form. Fixed in `plug init`.
- The sortie lock blocks on **both** pilots (D56). One decision — `permissionDecision: "deny"` with a non-empty
  reason — and two exit codes: Claude Code needs exit 2, Codex needs exit 0 (a non-zero exit makes it ignore the
  hook's stdout entirely). Verified live: zero command executions and the agent reporting it was stopped.
  This retracts the earlier "Codex records but cannot block" conclusion; see D57 for why that conclusion was
  reached from three sound experiments, and what to do instead of black-box probing.
- Every `--emit` path exits 0 even if the panel itself throws (D54).
- `plug check --contact` no longer reports a false "integration is broken" for a content repo whose equipment
  carries no dictionary: the MCP probe falls back to the index, and with nothing to probe with the hit count is
  not asserted (D50). Found by the first real acceptance run.
- Rule ids may carry a lowercase suffix (P2a). `shapes.rule_refs()` is now the single definition, used by check
  and numbers alike; before this such a reference was not misjudged but invisible, and the rule count under-read.
- Step 4 of first contact, the README and gates/README now say plainly that deny rules bind only a session whose
  project root is the content repo — written is not in force, and pre-commit is what actually holds (D49).

- `plug index` is now incremental in the dimension that costs: an unchanged file is not tokenised again (D47).
  A no-op rebuild of the first real content repo went from ~35 s to well under a second; pre-commit rebuilds the
  index on every commit, so that was a per-commit tax.
- Known issue, recorded and not yet fixed (D48): a row's `id` / `doc` is the file stem, so two equipment each
  holding a `SKILL.md` collapse into one document. It distorts `search`'s per-doc cap and can mix `eval`'s hit
  counting. The fix — qualifying both with the equipment name — also rewrites the bare ids in the public gold set,
  so it is a separate change.

`docs/PLAN.md` was removed on 2026-09-01: superseded, archived privately by the owner's instruction. It was the
module-boundary and W2 planning document; what it specified now lives where it is enforced — the module table in
this file and in `README.md`, the shapes in `docs/SHAPES.md`, and every decision it recorded in
`docs/DECISIONS.md` (the W2 round is D36–D44, and D45–D46 continue the series from the first real install).
There is no public copy; do not restore one from a fork.

Tags are only cut when the acceptance script passes in full. There is no tag yet.
