---
id: note-hc-leftover-cusip-gap
type: note
project: earnings-call-summarizer
parent_id: plan-hc-overnight-gate
title: Leftover 10-Ks confirm FYE but do not print common-stock CUSIP
node_label: Leftover CUSIP gap
tags: healthcare,identity,isin,cusip,august-2026
status: active
open_threads: 1
success: 'null'
files: ''
created_at: '2026-08-26T15:25:00+00:00'
updated_at: '2026-08-26T15:25:00+00:00'
---
26 Aug Quartr 10-K cover reads for the five leftover names. All five
fiscal years ended December 31, 2025 → `calendar_fiscal` written in
`config/fiscal_calendars.yaml`. Data sourced from Quartr.

| Ticker | companyId | 10-K documentId | FYE |
|---|---|---|---|
| DHR | 3685 | 2917984 | 31 Dec 2025 |
| SYK | 4857 | 2804126 | 31 Dec 2025 |
| GILD | 5113 | 2917906 | 31 Dec 2025 |
| VRTX | 6557 | 2822073 | 31 Dec 2025 |
| ELV | 3742 | 2763221 | 31 Dec 2025 |

Quartr OCR on those covers (and `search_documents` for CUSIP) did not
return a common-stock CUSIP. SYK hits were euro-note CUSIP language
only. DHR `get_company` still has no ISIN field.

Do not invent ISINs. Do not bind prefix aliases (DHR→DHRM, SYK→SYK1/SYKE,
ELV→ELVT/ELVA). Same Bloomberg-paste path that closed UNH is still the
fastest close for these five.
