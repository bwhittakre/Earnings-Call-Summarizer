---
id: checkpoint-desk-claims-v2-nvda-gold
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Claims desk v2 NVIDIA gold book is stamped
node_label: v2 gold stamp
tags: checkpoint,desk,claims,trees,nvidia,august-2026
status: active
open_threads: 0
success: 'true'
files: ''
created_at: '2026-08-27T18:30:00+00:00'
updated_at: '2026-08-27T18:30:00+00:00'
---
v2 is a new stamp and a new object. v1 17 Aug book is untouched.
Flex launch still reads kept and delivered on the v1 page.

## Lock
Window FY2022-Q2 through FY2027-Q1 (20 consecutive NVDA scored
quarters, `nvidia_fiscal`). Stamp `2026-08-27T18:02:00+00:00`.
Split `nvda-gold-20q-fy2022q2-fy2027q1`. Book `nvda_gold_v2`.

## Counts
Source: `desk_trees_v2.json` after `python scripts/_desk_trees_v2.py`.

- trees: 13 (8 promises, 5 goals)
- promise deliver rate: 0.8 on split `nvda-gold-20q-fy2022q2-fy2027q1`,
  window 20q, criterion scored promises only (4 delivered / 1 missed).
  Unresolved clocks excluded.
- goal hit rate: 1.0 on the same split, criterion scored goals only
  (1 hit / 0 missed). Still-want excluded.

## What landed
Tree schema + walker. Goals as a sibling type. Harden-to-promise
is an edge (China want → H20 $2–5B Q3, which missed). Roz Claims
Trees page beside locked v1. post_call hook walks open trees after
novelty_view; no proposer LLM. Zettel graph `desk-trees-v2-nvda`
holds sentences; memory holds this lock.

Proposer LLM stays gated until a later autonomy bar.
