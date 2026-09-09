---
id: chec-9fdde0ab
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-c35843a9
title: Call Scorecard 2-axis visual — built, refined, and wired into Roz post_call
node_label: Call Scorecard 2-axis visual — built, refined, and
tags: ''
status: active
open_threads: 0
success: 'null'
files: scripts/_desk_call_scorecard.py, scripts/_gen_scorecard_canvas.py, services/earnings_monitor/scorecard.py,
  services/earnings_monitor/config.py, services/earnings_monitor/service.py, data/desk_call_scorecard_v1.json
session_id: sess-3f126472
created_at: '2026-09-08T15:18:30.306971+00:00'
updated_at: '2026-09-08T15:18:30.306971+00:00'
---
Built the end-to-end 2-axis call scorecard system:

**Script** (`scripts/_desk_call_scorecard.py`): computes per-(ticker, fiscal_period) delivery score (rolling cumulative delivered/(delivered+failed)) and engagement score (net strengthen/weaken signal per call) across all three books. Added `n_never_touched`, `n_open_stale`, `pct_never_touched` goal-health fields. Expired trees now count as failed in both axes (delivery and engagement), not silently excluded.

**Canvas** (`scripts/_gen_scorecard_canvas.py` + `.cursor/projects/.../canvases/call-scorecard.canvas.tsx`): React/SVG quadrant with two view modes — Company Timeline (single ticker trajectory with connecting dots) and Period Snapshot (cross-company comparison for one period). Goal Health strip shows open goals, never-touched %, stale >4Q below the chart. Dot size and orange outer ring encode ghost-commitment rate visually.

**Roz integration** (`services/earnings_monitor/scorecard.py` + config + service hook): `scorecard_after_post_call` flag (default on, kill switch `EARNINGS_MONITOR_SCORECARD=0`) triggers sidecar + canvas rebuild after every post_call, after the autopilot runs. Canvas is patched by replacing the RAW_ENTRIES blob inline.

What's next: backlog of scoring runs to populate the delivery score and reduce the ~90% never-touched rate visible on the canvas.
