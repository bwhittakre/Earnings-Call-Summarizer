---
id: deci-corpus-briefs-not-blobs
type: decision
project: earnings-call-summarizer
parent_id: plan-corpus-briefs
title: Transcripts and SEC pulls are corpus, not memory-tree documents
node_label: Briefs not blobs
tags: angelo,corpus,transcripts,filings,gitignore,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-25T18:03:00+00:00'
updated_at: '2026-08-25T18:03:00+00:00'
---
Resolved 25 Aug 2026.

Angelo `documents` registers markdown reports linked to a phase.
Memory entries record counts, gaps, and next steps. Neither store
holds Quartr windows, assembled `transcripts_raw`, or SEC text.

Pipeline homes stay where they already are:
- assembled calls: `Structured Narrative/transcripts_raw/` (gitignored)
- reserved slots: `data/transcripts/`, `data/filings/`
- leftover persist windows: `data/healthcare_large_cap/windows/` (now ignored)
- leftover SEC pulls: `data/documents/` (now ignored)

Going forward, after a seed or onboard, write one short entry (and
a brief if the inventory changed). Do not `git add` the corpus.
Do not pin thousands of dumps via `record(files=...)`.
DVC / memory-artifacts is the later path if the bytes must be shared.
