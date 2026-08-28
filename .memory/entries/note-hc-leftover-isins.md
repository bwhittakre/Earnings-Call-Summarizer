---
id: note-hc-leftover-isins
type: note
project: earnings-call-summarizer
parent_id: plan-hc-overnight-gate
title: User-sourced leftover ISINs bind the five Quartr healthcare names
node_label: Leftover ISIN paste
tags: healthcare,identity,isin,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-26T15:33:00+00:00'
updated_at: '2026-08-26T15:33:00+00:00'
---
User pasted five ISINs on 26 Aug 2026 (typed SYX for Stryker).
Each was searched on Quartr `search_companies` before any overlay write.
One match each. Data sourced from Quartr.

| Ticker | ISIN | companyId | Name |
|---|---|---|---|
| DHR | US2358511028 | 3685 | Danaher |
| SYK | US8636671013 | 4857 | Stryker |
| GILD | US3755581036 | 5113 | Gilead Sciences |
| VRTX | US92532F1003 | 6557 | Vertex Pharmaceuticals |
| ELV | US0367521038 | 3742 | Elevance Health |

Do not bind prefix aliases. LSEG estpermid/barra still pending a live
A822 resolve. Short two-quarter overlays only after that resolve.
Do not call full `run_onboard`. Do not stamp `healthcare_large_cap`.
