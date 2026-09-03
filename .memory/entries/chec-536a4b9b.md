---
id: chec-536a4b9b
type: checkpoint
project: earnings-call-summarizer
parent_id: earnings-call-summarizer
title: AVGO scored + append_node idempotency fix
node_label: AVGO scored + append_node idempotency fix
tags: ''
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-5f5e1695
created_at: '2026-09-03T18:17:30.237147+00:00'
updated_at: '2026-09-03T18:17:30.237147+00:00'
---
AVGO scored: 1 seed confirmed, 1 verdict inserted (both books rebuilt clean, zero errors).

Root cause of duplicate overlay nodes found and fixed: append_node() in _desk_catalog_overlay.py had no idempotency check. Multiple independent autopilot runs each appended the same (fiscal_period, edge) node, creating 8x duplicates. Fixed by adding a skip guard before append.

Also cleaned: aapl-mac-pro-us-production (8 invalid 'delivered' nodes on goal tree), aapl-airpods-hearing-health (8 duplicate 'hit' nodes deduped to 1), amzn-aws-five-new-regions (2 duplicate nodes deduped to 1).

OPS overlay: 207 trees (155 confirmed, 52 provisional), HC: 187 trees (141 confirmed, 46 provisional).
