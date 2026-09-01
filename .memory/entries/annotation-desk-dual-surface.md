---
id: annotation-desk-dual-surface
type: annotation
project: earnings-call-summarizer
parent_id: plan-desk-claims-v2
title: Claims Trees and workshop HTML stay identical
tags: annotation,desk,claims,roz,html,workshop,september-2026
created_at: 2026-09-01T13:00:00+00:00
updated_at: 2026-09-01T13:00:00+00:00
---
User preference. Any change to the claims desk (filters, rates,
buckets, edges, captions, tree list) must land on both Roz
Claims Trees and the standalone workshop HTML unless the user
says the surfaces may differ.

Shared helpers live in `claims_trees.py`. Rebuild
`claims_desk.html` after a desk change. Do not invent a second
scoring path for the workshop.
