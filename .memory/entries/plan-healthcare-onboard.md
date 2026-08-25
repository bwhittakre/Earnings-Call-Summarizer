---
id: plan-healthcare-onboard
type: plan
project: earnings-call-summarizer
parent_id: plan-6eca5d31
title: Healthcare Large-Cap Quartr-to-Roz onboard
node_label: Healthcare onboard
tags: healthcare,onboard,quartr,universe-expansion
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-19T01:10:00+00:00'
updated_at: '2026-08-19T01:10:00+00:00'
---
Unattended 18 Aug 2026 universe expansion.

Sector title: Healthcare Large-Cap (`config/sectors/healthcare_large_cap.txt`).
20 names: LLY UNH JNJ ABBV MRK TMO ABT DHR PFE AMGN ISRG SYK GILD VRTX MDT BMY REGN CI ELV BSX.
Quartr watchlist 27941.

Path: MCP search_companies (validated ticker+US healthcare) → list_events earnings_call 2016-01-01..2026-08-19 → read_transcript windows → transcripts_raw → `run_onboard(skip_pull=True, skip_book_sync=True, research_sector=healthcare_large_cap)`.

Do not append these names into the live xlk_tech / SQLite Roz book. Feature panels stay under Structured Narrative/output/{TICKER}.

QUARTR_API_KEY is not set; REST import is not used.
Keep-awake process is running on Windows via SetThreadExecutionState.
