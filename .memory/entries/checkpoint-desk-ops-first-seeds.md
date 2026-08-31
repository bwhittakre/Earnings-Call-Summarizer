---
id: checkpoint-desk-ops-first-seeds
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Ops book, 24-name scan, first seeds, Roz switcher
tags: checkpoint,desk,claims,ops,august-2026
created_at: 2026-08-31T14:40:00+00:00
updated_at: 2026-08-31T14:40:00+00:00
---
Sibling ops book is live. NVIDIA gold stays locked in
`desk_trees_v2.json` stamp `2026-08-27T18:02:00+00:00`,
book `nvda_gold_v2`, 33 trees. Ops lives in
`desk_trees_ops_v2.json` stamp `2026-08-31T14:18:00+00:00`,
book `desk_ops_v2`, split `tech-ops-novelty-present`.

24 tech names with `novelty_view` were scanned. NVDA stays
on the gold queue. The other 23 write
`desk_cue_queue_v2_<TICKER>.json` plus an ops index.

First seeds are hand-typed from leftover novelty excerpts.
23 ops trees across 22 tickers. Delivered, hit, and missed
were not invented. APH has no first seed: leftover cues
after reject/guidance tighten are Brexit watchfulness,
COVID recovery rhetoric, and withdrawn guidance.

Added after the first 19: `avgo-day2-one-erp`,
`avgo-45-op-margin`, `lrcx-klx-approvals-mid2016`,
`strw-150-160-spend`. LRCX leftover coverage is 0 because
the full leftover also says "we will not comment further"
and is now a reject; the short mid-2016 approval cite still
verifies against `novelty_view`.

Roz Claims Trees has a book select: `nvda_gold_v2` or
`desk_ops_v2`. Empty ops still shows leftover cues.

Reject/guidance tighten: "we will not comment further",
"we will manage through", "we will exclude these benefits",
"if that changes we will tell you", "we're not going to
dilute ourselves", plus "we now expect to achieve" and
"we expect to see higher" as guidance. Gold cue recall
stays 1.0 on the 20Q window and on full history.

Dry walks 31 Aug 2026: NVDA FY2027-Q2 `walked`,
`changed=False`, gold stamp unchanged. MSFT FY2026-Q4
`walked`, `changed=True`, added one `silent` edge on
`msft-build-analyst-briefing` only. Gold file bytes
unchanged. Proposer remains candidates-only.

Healthcare and Rank IC / `production_v1` were not mixed.
No commit in this pass.

results_json:
- metric ops_trees value 23 split tech-ops-novelty-present
- metric gold_trees value 33 split nvda-gold-20q-fy2022q2-fy2027q1
- metric gold_cue_recall value 1.0 split nvda-gold-20q-fy2022q2-fy2027q1
