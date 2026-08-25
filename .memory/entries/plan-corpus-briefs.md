---
id: plan-corpus-briefs
type: plan
project: earnings-call-summarizer
parent_id: plan-6eca5d31
title: Keep raw transcripts off the memory tree
node_label: Corpus briefs
tags: angelo,corpus,transcripts,filings,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-25T18:03:00+00:00'
updated_at: '2026-08-25T18:03:00+00:00'
---
User confirmed 25 Aug 2026: raw transcripts and SEC pulls stay off
git and off the Angelo memory tree. History in the model is briefs
and entries, not window dumps.

First cut: ignore the leftover corpus, record the decision, write
one healthcare leftover brief. DVC only if a second machine needs
the bytes. Do not invent ISINs or `generated_at`.
