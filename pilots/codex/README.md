# pilots/codex · wiring up Codex, no code required

The two pilots are equals: all state is files in the content repo, so switching pilots is one more person reading
the same folder.

Shortest path: run `plug init --pilot codex` inside the content repo — it writes AGENTS.md (only when absent),
mirrors the manuals plus `agents/openai.yaml`, writes the repo-level `.codex/hooks.json` and `.codex/config.toml`
(`[mcp_servers.entryplug]`), and installs the pre-commit hook. If your Codex only reads `~/.codex/`, merge those
two files across. By hand:

1. `AGENTS.md` → copy to `<content-repo>/AGENTS.md` and fill in the `<tool-…>` slots (same map as CLAUDE.md).
   It tells the pilot to run `plug status` first thing every session.
2. Manuals: `plug index` has already mirrored every `SKILL.md` to
   `<content-repo>/.agents/skills/<equipment>/SKILL.md` with an `agents/openai.yaml` beside it
   (`allow_implicit_invocation: true` — Codex's implicit-invocation switch is not in the frontmatter, see
   `agents-openai.yaml`; equipment marked `disable-model-invocation: true` gets `false` instead).
   To keep a single copy you can use a directory junction instead of the mirror (Windows):
   `mklink /J .agents\skills .claude\skills`, then drop the codex skills line from plug.yaml.
3. MCP: add an `entryplug` entry to Codex's MCP config, command `plug mcp` (cwd = the content repo).
4. Hooks: `plug init` writes `<content-repo>/.codex/hooks.json` — the sortie-lock recorder, the compaction pin,
   the SessionStart panel and the Stop record reminder. **Read the next section before editing it by hand.**
5. Berserk lock: `gates/hooks/pre-commit` → `<content-repo>/.git/hooks/pre-commit`.
   **Codex has no permissions.deny, so prohibition ① has only this one layer here** — the pilot must say so out
   loud when the owner switches pilots.
6. `plug check --contact codex`, four steps, all green.

## User-level equipment

`plug init --pilot codex --link-skills` also copies every `SKILL.md` into the user-level skills directory
(`~/.agents/skills/<equipment>/` by default, overridable with `pilots.codex.user_skills` in plug.yaml), with the
content repo's absolute path stamped in so the equipment still knows where products go: `<root>/work/<equipment>/`.
It is a manual trigger, and there is no user-level MCP registration — outside the content repo you get the
manual, not the Base.

A record's `by` field reads `codex · <model> · <date>`, so the same situation judged by two pilots can be compared.

## After the machine changes: your AGENTS.md does not update itself

`plug init` writes `AGENTS.md` only when it is missing. Correcting the template here therefore fixes the *next*
install and not yours — this is exactly how a repo installed before 2026-09-01 kept telling its Codex pilot that
outbound actions were "blocked by a hook" long after we knew they were not. Diff your `AGENTS.md` against
`pilots/codex/AGENTS.md` after any machine upgrade; `plug check` raises `map_claim` for that specific stale claim.

## The Codex hook contract (verified against codex-cli 0.152, 2026-09-01)

Codex's hook file is **not** Claude Code's, and getting it wrong fails silently-ish: every hook reports
`Failed` and nothing runs.

```json
{ "hooks": { "PreToolUse": [ { "matcher": "Bash|shell|mcp__.*",
  "hooks": [ { "type": "command", "command": "C:/py/python.exe C:/repo/gates/outbound.py", "timeout": 30 } ] } ] } }
```

- **`command` is one string, split on whitespace, and quoting is not honoured.** The Claude form
  (`"\"C:/py/python.exe\" \"C:/repo/gates/outbound.py\""`) makes Codex try to spawn a program whose *name*
  contains quote characters — that is what "hook: PreToolUse Failed" meant. Write bare words.
  A path containing a space cannot be expressed at all; `plug init` warns instead of writing a hook that dies.
- Handler fields: `type` · `command` · `commandWindows` · `timeout` · `async` · `statusMessage` ·
  `additionalContextLimit`. Event names are PascalCase: PreToolUse · PermissionRequest · PostToolUse ·
  PreCompact · PostCompact · SessionStart · SessionEnd · UserPromptSubmit · SubagentStart · SubagentStop ·
  Stop · Interrupt.
- The payload on stdin is **the same shape as Claude Code's** (`hook_event_name`, `tool_name`, `tool_input`,
  `cwd`, `session_id`, `transcript_path`, `permission_mode`), which is why `gates/*.py` are shared unchanged.
- **Trust**: hooks need trusting once, and again after every change. Interactively Codex shows "Hooks need
  review → Trust all and continue"; the decision persists in `~/.codex/config.toml` as
  `[hooks.state.'<hooks.json path>:<event_snake>:<group>:<handler>'] trusted_hash = "sha256:…"`, where the hash
  covers the normalised handler (recipe in D58). Edit the file and the hash stops matching, and Codex then
  skips that hook **silently** — no error, nothing printed. `plug check` and `plug status` report this; for
  automation there is `codex exec --dangerously-bypass-hook-trust`. Until trusted, hooks do not run.

### How a Codex hook blocks

It blocks by **deciding**, not by failing. Print this on stdout and exit **0**:

```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "why — this must not be empty"}}
```

- `permissionDecisionReason` must be non-empty; Codex rejects a deny without one, and the reason is what the
  model is shown ("the command did not execute because …").
- **Exit 0.** A hook that exits non-zero has its stdout ignored, so `exit 2` — Claude Code's blocking channel —
  silently disables the deny on this side. `gates/outbound.py` prints the same JSON for both pilots and chooses
  the exit code from the payload (`turn_id` present ⇒ Codex ⇒ exit 0).
- Three forms do **not** work, and Codex says so in its own error strings: `continue: false`, `stopReason`, and
  relying on `async: false`. If you are testing a hook and nothing blocks, check that first.
- `PermissionRequest` is a separate event for the approval flow; the sortie lock does not need it.
