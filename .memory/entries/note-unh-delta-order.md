---
id: note-unh-delta-order
type: note
project: earnings-call-summarizer
parent_id: plan-unh-two-quarter
title: UNH delta was inverted; pairing is now chronological
node_label: Delta order fix
tags: healthcare,unh,delta,bug,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-26T15:13:00+00:00'
updated_at: '2026-08-26T15:13:00+00:00'
---
UNH first-write `dimension_view` landed newest-first (batch fetch
order). Delta pairing followed list order, so the first UNH test
scored FY2026-Q2 as prior to FY2026-Q1.

Fix: `chronological_quarters()` in `quarter_merge.py`; dimension
finalize always sorts; delta `resolve_scope` sorts before pairing.
Force-rescore 26 Aug 2026: FY2025-Q4 → FY2026-Q1 and FY2026-Q1 →
FY2026-Q2. Panel is 16 rows (Q1 and Q2). JNJ / AMZN / CI views were
already chronological — this is a first-write hazard, not a
book-wide invert.

Do not quote the inverted Q2→Q1 delta. No healthcare Rank IC. No
book stamp.
