---
id: chec-9e3c79ce
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-c35843a9
title: CRWV is on the live Rank IC / consolidated book
node_label: CRWV is on the live Rank IC / consolidated book
tags: ''
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-83205f0b
created_at: '2026-09-09T13:35:52.510063+00:00'
updated_at: '2026-09-09T13:36:04.859953+00:00'
results: '[{"metric": "rank_ic_book_size", "value": 26, "split": "live-docker-xlk",
  "window": "2026-09-09T13:25:21Z", "source": "narrative_signal_eval.json tickers
  includes CRWV"}, {"metric": "consolidated_rows", "value": 7240, "split": "live-docker-xlk",
  "window": "min_cal=2016-Q2", "source": "build_consolidated_panel_report Loaded CRWV:
  40 rows"}]'
related_to: chec-b4f9b48b
---
CRWV Roz scoring was already on disk (feature_panel 2026-09-09T00:19:34, 40 rows). The stale sidebar warning was a host-vs-Docker book split: host sqlite was dirty with CRWV; Docker /data/monitor.sqlite3 was clean on the 25-name 2026-08-27 book, so the regen loop idled.

Forced Docker research-regen. Live operational artifacts now include CRWV (26 names). Rank IC generated_at=2026-09-09T13:25:21Z; consolidated 2026-09-09T13:25:36Z. Dashboard stale check is clear. This is not the locked 17 Aug pack.

Heal: research-regen now treats sector∩overlay names missing from the Docker book as a regen trigger (TESTX99 stays out — no overlay). Book-ranks-only failures no longer re-dirty evaluate. research-regen compose now bind-mounts ./services and build_book_ranks.py.

Independent remains a 1-name dashboard filter; use XLK / All Companies to see CRWV in the cross-section.
