---
id: chec-f3b8ff1b
type: checkpoint
project: earnings-call-summarizer
parent_id: earnings-call-summarizer
title: Roz autopilot integration + debug sweep fixes
node_label: Roz autopilot integration + debug sweep fixes
tags: ''
status: active
open_threads: 0
success: 'null'
files: services/earnings_monitor/desk_autopilot.py, services/earnings_monitor/service.py,
  services/earnings_monitor/onboard.py, services/earnings_monitor/config.py, scripts/_desk_autopilot.py,
  scripts/_desk_catalog_overlay.py, tests/test_roz_autopilot_hook.py
session_id: sess-b5fed083
created_at: '2026-09-03T17:58:00.030932+00:00'
updated_at: '2026-09-03T17:58:00.030932+00:00'
---
Committing all Desk Autopilot + Roz integration work:

New files:
- scripts/_desk_autopilot.py — main autopilot orchestrator
- scripts/_desk_catalog_overlay.py — overlay CRUD
- scripts/_desk_regimes_stub.py — provisional regime stubs
- scripts/_desk_review_apply.py — apply analyst decisions
- scripts/_desk_review_sheet.py — Excel review workbook builder
- services/earnings_monitor/desk_autopilot.py — thin Roz hook wrapper
- tests/test_desk_autopilot.py, test_desk_catalog_overlay.py, test_desk_review_apply.py, test_roz_autopilot_hook.py

Key edits:
- service.py: post_call fires run_autopilot_for_ticker after walk_after_novelty_view
- onboard.py: sync_book_after_onboard fires run_autopilot_for_ticker at end (with EARNINGS_MONITOR_DESK_AUTOPILOT env guard)
- config.py: desk_autopilot_after_post_call=True, desk_autopilot_budget_usd=1.0
- _desk_trees_v2.py, _desk_trees_v2_ops.py, _desk_trees_v2_hc.py: overlay merge + materiality weighting
- _desk_seed_batch.py: materiality in LLM schema
- _desk_regimes.py: overlay merge for regime catalog
- claims_trees.py: provisional badges

Debug sweep found + fixed 2 bugs:
1. Dead TECH_TICKERS import removed from desk_autopilot.py
2. H4: sync_book_after_onboard lacked EARNINGS_MONITOR_DESK_AUTOPILOT guard — MonitorConfig flag had no effect on onboard path. Fixed by reading env var directly.

936 tests passing.
