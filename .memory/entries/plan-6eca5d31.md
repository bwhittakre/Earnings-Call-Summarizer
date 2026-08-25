---
id: plan-6eca5d31
type: plan
project: earnings-call-summarizer
parent_id: earnings-call-summarizer
title: Narrative signal research (Roz)
node_label: Narrative signal research
tags: subproject,roz,rank-ic,narrative
status: active
open_threads: 0
success: 'null'
files: ''
session_id: sess-e7b9323b
created_at: '2026-08-17T19:44:35.970967+00:00'
updated_at: '2026-08-17T19:44:35.970967+00:00'
---
The narrative-signal workstream that sits alongside the SEC confidence analyzer.

LLM scores earnings-call transcripts across 8 narrative dimensions, every claim backed by a transcript-verified excerpt. Signals join a point-in-time quant spine (LSEG/IBES + MSCI Barra) and are evaluated with walk-forward Rank IC. Results surface in the Roz Streamlit dashboard.

## Scale as of Aug 2026
- 26 companies, 950 scored quarters, 46 distinct fiscal periods (back to 2016-Q2)
- 14,855 evidence excerpts, 100% transcript-supported
- Verification ladder in `Structured Narrative/dimension_scorer.py`: verbatim (10,587) / composite (3,357) / anchored (911) / paraphrased / unverified

## Key code
- `Structured Narrative/` — scoring (dimension, delta, surprise, novelty), evaluation, panel builders
- `services/earnings_monitor/dashboard/` — Roz pages including Rank IC Research and Rank IC Lab
