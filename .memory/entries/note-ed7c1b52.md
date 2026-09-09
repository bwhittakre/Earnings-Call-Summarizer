---
id: note-ed7c1b52
type: note
project: earnings-call-summarizer
parent_id: note-1492ba44
title: APH regime gap fixed — R. Adam Norwitt added (FY2009-Q1, no end)
node_label: APH regime gap fixed — R. Adam Norwitt added (FY20
tags: ''
status: active
open_threads: 0
success: 'null'
files: config/management_regimes.json
session_id: sess-7113be9f
created_at: '2026-09-08T13:59:30.977109+00:00'
updated_at: '2026-09-08T13:59:30.977109+00:00'
---
APH (Amphenol) had zero entries in config/management_regimes.json, causing all 16 of its ops-book trees to fall into the 'unknown' regime bucket in the claims desk HTML.

Added regime:
- regime_id: aph-norwitt-ceo
- named_person: R. Adam Norwitt
- start_fiscal: FY2009-Q1 (Jan 1, 2009; APH FYE Dec 31)
- end_fiscal: null (current)

Sidecar rebuilt: 74 regimes total (was 73). desk_ops_v2 now has 35 regime buckets (was 34). APH trees will be attributed correctly on next HTML rebuild.
