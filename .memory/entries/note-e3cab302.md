---
id: note-e3cab302
type: note
project: earnings-call-summarizer
parent_id: chec-8b09d4cb
title: DDOG --force rescoring aborted per user
node_label: DDOG --force rescoring aborted per user
tags: ddog,onboard,force,aborted
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-015c4e30
created_at: '2026-09-09T19:15:04.777338+00:00'
updated_at: '2026-09-09T23:11:49.403827+00:00'
related_to: anno-411e6397
---
User aborted the live DDOG FY2026-Q2 onboard that used --force-onboard and spawned run_universe_batch.py --tickers DDOG --force. That path resubmits already-scored quarters.

Killed process tree: PID 24096 (run_universe_batch --force), 39408 (onboard --force-onboard FY2026-Q2), 7520 (_case_study_onboard_batch.py), 37956 (parent PowerShell). Confirmed gone.

Do not rescore: FY2019-Q3, FY2021-Q1, FY2021-Q2, FY2025-Q3, FY2025-Q4, FY2026-Q1, FY2026-Q2.

onboard.py always appends --force to run_universe_batch, so remaining work must call run_universe_batch without --force (or with an explicit unscored --quarters list) rather than re-running the onboard CLI.
