---
id: chec-152afe70
type: checkpoint
project: earnings-call-summarizer
parent_id: chec-cc44fdcd
title: Roz autopilot integration complete
node_label: Roz autopilot integration complete
tags: ''
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-b5fed083
created_at: '2026-09-03T17:43:20.847234+00:00'
updated_at: '2026-09-03T17:43:20.847234+00:00'
---
Wired _desk_autopilot.run_for_ticker into Roz at two call sites:

1. post_call hook in service.py — fires after walk_after_novelty_view on every new earnings call
2. sync_book_after_onboard in onboard.py — fires when a new ticker is onboarded

New files: services/earnings_monitor/desk_autopilot.py (thin wrapper, never raises), tests/test_roz_autopilot_hook.py (7 tests).
Config: desk_autopilot_after_post_call=True, desk_autopilot_budget_usd=1.0. Env overrides: EARNINGS_MONITOR_DESK_AUTOPILOT, EARNINGS_MONITOR_DESK_AUTOPILOT_BUDGET_USD.
Kill switch: DESK_AUTOPILOT=0.

936 tests pass. Next: score AVGO through the full loop.
