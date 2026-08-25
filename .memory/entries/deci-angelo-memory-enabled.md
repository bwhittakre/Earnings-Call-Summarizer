---
id: deci-angelo-memory-enabled
type: decision
project: earnings-call-summarizer
parent_id: earnings-call-summarizer
title: Angelo memory re-enabled on an isolated venv; the main repo is the memory home
node_label: Angelo memory enabled
tags: angelo,memory,mcp,infrastructure,setup
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-17T20:05:00+00:00'
updated_at: '2026-08-17T20:05:00+00:00'
---
Angelo was installed on 8 July 2026 and then never ran once. This entry records why, and
the configuration that fixed it.

## Why it was dead
Every Angelo MCP server — memory, zettelkasten, coordinator, memory-artifacts — was
configured in `.cursor/mcp.json` to launch from `.venv\Scripts\angelo-*.exe`. That venv was
built on Python 3.14.6, which was later removed from the machine, so all four crashed on
startup with exit 103. `angelo doctor` reproduces this exactly. The symptom was five weeks
of `.memory/` sitting at its two bootstrap entries with nothing added.

## The configuration now
- Angelo upgraded **1.7.5 to 1.7.23** and installed into an isolated venv at
  `C:\Users\BobbyWhittaker\AppData\Local\angelo-venv` on Python 3.12. Isolation is required,
  not cosmetic — see the Python environment note.
- `angelo doctor --fix` installed the Cursor global plugin
  (`~/.cursor/plugins/local/angelo`) pointing at that venv.
- Both `.cursor/mcp.json` files — main repo and the temp audit worktree — repointed at the
  same venv, with timestamped `.bak-*` copies beside them.
- `angelo update --keep-edits` refreshed 12 managed config files and preserved locally
  edited rules as `.new` copies to reconcile.

## Two things to remember
1. **`.memory/` is git-tracked in this repo.** The memory server will therefore auto-commit
   memory files authored as `memory-mcp`. Those commits touch only `.memory/`, never source,
   but the repo's no-auto-commit rule assumes these files are ignored and that is no longer
   true.
2. **This repo has two git worktrees** — the main repo on `cursor/call-ticker-reaction` and
   a scratch audit worktree under `AppData\Local\Temp` on `cursor/automated-earnings-monitor`.
   With no pinned `ANGELO_WORKSPACE`, a memory write landed in one store while reads came
   from the other. The main repo is the decided home for memory; work there.
