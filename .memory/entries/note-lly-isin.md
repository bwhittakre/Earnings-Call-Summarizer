---
id: note-lly-isin
type: note
project: earnings-call-summarizer
parent_id: plan-hc-overnight-gate
title: LLY identity is ISIN US5324571083; Lloyds overlay dropped
node_label: LLY ISIN bind
tags: healthcare,lly,identity,isin,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-26T15:25:00+00:00'
updated_at: '2026-08-26T15:25:00+00:00'
---
Lloyds ISIN `GB0005163141` is gone from the LLY overlay.

Sourced bind: LSEG ticker-hop on 25 Aug (`expe-hc-identity-probe`) returned
ISIN `US5324571083`, estpermid `30064846182`, Barra `USAI951`, IBES `LLY`.
Quartr `search_companies("US5324571083")` on 26 Aug returned company
5159 / ticker LLY / Eli Lilly and Company only.

Short two-quarter overlay (same shape as UNH): prior `FY2025-Q4`,
output `FY2026-Q1` `FY2026-Q2`. Do not call full `run_onboard`.
Do not stamp `healthcare_large_cap` from this test.
