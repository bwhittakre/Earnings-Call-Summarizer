---
id: note-hc-leftover-ibes-aliases
type: note
project: earnings-call-summarizer
parent_id: plan-hc-overnight-gate
title: Leftover IBES tickers are aliases, not exchange tickers
node_label: Leftover IBES aliases
tags: healthcare,identity,ibes,lseg,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-26T15:36:00+00:00'
updated_at: '2026-08-26T15:36:00+00:00'
---
Live LSEG A822 ISIN→INSTRPERMID→primary IBES on 26 Aug 2026.
Same pattern as UNH→UNIH. Do not bind the prefix aliases.

| Ticker | ISIN | estpermid | IBES | Barra |
|---|---|---|---|---|
| DHR | US2358511028 | 30064836230 | DMG | USADTY1 |
| SYK | US8636671013 | 30064857950 | STRY | USAN4Z1 |
| GILD | US3755581036 | 30064840651 | GIL1 | USAREJ1 |
| VRTX | US92532F1003 | 30064861819 | VRT1 | USAOKE1 |
| ELV | US0367521038 | 30064829391 | ATHI | USA4NM1 |

Not bound: DHRM, SYK1/SYKE, ELVT/ELVA. Exact `IBESTICKER=ticker`
missed for the same reason UNH did.
