---
id: chec-desk-claims-roz
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-desk-claims-roz
title: Claims Desk Roz page live on the locked 17 Aug book
node_label: Claims Desk live
tags: checkpoint,desk,claims,roz,delivery,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-27T14:15:00+00:00'
updated_at: '2026-08-27T14:15:00+00:00'
---
27 Aug 2026. Read-only Claims Desk page is live. Stamp
`2026-08-17T17:28:40+00:00`. Split `asof-path-id-17aug-book-v1`.

Book deliver rate 1/1 (Autodesk Flex launch). Three promises
unresolved. Nine kept rows have a hand-written coverage sentence.
Lab expander stays compact and points at the page. No new LLM.
No remaining-125 dump. production_v1 untouched.

Roz on :8501 is `roz-dashboard-1`. Compose does not bind-mount
`services/earnings_monitor` Python, so a browser refresh cannot
pick up host edits. Claims Desk was patched into the running
container. Recreating from the week-old image drops the page
until `docker compose up -d --build dashboard`. The page loader
reads `desk_claims_v1.json` itself and does not import
`scripts._desk_claims_v1` or `rank_ic_lab`.
