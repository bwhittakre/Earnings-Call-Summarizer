---
id: decision-desk-panel-metrics-v2
type: decision
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: desk_trust and desk_ambition are PIT credibility columns
node_label: Panel metrics
tags: decision,desk,trust,ambition,panel,nvidia,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-27T18:50:00+00:00'
updated_at: '2026-08-27T18:50:00+00:00'
---
Two columns, same shape, different objects. Home is
`management_confidence` only. Expanding window from the NVIDIA
lock FY2022-Q2. A rate at T uses terminals whose cite
fiscal_period <= T.

- desk_trust = delivered / (delivered + missed) on promises
- desk_ambition = hit / (hit + missed) on goals
- n companions so Roz can show 4/5
- null when n is 0
- goals never enter trust

Stamp `2026-08-27T18:02:00+00:00`. Split
`nvda-gold-20q-fy2022q2-fy2027q1`. Not the 17 Aug Rank IC book.
`production_v1` is not written. Flex v1 stays kept and delivered.

NVIDIA book-end from `desk_panel_metrics_v2.json`:
desk_trust 0.8 on 5 scored; desk_ambition 1.0 on 1 scored.
