# pilots/antigravity · wiring up Antigravity (the desktop app and the agy CLI, one wiring)

Antigravity 2.0 (the desktop app) and the `agy` CLI run separate builds of one engine and read the same customization roots:
`.agents/` in the workspace, `~/.gemini/config/` for the user. Each keeps its own conversations
(`~/.gemini/antigravity/` and `~/.gemini/antigravity-cli/`), and the CLI has its own interface settings
(`~/.gemini/antigravity-cli/settings.json`); a content repo carries none of that. So there is one wiring, and it
serves both (D87). Open the app on the content repo folder, or start `agy` inside it: customizations are found by
walking from the working directory up to the repository root, so a session rooted in a parent folder sees none.

Shortest path: `plug init --pilot antigravity` inside the content repo (`--pilot all` for all three pilots), then
`plug index`, `plug status`, `plug check --contact antigravity`. It writes:

| file | what it is |
|---|---|
| `.agents/plugins/entryplug/plugin.json` | marks the folder as a workspace plugin; discovered plugins are on by default |
| `.agents/plugins/entryplug/mcp_config.json` | the `entryplug` MCP server (`plug mcp`). Outside a plugin Antigravity reads MCP servers only from `~/.gemini/config/mcp_config.json`, and the machine registers nothing user-level |
| `.agents/plugins/entryplug/hooks.json` | the sortie lock (PreToolUse, matcher `run_command\|send_command_input\|call_mcp_tool\|mcp_.*`) and the boot panel (SessionStart, `plug status --emit antigravity`) |
| `GEMINI.md` | the map overlay, only when absent — with `AGENTS.md`, also only when absent |

Two lines in `plug.yaml` are the owner's to add (it is protected, so in a live repo that is a refit request):

- `run_command` and `send_command_input` in every shell rule of `outbound:` —
  `tool: "^(Bash|PowerShell|shell|run_command|send_command_input)$"`. The first starts a command line, the second
  types into one already running. Until both are listed, what goes through them reaches the gate and matches
  nothing; `plug status` and `plug check` say so ([NG] / `agy_plugin`) instead of reporting the lock armed.
- `antigravity: {skills: .agents/skills, user_skills: "~/.gemini/config/skills"}` under `pilots:`. Antigravity
  reads the mirror Codex already gets (`.agents/skills/<equipment>/SKILL.md`); the line matters when Codex is not
  listed, and for `--link-skills`.

And two for the berserk lock's own coverage, if the repo protects the files that define its locks: `GEMINI.md` and
`.agents/plugins/entryplug/**` under `protect:`.

## The map

Antigravity loads `AGENTS.md` and `GEMINI.md` from the repo root together, always on, with no frontmatter (each file
is capped at 24,000 bytes; always-on rules share a 20,000-token budget). `AGENTS.md` is Codex's map, so `GEMINI.md`
is not a third copy of it but a short overlay: you are Antigravity, `by` reads `antigravity · <model> · <date>`,
and what the machine does and does not do on this side. Where the two disagree the overlay wins. `CLAUDE.md` is
not read.

## The hook contract (Antigravity's own: builtin skill `agy-customizations`, `docs/hooks.md`)

- `hooks.json` maps a hook *name* to its events: `{"sortie-lock": {"PreToolUse": [{"matcher": …, "hooks": [handler]}]}}`.
  `SessionStart` takes a flat list of handlers. Handler: `{"type": "command", "command": "…", "timeout": 30}`.
- The command runs as `cmd /d /s /c "<command>"` on Windows (`sh -c` elsewhere), with the plugin folder as its
  working directory, so it reads exactly as typed in cmd and quoted paths work too. `plug init` writes bare,
  space-separated words, as for Codex, and warns when a path holds a space.
- Allow by printing nothing. On agy 1.5.13 a hook that exits non-zero, or prints `{}`, `{"decision": ""}`, Claude's
  `hookSpecificOutput` or anything that is not JSON, makes the tool call fail; the guide says hooks fail open, this
  engine does not. `gates/outbound.py` prints only when it denies, so a gate that crashes stops shell commands on
  this side instead of letting them through.
