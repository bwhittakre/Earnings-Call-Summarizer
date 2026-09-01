---
id: decision-desk-quant-expire-v2
type: decision
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Quant cross-check, clocks, and expired unknown
tags: decision,desk,claims,quant,expire,known-delivered,september-2026
created_at: 2026-09-01T16:20:00+00:00
updated_at: 2026-09-01T16:20:00+00:00
---
Stated horizons are `seed.clock`. A later typed `deferred`
pushes `current_clock`. Walk does not invent a clock, expire,
or quant binding. `expired` closes and does not score. Silence
alone is never a miss.

Quant runner reads local `narrative_quant.parquet` only. No
live Snowflake. Clocked trees check at or after the clock;
unclocked trees wait `silence_quarters=4`, then stop at typed
`expire` or seed+8Q. A missing actual at the stop is expired,
not missed. Quant confirm/deny scores with `delivery_basis=quant`.
Gold never gets an apply.

Known-delivered keeps aged trees in the denominator
(confirmed / aged). Settled share is the companion. An
untouched expired claim stays unknown. Expiry never
auto-classifies delivered vs dropped. Soft someday-wants
with no clock and no expire stay out of the aged set.
Does not fold into `desk_trust`. Does not overwrite
`desk_panel_metrics_v2.json`.

Sidecar `desk_quant_v2.json` stamp `2026-09-01T16:00:00+00:00`.
Ops book rebuilt under the kept stamp
`2026-08-31T14:18:00+00:00`. Gold stamp stays
`2026-08-27T18:02:00+00:00` (0 quant rows).

First examples, ops only: `ibm-promontory-watson` qualitative
expire FY2018-Q3 → expired / unknown. `strw-150-160-spend`
quant binding with `measure: None` (Capex 22 prints 0–88,
not the $150–160M REIT spend bogey) and expire FY2027-Q3;
STRW onboard through FY2026-Q2 so the runner stays pending.
Management regimes parked.

Roz Claims Trees and workshop HTML both show expire caption,
quant panel, known-delivered, and settled share.
