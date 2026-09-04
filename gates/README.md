# gates · two locks, one pin, one reminder

Four scripts. One hook, one verb; one line of reason; each stamps `.kb/hooks/<name>` with the time it last fired
(`plug check` and `plug status` report when one has gone quiet).

| script | prohibition | mounted on | hardness |
|---|---|---|---|
| `precommit.py` | ① berserk lock: a protected path cannot be committed without `KB_APPROVE=1`; a staged record or proposal must have its shape | git pre-commit (installed by `plug init`) · `plug.yaml: protected / unprotected / protect` | **Hard.** Refuses and nothing else since D75: no index rebuild, no check-up, no numbers page in the hook |
| `outbound.py` | ② sortie lock: nothing goes out in the owner's name, ask first | PreToolUse (Claude Code `pilots/claude-code/hooks/hooks.json` · Codex `.codex/hooks.json`), one list in `plug.yaml: outbound` | **Blocks on both** — one deny decision on stdout, exit 0, read by both pilots (D65). Hooks are still fail-open if the script never runs, and a tool name outside the matcher never reaches it |
| `precompact.py` | (not a prohibition) the compaction pin | PreCompact + SessionStart(compact) | five facts, nothing else |
| `stop.py` | (not a prohibition) the record reminder | Stop | reminder only: it never blocks, it never writes, it exits 0 always |

By hardness: pre-commit > `permissions.deny` (Claude Code only; `Edit(path)` form, see
`pilots/claude-code/settings.template.json`) > hooks. Native Windows has no sandbox, so deny cannot stop a
subprocess writing directly — which is why pre-commit is the hard layer. Hard, not airtight: `--no-verify` and
`KB_APPROVE=1` go round it, on purpose and visibly; the test seams `PLUG_STAGED` / `PLUG_ROOT` no longer do
(D66), a Chinese file name no longer slips past it (D67), and a stub hook no longer reads as armed (D68).

Deny has a second, quieter limit: those rules bind **a session whose project root is the content repo**. Open the
same files from a session rooted anywhere else and deny never sees the edit; the file changes, and the refusal
only arrives at commit time, from pre-commit. `plug check --contact` can therefore prove the rules are *written*,
never that they are *in force* — to see them bite, edit a protected file from a session whose root is the content
repo. Treat deny as the layer that stops an honest mistake in the room where it was configured, not as a fence.

## `.plug-off`

A file named `.plug-off` at the content repo root means "the plug is out for now": `outbound.py`,
`precompact.py` and `stop.py` all pass straight through — no Base lookups, no pin, no record nagging.
**Deny rules and pre-commit are not affected**: what is protected stays protected whether or not you are
using the Base. Delete the file to plug back in. `plug status` reports whether it is there.

## Install (once per content repo)

```
cd <content repo>
plug init --pilot both               # .git/hooks/pre-commit (backing up anyone else's), the deny rules and hooks in
                                     # .claude/settings.json (merged), .mcp.json, CLAUDE.md / AGENTS.md when absent,
                                     # the manual mirror, .codex/hooks.json + config.toml, work/ and workshop/.
                                     # Real absolute paths, idempotent. Add --link-skills for user-level skills.
plug index
plug status                          # the boot self-check: every layer on one line
plug check --contact claude-code     # first contact, four steps; all green or the integration is broken
plug check --contact codex           # each Codex hook has to be trusted once, by hand
```

By hand (if you would rather not use init): copy `gates/hooks/pre-commit` to
`<content repo>/.git/hooks/pre-commit` and fix the path; merge `pilots/claude-code/settings.template.json` into
`.claude/settings.json`; merge `pilots/codex/hooks.json` into `~/.codex/hooks.json` or the repo-level `.codex/hooks.json`.

Rules for the gates themselves: never rewrite a tool's input (updatedInput), never push search results into the
prompt, never inject the rules in full at boot, and never let a Stop hook block — the reminder is a reminder.