- The payload is camelCase: `hookEventName`, `cwd` (the agent's), `workspacePaths`, `conversationId`,
  `transcriptPath`, and for a tool call `toolCall: {id, name, args}` with PascalCase arguments. A shell command is
  `CommandLine` of `run_command`, or `Input` of `send_command_input`. An MCP call is `call_mcp_tool`
  (`ServerName` · `ToolName` · `Arguments`) when tools load lazily, or the tool itself as `mcp_<server>_<tool>`;
  a plugin's server is named `<plugin>_<server>`. The matcher is an anchored regex: `a|b` means exactly a or b.
- A deny is `{"decision": "deny", "reason": "…"}` on stdout, from a process that exits 0. `gates/outbound.py` tells
  this protocol from the payload's own shape (only Antigravity sends `toolCall`) and answers in it (D88); it names
  an MCP call `mcp__<server>__<tool>`, as the other two pilots do, so one outbound list covers all three.
- SessionStart answers `{"injectSteps": [{"systemMessage": {"systemMessage": <line>, "renderInfo": {"markdown": <panel>}}}]}`:
  the model reads only `systemMessage` (seen live). The owner does not see the panel on this side: Antigravity's
  UI does not display an injected system message, and both engines drop `renderInfo` from a hook's step — in a
  live app conversation and a live agy one the stored step held the boot line and no panel. It stays in the output
  for a build that renders it. The hooks guide's `metadata.user_markdown` is not a field in either engine, and agy
  drops the whole hook over it. The one hook output a user does see, an injected `errorMessage`, would show the
  panel as an error on every new conversation and make `agy -p` exit as failed, so it is not used (D89).

## Seen live (agy 1.5.13, 2026-11-20)

In a scratch copy of the example after `plug init --pilot all`, one `agy -p` session: the boot line arrived as
"The following system message was injected by a SessionStart hook: entry plug boot: …"; `curl -X POST
https://example.invalid/x` came back to the agent as "tool call denied by pre-tool hook: sortie lock: run_command is
an outward action … ask first" and did not run; `search` on the plugin's server (`entryplug_entryplug`) answered a
Chinese query. Also seen: `run_command` runs PowerShell on Windows; every command the agent runs carries
`ANTIGRAVITY_AGENT`, which `plug apply` refuses like the other pilots' markers; MCP tools ask before their first use,
and headless `-p` cannot ask, so a scripted run needs `--settings '{"permissions":{"allow":["mcp(entryplug_entryplug/*)"]}}'`.
With the terminal sandbox on, `python.exe` could not start inside it on the build machine ("The file cannot be
accessed by the system"): the hooks and the MCP server run outside the sandbox and are unaffected, but a `plug …`
the pilot types into the terminal fails until the sandbox is off for that project.
The desktop app (engine 2.33.0) reads the same files but is checked by hand: acceptance item C4.6.

## What is not wired, and why (D90)

- **No deny layer.** Antigravity's permission grants live in the user's own config, per app project, not in a
  file the content repo carries. Pre-commit is the only berserk lock on this side, as on Codex, and the pilot has
  to say so when the owner switches pilots.
- **No compaction pin.** There is no compaction event to hook; the overlay tells the pilot what to read instead.
- **No record reminder.** Antigravity's `Stop` hook either lets the agent stop or makes it continue; a reminder
  that keeps the loop running is exactly the blocking Stop hook the machine forbids.
- **No panel on the owner's screen.** The pilot gets the boot line; the owner runs `plug status` (or asks the pilot
  to) when he wants the panel, and the overlay has the pilot say PATTERN ORANGE out loud (D89).

## Switching it off, and checking it is on

The plugin's on/off switch is Antigravity's own: `~/.gemini/config/config.json` → `plugins.entryplug.enabled`,
written by the plugin settings or `agy plugin enable|disable entryplug`. `plug status`, `plug check` and
`plug check --contact antigravity` read it and report a switched-off plugin rather than an armed lock.

Run `plug check --contact antigravity` the day Antigravity updates. Step ③ probes the gate with the payload shape
Antigravity sends; whether the app and the CLI really run the hook is the MANUAL item: open the content repo,
start a conversation, and see the boot panel arrive and a fake `curl -X POST https://example.invalid/x` refused.
