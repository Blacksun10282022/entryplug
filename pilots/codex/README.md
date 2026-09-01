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
4. Sortie lock: merge `hooks.json` into `~/.codex/hooks.json` (or the repo-level file) and fix the placeholder
   paths. Each hook has to be trusted once, by hand. The same file also carries the compaction pin, the
   SessionStart panel and the Stop-hook record reminder.
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
