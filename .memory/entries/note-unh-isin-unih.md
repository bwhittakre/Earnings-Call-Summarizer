---
id: note-unh-isin-unih
type: note
project: earnings-call-summarizer
parent_id: plan-unh-two-quarter
title: UNH identity is ISIN US91324P1021; IBES ticker is UNIH
node_label: UNH ISIN bind
tags: healthcare,unh,identity,isin,lseg,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-25T20:27:00+00:00'
updated_at: '2026-08-25T20:27:00+00:00'
---
Sourced from Bloomberg by the user on 25 Aug 2026, then verified
live against LSEG A822 and Quartr.

ISIN `US91324P1021` binds UnitedHealth Group. Quartr
`search_companies` on that ISIN returns company 4258 / ticker UNH
only.

LSEG bind: INSTRPERMID `8590935024`, estpermid `30064860782`,
Barra `USAO6Z1`, IBES ticker `UNIH`. That is why exact
`IBESTICKER=UNH` printed None None. Do not bind UNHC
(`US9091961071`, estpermid `30064860776`).

A770 also missed exact UNH. Prefix aliases stay unbound.
Two-quarter test uses this ISIN on a short overlay
(prior `FY2025-Q4`, output `FY2026-Q1` `FY2026-Q2`).

UNH was missing from `config/fiscal_calendars.yaml` (full onboard
writes that entry). 10-K documentId 2974558: fiscal year ended
December 31, 2025 → `calendar_fiscal`. Without it, quant extract
skipped every PERENDDATE as unlabeled.
