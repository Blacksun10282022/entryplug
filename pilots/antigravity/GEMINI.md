# Map overlay (<=40 lines) · copy this to the content repo root as GEMINI.md. Antigravity — the desktop app and the `agy` CLI alike — loads AGENTS.md and GEMINI.md together, both always on: AGENTS.md is the full map, and this page says only where you differ from the Codex pilot it was written for.

You are the Antigravity pilot. AGENTS.md is your map: where it says Codex it means you, except where this page says otherwise, and where the two disagree this page wins.

## In a record

- `by` reads `antigravity · <model> · <date>`, never `codex`. Everything else about records is as AGENTS.md says.

## What the machine does for you here

- Boot: a SessionStart hook runs `plug status` once per conversation and hands you one boot line. The owner does not see the panel on this side, so if the line says PATTERN ORANGE, tell him before you start working and name the layer; if he asks for the panel, run `plug status` and show it.
- Search: the `search` tool comes from the workspace plugin `.agents/plugins/entryplug/`, whose server Antigravity names `entryplug_entryplug` (you reach it through `call_mcp_tool`, or as `mcp_entryplug_entryplug_search`). Same arguments and same caveats as AGENTS.md gives.
- Equipment: the manuals are the mirror in `.agents/skills/<equipment>/SKILL.md`. One whose frontmatter says `disable-model-invocation: true` is the owner's to call (`/<equipment>`); never pick it up yourself.
- Sortie & worktree berserk lock: a `PreToolUse` hook in the workspace plugin denies both listed outward commands and edits/shell-writes to protected paths (backed up by `pre-commit`). Same tripwire, same blind spots as AGENTS.md describes.
- Hot indexing & prompt hints: `PostToolUse` updates the index immediately after record/memory edits and checks record quotes; `PreInvocation` injects configured prompt hints and `topic_pulse` nudges.
- Refit requests: `plug apply` sees the marker Antigravity puts in every command you run and refuses you, as it refuses the other pilots. Approving stays the owner's move, from a terminal of his own.

## What it does not do here — say so out loud when the owner switches pilots

- No compaction pin: Antigravity condenses conversations into checkpoints with no hook event to mark it. If your context was summarized, read the newest record under `self/records/` before you carry on, and keep answering in the owner's language.
- No record reminder at the end of a turn: Antigravity's Stop hook can only keep the loop running, and a reminder must never do that. The record obligation in AGENTS.md is yours to keep unprompted.

## Everything else

- As AGENTS.md says: the rules, where things go, refit requests and the owner's two lines, `.plug-off`, how to answer the owner, and how to finish.
