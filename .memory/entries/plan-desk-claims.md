---
id: plan-desk-claims
type: plan
project: earnings-call-summarizer
parent_id: plan-grounded-desk-p2
title: Claims desk v1 — promise tracker and cite-first as one object
node_label: Claims desk
tags: plan,desk,claims,promise,cite-first,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-27T13:16:00+00:00'
updated_at: '2026-08-27T13:16:00+00:00'
---
One product, not two stacks. A row is a typed claim with a clock,
a state, a cite, and a follow-up cite. 6 without 5 is a library;
5 without 6 is a spreadsheet.

## First cut
The 15 Phase 2 pilot rows. Hand-labeled type + object tokens.
Resolver searches **all** next-quarter verified evidence, any
dimension. Desk v1 first-verbatim is not the resolver.

Flex FY2022-Q2 → FY2022-Q3 is the bar: must return **kept**.

## States
- no next quarter → open
- object found → kept
- forward_clock due and silent → slipped
- forward_clock not due and silent → open
- pending_close silent → open
- printed_fact / completed_announcement silent → subject-changed

## Hard rules
No new LLM. No `transcripts_raw`. No 140 dump. No Path ID retune.
`production_v1` frozen. Locked stamp `2026-08-17T17:28:40+00:00`.
Path ID hit/miss is metadata, not the verdict. Healthcare stays out.
