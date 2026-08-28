---
id: plan-hc-overnight-gate
type: plan
project: earnings-call-summarizer
parent_id: plan-healthcare-onboard
title: Overnight close of healthcare onboard gate
node_label: HC overnight gate
tags: healthcare,onboard,identity,overnight,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-25T18:25:00+00:00'
updated_at: '2026-08-25T18:25:00+00:00'
---
User confirmed 25 Aug 2026: finish the three leftover onboard bets
overnight. Identity first, then the seven `run_onboard`s, then stamp
`healthcare_large_cap`. Do not invent ISINs. Do not compute Rank IC.
Do not mix into `xlk_tech`. `production_v1` stays frozen.

Quartr validated ticker+US healthcare matches (25 Aug): LLY 5159,
UNH 4258, DHR 3685, SYK 4857, GILD 5113, VRTX 6557, ELV 3742.
Quartr profiles do not carry ISIN.

LLY overlay `GB0005163141` / estpermid `30064846182` stays unverified.
Onboard must `--refresh-ids` and must not reuse that overlay.
