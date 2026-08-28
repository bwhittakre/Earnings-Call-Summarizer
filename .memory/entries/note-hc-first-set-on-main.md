---
id: note-hc-first-set-on-main
type: note
project: earnings-call-summarizer
parent_id: chec-hc-first-set-commit
title: Fast-forward main to healthcare first-set commit
node_label: First set on main
tags: healthcare,git,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-25T17:50:00+00:00'
updated_at: '2026-08-25T17:50:00+00:00'
---
`origin/main` at `48cad86` is an ancestor of `cd961f2` (40 commits
ahead, 0 behind). Publishing the first set to main is a fast-forward
of `cursor/call-ticker-reaction` onto `main`, not a cherry-pick.

Cherry-pick onto old main failed earlier because that tip has no
`services/earnings_monitor/`. Do not invent a merge to hide that.

Second set (Angelo `.cursor/` rules/skills) stays uncommitted until
the user asks. Do not stage `.cursor/mcp.json`.
