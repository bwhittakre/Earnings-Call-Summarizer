---
id: plan-monitor-automation
type: plan
project: earnings-call-summarizer
parent_id: plan-6eca5d31
title: 'Phase 2: fully automated earnings cycle and per-sector Rank IC'
node_label: 'Phase 2: monitor automation'
tags: phase,september-2026,monitor,automation,quartr,rank-ic
status: active
open_threads: 3
success: 'null'
files: ''
created_at: '2026-09-02T13:50:00+00:00'
updated_at: '2026-09-02T19:53:02.334374+00:00'
---
September 2026. Roz was not picking up earnings calls for companies that had been
onboarded. This phase closes the loop so the only manual step is onboarding a new company.

## Target cycle
On completing a call, look up the next earnings date from Quartr and schedule it. Re-verify
that date a week out. Run the quant check a couple of hours before, then score on the day.
Repeat with no arming or manual intervention.

## The four phases
1. **Unblock monitoring** -- monitored universe is every onboarded company, not the
   intersection with the research book. *(done, see the decision entry)*
2. **Close the Quartr loop** -- `config/automation_watchlist.yaml` is empty and
   `host_quartr/` has never existed, so no calendar dump is ever published. Needs the
   watchlist wired to the monitored universe plus scheduled Cursor Automations, because
   `RestQuartrGateway` is a stub and there is no API key.
3. **Self-perpetuating scheduling** -- nothing runs on COMPLETE to schedule the next
   quarter, and there is no T-7 re-verification. *(the rescheduled-call half is done)*
4. **Per-sector Rank IC** -- chosen deliberately over one pooled book. Rank IC is a
   cross-sectional statistic, so pooling tech with healthcare and later sectors makes the
   sample worse, not bigger. Needs artifact namespacing, a regen loop over sectors, and a
   sector selector in the dashboard.

## Open threads
- Phase 2 (Quartr acquisition) not started.
- Phase 3 next-quarter scheduling and T-7 re-verification not started.
- Phase 4 per-sector Rank IC not started.
