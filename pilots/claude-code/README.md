# pilots/claude-code · wiring up Claude Code

A thin shell with no content in it. Shortest path: run `plug init --pilot claude-code` inside the content repo —
it does steps 1–5 of A below (real absolute paths, merged not overwritten, idempotent) — then `plug index`,
`plug status`, `plug check --contact claude-code`. By hand:

**A. Project level (recommended, the content repo carries it)**
1. `pilots/claude-code/CLAUDE.md` → copy to `<content-repo>/CLAUDE.md`, fill in the `<tool-…>` slots.
2. `settings.template.json` → merge into `<content-repo>/.claude/settings.json`; replace `//c/<content-repo>`,
   `//c/<entryplug-repo>` and `<equipment>` with the real paths and names.
3. `.mcp.json` → copy to `<content-repo>/.mcp.json` (`plug` must be on PATH: `pip install -e <entryplug>`).
4. `plug index` mirrors every equipment's `SKILL.md` to `<content-repo>/.claude/skills/<equipment>/SKILL.md`.
5. `gates/hooks/pre-commit` → `<content-repo>/.git/hooks/pre-commit`.
6. `plug check --contact claude-code`, four steps, all green.

**B. As a plugin**: this directory is a plugin root (`.claude-plugin/plugin.json` + `hooks/hooks.json` +
`.mcp.json`); `claude plugin add <this directory>`. The deny rules and pre-commit still go into the content repo
by A's steps 2 and 5 — a plugin cannot install deny rules.

## The SessionStart panel

`plug status` is wired to `SessionStart` (matcher `startup|resume|clear`) with `--emit`, which hands the panel
over as `additionalContext`. That is a panel of measured facts, not a briefing: it never injects the rules or
any search result.

```json
{ "hooks": { "SessionStart": [ { "matcher": "startup|resume|clear",
  "hooks": [ { "type": "command", "command": "python -m entryplug.cli --root \"//c/<content-repo>\" status --emit", "timeout": 30 } ] } ] } }
```

## Three things worth remembering

- deny only understands `Edit()` / `Read()`; a `Write()` rule is never checked. Never deny `Read(self/RULES.md)` —
  the pilot has to read the rules.
- deny applies under bypassPermissions too — verified live on 2026-09-02, Edit and Write both refused — but it
  cannot stop `python -c` writing directly; the backstop is pre-commit.
- The sortie-lock matcher must name every tool that can run a command or publish: `Bash|PowerShell|WebFetch|Artifact|mcp__.*`.
  A tool outside the matcher never starts the hook, and nothing reports that.
- Run `plug check --contact claude-code` the day you upgrade Claude Code; run `tests/acceptance.py` when you change model.
