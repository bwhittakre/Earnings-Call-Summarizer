---
id: checkpoint-desk-onboard-1-3
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Claims-desk onboard 1–3 closed (honest desk, cull, census)
tags: checkpoint,desk,claims,onboard,honest-desk,cull,census,august-2026
created_at: 2026-08-31T18:55:00+00:00
updated_at: 2026-08-31T18:55:00+00:00
---
Onboard steps 1–3 are closed. No trees were auto-inserted.
Gold `desk_trees_v2.json` stayed 84,215 bytes at stamp
`2026-08-27T18:02:00+00:00`. Gold cue queue stamp unchanged.
Cue recall tests still 1.0 / n_missed==0.

1. Honest desk. Sector drives Book (`desk_hc_v2` on
healthcare, `desk_ops_v2` on tech, gold on All Companies
or `{NVDA}`). Zero-scoreable rates caption as "No scored
X yet. Em dash is not a 0% keep rate." Trailing
credibility (`desk_trust` / `desk_ambition`) shows only on
`nvda_gold_v2`.

2. Tighten the pull. Reject/guidance/rhetoric net widened
in `_desk_trees_v2_recall.py`. Ops and HC queues rescanned.
Leftover fell 1,250 → 1,145 (ops 610 → 556, HC 640 → 589).
That is a shorter worklist, not a short one. Further cull
only with patterns that keep gold 18/18. Proposer still
candidates-only.

3. Census. 24 tech + 20 HC each have novelty, a book, and
a queue. `missing=none`. Wrote `data/desk_onboard_census.json`.
APH still has no first seed. LRCX has a tree but covered 0.
DHR has no first seed.

Do not start more depth names or healthcare Rank IC unless
asked. Next is the user's separate ideas.

results_json:
- metric leftover_openings value 1145 split tech-ops-plus-hc-plus-nvda-gold window post-cull-2026-08-31 criterion vs-1250-pre-cull source desk_onboard_census
- metric leftover_ops value 556 split tech-ops-novelty-present window post-cull-2026-08-31 criterion vs-610-pre-cull source desk_ops_scan
- metric leftover_hc value 589 split hc-ops-novelty-present window post-cull-2026-08-31 criterion vs-640-pre-cull source desk_hc_scan
- metric census_tickers value 44 split 24-tech-plus-20-hc window onboard-1-3 criterion missing=none source desk_onboard_census
- metric gold_bytes value 84215 split nvda-gold-20q-fy2022q2-fy2027q1 window stamp-2026-08-27T18:02:00+00:00 source desk_trees_v2.json
