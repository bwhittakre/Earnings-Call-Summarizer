---
id: plan-grounded-desk-p2
type: plan
project: earnings-call-summarizer
parent_id: plan-grounded-desk
title: 'Grounded desk Phase 2: file verified excerpts as zettels'
node_label: Desk Phase 2
tags: plan,desk,zettel,path-id,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-26T18:37:00+00:00'
updated_at: '2026-08-26T18:37:00+00:00'
---
v1 proved the join (140/140) and that the excerpt explains novelty,
not the path. Phase 2 files already-verified desk excerpts as
grounded notes. No new LLM. No `transcripts_raw`. No
`create_extraction_graph`. No Path ID retune. `production_v1` stays
frozen. Healthcare stays out.

## Object
One note per desk row, quote = `excerpt`, citation stays a file
pointer into `novelty_view` (`{ticker} {fiscal_period} novelty_view
competitive_position {status}`). Path predicted/realized/hit ride
as metadata, not as the claim.

## Pilot (this cut)
15 rows already read on the desk:

- First print calendar 2021-Q2 (7 names)
- High-novelty misses (8 names)

Then stop. Full 140 is a later batch if the pilot notes are
something you would actually open.

## Hard rules
- Body quote is copied from `desk_path_id_v1.json` only.
- Do not invent a sentence. Do not read `transcripts_raw`.
- Do not promote Path ID L2. Notes are cites, not a ranking win.
- No `files=` pin unless asked to commit.
