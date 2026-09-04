# entryplug · Entry Plug

The machine that sits between one person's written judgment and the agent that uses it: three file shapes, one
read-only search interface, two machine-enforced prohibitions, one check-up. It does not judge, does not
orchestrate, does not learn on its own. A Sunzi example equipment ships with it, so the acceptance script runs
in five minutes, along with a small benchmark anyone can reproduce. This is something I use myself; it is not a
general-purpose product.

*Entryplug is the plug any pilot (Claude Code / Codex) inserts into one person's Base (rules, flight log, facts)
to fight with that person's Equipment (tools). The owner never pilots; the pilot never edits the Base.*
The architectural pattern is called **Base & Equipment**.

## What it does (all of it in the machine; the content is never here)

| verb | what it does |
|---|---|
| `plug index` | walk the content repo → shape validation → chunking → jieba words + CJK bigrams → **one FTS5 table**; incremental by file hash; writes the human-readable `index.md` and each equipment's playbook directory `playbooks/INDEX.md`; mirrors the manuals into the pilots' skills directories |
| `plug search` / MCP `search` | the only query interface, read-only: one or more queries → alias expansion → full text → round-robin merge → grouped by document → compact lines (id · source · file#Lstart-Lend · kind · excerpt). **No reranking**: reading the window and weighing it is the pilot's job |
| `plug status` | the boot self-check. One line per layer — index, Base, deny + pre-commit, berserk lock, sortie lock, equipment bay, `.plug-off` — then a sync rate and a verdict. Exits nonzero only when the index layer itself is unusable |
| `plug check` | the check-up: ERROR / WARNING one line at a time with the time each was verified, the header self-check (shape version · index freshness · when each hook last fired · mounted equipment), each equipment's own `checks/`, refit requests unapproved for 30 days moved to rejected/, one page of report + the sync rate. Never a total score. `--contact claude-code\|codex` = the four-step first-contact smoke test |
| `plug apply` | approve one refit request: verify the base short hash → add / replace / retire → check with 0 ERROR → git commit (the proposal sha in a trailer). A base mismatch is refused outright, never silently overwritten. **Owner only**: run inside an agent environment it refuses and tells the owner how to run it himself |
| `plug eval` | gold-set recall@10; zero recall on Chinese queries is an ERROR |
| `plug init --pilot claude-code\|codex\|both` | install the gates and the pilot shells into a content repo: the pre-commit hook, `.claude/settings.json`'s deny rules and hooks (merged, never overwritten), `.mcp.json`, the CLAUDE.md / AGENTS.md map (only when absent), the manual mirror, `.codex/hooks.json` and `.codex/config.toml`, the `work/` and `workshop/` zones — all with real absolute paths; idempotent, and it prints what it did to every file. `--link-skills` also installs the manuals user-level |

Two prohibitions are enforced by `gates/`, not by prompting: the **berserk lock** (do not change the rules or the
equipment, do not build new equipment — write a refit request) = git pre-commit + Claude Code deny rules. Know
what the deny half is worth: the rules live in `<content-repo>/.claude/settings.json` and bind a session whose
**project root is that repo**. An agent working from somewhere else — another project, a machine repo, a scratch
directory — edits those files with nothing in its way, and only pre-commit stops the result from landing. That is
why pre-commit is the hard layer and deny is the polite one. Hard, not airtight: `--no-verify` and `KB_APPROVE=1`
are the two documented ways round it, both leave a trace, and both are the owner's to use. The
**sortie lock** (nothing goes out in the owner's name — ask first) = a PreToolUse hook, one list shared by Claude
Code and Codex, and it really blocks on both. The decision is one JSON line on stdout from a process that exits 0 —
`hookSpecificOutput.permissionDecision: "deny"` with a non-empty `permissionDecisionReason` — on both pilots
(D65, verified live on each). The hook is wired to every tool that can run a command or publish: Bash, PowerShell,
WebFetch, Artifact and all MCP tools. Codex's own
`approval_policy` and `sandbox_mode` sit on top as a second layer; `plug check --contact codex` prints both so you
can see what else is or is not in the way. Plus a compaction pin and a Stop-hook record reminder, both reminder-level.

## Five minutes

```
git clone <this repo> entryplug && pip install -e ./entryplug
cd entryplug
plug --root example-tool index
plug --root example-tool status
plug --root example-tool search 诡道
plug --root example-tool check
plug --root example-tool eval bench/public/goldset-sunzi.yaml
python -m pytest            # one group per verb, per gate, per kind of ERROR
python tests/acceptance.py  # the acceptance script C0–C4: machine items PASS/FAIL, human items MANUAL
```

### Updating an install after the machine changes

`plug init` is idempotent, but it writes the maps (`CLAUDE.md` / `AGENTS.md`) **only when they are absent** — they
are meant to be edited after install, so it will not overwrite yours. The consequence worth knowing: when a
template is corrected here, repos installed earlier keep the old text. Generated files (hooks, deny rules,
`.mcp.json`, the manual mirror) *are* refreshed by re-running `plug init`; the maps are not.

So after upgrading the machine: re-run `plug init --pilot both`, then diff your maps against
`pilots/*/CLAUDE.md` / `pilots/codex/AGENTS.md` and copy over anything that changed. `plug check` mechanically
catches the one stale claim that misleads a pilot about its own limits (code `map_claim`); everything else is on
the diff.

Build your own content repo the way `example-tool/` is built (`plug.yaml` is the only place a path may appear),
then run `plug init --pilot both` inside it to install the gates and the pilot shells (re-run it after upgrading the
machine: it also refreshes the hook matcher of an existing install), then `plug index`,
`plug status`, and `plug check --contact claude-code` (or `codex`) with all four steps green. Integration details
are in `pilots/claude-code/` and `pilots/codex/`, the gates in `gates/README.md`, the shapes in `docs/SHAPES.md`,
and every call made along the way — including the whole W2 round, D36–D44 — in `docs/DECISIONS.md`.

`plug search` covers the dictionary, the playbooks and the records by default; the corpus needs `--scope corpus`
(`scope=corpus` over MCP). With no hits the tail line says which scope was searched and when the index was built;
with no index it says so and exits 1.

## The owner's two lines

A pilot may write a refit request; only the owner may approve one. Every proposal file ends with the same block
the pilot pastes into the reply:

```
in a terminal:  plug apply proposals/pending/<file>.md
                plug apply proposals/pending/<file>.md --reject "reason"
from the chat:  ! plug apply proposals/pending/<file>.md --owner
                ! plug apply proposals/pending/<file>.md --reject "reason" --owner
look first (anyone, anywhere):  plug apply proposals/pending/<file>.md --dry-run
```

Why two forms: inside Claude Code / Codex the `!` prefix runs the command in the owner's own session, but that
session is the *same environment the pilot runs in*, so `plug apply` cannot tell an owner keystroke from an agent
tool call and refuses on the agent markers. The chat form therefore carries `--owner` (`PLUG_OWNER=1` works too);
in a real terminal no marker is set and no flag is needed. `--dry-run` is open to anyone, anywhere. A pilot
passing `--owner` is exactly the broken promise that setting `KB_APPROVE` by hand would be — and, like that one,
the real backstop is pre-commit. The wording lives in one function, `apply.owner_lines()`.

## Two cards

### In the content repo, without the plug

Some days the Base is beside the point and you want the plain model. Either put a file called **`.plug-off`** at
the repo root, or just say so ("不用素体" / "leave the Base out of this one").

- What turns off: the sortie lock, the compaction pin and the Stop-hook record reminder all pass straight
  through — no Base lookups, no playbook directory, no record nagging.
- What does **not** turn off: the deny rules and pre-commit. Protected files stay protected whether or not the
  plug is in. Nothing about `.plug-off` lets anyone edit `self/RULES.md`.
- `plug status` reports whether it is there, so you never wonder which mode you are in. Delete the file to plug
  back in.

### Outside the content repo, with the plug

You want one piece of equipment while working somewhere else entirely — another project, a scratch directory.

```
plug --root <content-repo> init --pilot claude-code --link-skills
```

That copies every `tools/*/SKILL.md` into the user-level skills directory (`~/.claude/skills/<equipment>/`,
`~/.agents/skills/<equipment>/` for Codex; override with `pilots.<name>.user_skills` in plug.yaml), stamping in
the content repo's absolute path. It is a manual trigger and it registers no user-level MCP server: outside the
content repo you get the manual, not the Base.

- Products default to `<content-repo>/work/<equipment>/`. If a copy is wanted where you are working, write the
  copy and note the master path in it.
- The Base is not loaded out here, and the manual says so: the equipment states that instead of inventing the
  owner's rules.
- Equipment you would rather the model never reached for on its own gets `disable-model-invocation: true` in its
  SKILL.md frontmatter; that rides along into the user-level copy and into Codex's `openai.yaml`.

## Boot panel as a SessionStart hook

`plug init` wires this up; by hand it is:

```json
{ "hooks": { "SessionStart": [ { "matcher": "startup|resume|clear",
  "hooks": [ { "type": "command",
    "command": "python -m entryplug.cli --root \"//c/<content-repo>\" status --emit", "timeout": 30 } ] } ] } }
```

`--emit` shows the panel on the owner's screen (`systemMessage`) and hands the pilot one verdict line as
`additionalContext` (D74). It is a panel of measured facts — the index is really queried
and timed — never the rules and never a search result. `AGENTS.md` tells Codex-style pilots to run `plug status`
first thing instead.

## Layout

```
entryplug/    cli · config · shapes · index · search · mcp · check · numbers · report · contact · status · apply · eval · init
              (one verb per file, <=250 lines each, no classes and no frameworks)
gates/        precommit · outbound · precompact · stop + the hook template
pilots/       claude-code/ (plugin shell · map · deny template) · codex/ (AGENTS.md · hooks · junction notes)
example-tool/ the Sunzi example content repo (corpus public domain, everything else CC0)
tests/        one group per verb, per gate, per kind of ERROR, plus no-leak and the acceptance script
bench/        the benchmark input format · a public mini gold set · the private benchmark registry
docs/         DECISIONS · SHAPES
extras/       where connector side-scripts live (not counted, not tested)
```

Dependencies: Python 3.12 · stdlib (sqlite3 + FTS5) · jieba · PyYAML · git. Works on native Windows, nothing to
compile. Vector retrieval is an optional module, `pip install entryplug[dense]` (an interface stub in this version).

## What it does not do

No model training, no LLM scoring of judgments, no total score; no agent runtime, rule engine or matcher; no LLM
extraction on the way in; no scheduled jobs and no unattended LLM tasks; no plugin marketplace, no multi-user, no
cloud sync, no web viewer.

## Licence and stance

The machine is MIT, the example content CC0. **Open source, not open contribution** (SQLite's phrasing): bug
reports with reproduction steps are welcome, feature requests are not, forks are fine, there is no roadmap.
Tags are cut only when the acceptance script passes in full; the last verification is in `STATUS.md`.
