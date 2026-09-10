---
id: chec-b4f9b48b
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: CRWV full-call desk + live scorecard timeline + 9 Sep weekly pack
node_label: 'CRWV full-call desk + live scorecard timeline + 9 '
tags: checkpoint,crwv,scorecard,desk,september-2026
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-7b99e8a2
created_at: '2026-09-09T12:57:19.911061+00:00'
updated_at: '2026-09-09T13:36:04.859953+00:00'
results: '[{"metric": "crwv_scorecard_rows", "value": 19, "split": "CRWV", "window":
  "FY2025-Q1-through-CONF-2026-09-08", "criterion": "6 FY + 13 CONF", "source": "data/desk_call_scorecard_v1.json
  generated_at=2026-09-09T01:27:26Z"}, {"metric": "crwv_delivery_null", "value": 19,
  "split": "CRWV", "window": "same", "source": "desk_call_scorecard_v1.json"}]'
related_to: chec-9e3c79ce
---
Last-night work before the 9 Sep talk.

Onboard now writes the cue queue before desk autopilot and rebuilds the scorecard. Independent / non-tech names route to the hc book. Period identity keeps one row per FY quarter and per CONF event; canonical_period stays delivery-math only.

Call Scorecard Company Timeline plots every tracked call (earnings + conferences). Delivery is tooltip-only until a promise settles and is never drawn as zero. Period Snapshot is a transparency bar. Click pins goal health.

CRWV (Independent, Intrator, desk_hc_v2): 19 scorecard rows (6 FY + 13 CONF), delivery null on all 19, 19 post-call briefs. Live chart verified on :8501.

Weekly pack dated 9 Sep written to the Desktop (outline, script, talking card). Coverage is noon 31 Aug through 8 Sep. Rank IC book unchanged. No healthcare Rank IC. No production_v1.
