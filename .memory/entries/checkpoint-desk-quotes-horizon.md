---
id: checkpoint-desk-quotes-horizon
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Quote table and horizon keep rates on Claims Trees
tags: checkpoint,desk,claims,quotes,horizon,august-2026
created_at: 2026-08-31T15:20:00+00:00
updated_at: 2026-08-31T15:20:00+00:00
---
Roz Claims Trees now has a filterable quote table (seed / change /
close) and a new horizon series. Locked gold deliver 6/7, hit 1/1,
and desk_trust / desk_ambition in desk_panel_metrics_v2 are
unchanged.

Horizon series names are horizon_quarter_* and horizon_cum_*.
Cohort is due-this-quarter. Slipped / silent-due is a miss for
this series only; tree delivery stays unresolved. Event date for
a slip miss is the clock quarter. Horizon filter is clock length
1Q / 2Q / 4Q / all. Date range windows the same events.

Does not write production_v1. Walk still does not invent
delivered / hit / missed edges.
