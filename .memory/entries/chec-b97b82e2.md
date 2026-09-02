---
id: chec-b97b82e2
type: checkpoint
project: earnings-call-summarizer
parent_id: deci-cd5d3ce7
title: 'Quartr sweep live: 45/45 armed; four bugs found only against the real API'
node_label: 'Quartr sweep live: 45/45 armed; four bugs found on'
tags: quartr,monitor,phase2,live
status: discarded
open_threads: 0
success: 'null'
files: services/earnings_monitor/quartr_mcp.py,services/earnings_monitor/quartr_oauth.py,services/earnings_monitor/calendar_publish.py,services/earnings_monitor/providers.py,services/earnings_monitor/host_automation.py
session_id: sess-47f0193e
created_at: '2026-09-02T17:02:21.743819+00:00'
updated_at: '2026-09-02T19:52:34.356291+00:00'
related_to: ''
invalidated_by: ''
invalidates: ''
---
State: 'calendar --source mcp --horizon-days 100' publishes 47 manifests covering all 45 onboarded companies, zero skips, zero rate-limit failures. Suite 849 passed. Nothing committed.

Four bugs, all invisible to unit tests:

1. list_events takes companyId not ticker, and 'expand' is REQUIRED. My gateway passed {ticker}, so every sweep would have failed validation and read as 'no upcoming calls'. Fixed via cached search_companies requiring an EXACT ticker match (search is fuzzy; arming the wrong company beats skipping one) plus expand=[contentDates].

2. _fiscal_period read the quarter from the title but the year only from fiscalYear, which Quartr returns as null on many live rows titled 'Q3 2026'. BMY, IBM, LLY, MRK yielded no period and were dropped silently -- four major names never armed. Added a title-year fallback; explicit fiscalYear still wins.

3. Multiple events per quarter: MU FY2026-Q4 returned the call at 20:30Z and a 'Q4 2026 Post' session at 22:00Z. Same filename, same unique (ticker, period) key, so the last write won and Roz could be armed against the post-earnings session. dedupe_by_period keeps the earliest call time.

4. Quartr estimates report and call times INDEPENDENTLY, so they drift for future quarters (GILD call Oct 29 / report Nov 6; NVDA Nov 18 / Nov 25). 32 of 47 rows were inverted, violating call_at >= report_at, and the ValueError ABORTED the sweep leaving 6 of 47 written. Fixed by clamping report_at to call_at and guarding the per-manifest write so one bad row is a skip, not a run-ender.

Also: Quartr 429-rate-limits a full-book sweep; _send now honours Retry-After from header or body with capped backoff. The 'keep the previous dump when a fetch returns nothing' rule saved the first sweep.

Open: the 32 clamped times are estimates, corrected by T-7 re-verification (Phase 3b). Sweep is not yet on a timer.
