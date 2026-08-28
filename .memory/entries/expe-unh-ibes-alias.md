---
id: expe-unh-ibes-alias
type: experiment
project: earnings-call-summarizer
parent_id: plan-unh-two-quarter
title: UNH exact IBES miss; UNHC is a different instrument
node_label: UNH not UNHC
tags: healthcare,unh,identity,lseg,august-2026
status: active
open_threads: 1
success: 'false'
files: ''
created_at: '2026-08-25T18:58:00+00:00'
updated_at: '2026-08-25T18:58:00+00:00'
---
25 Aug 2026 LSEG probe, ISIN cleared.

`IBESTICKER = UNH` and IRIS_UNIV ticker UNH: empty.
`IBESTICKER LIKE 'UNH%'` hit one row: IBES `UNHC`, estpermid
`30064860776`, SOURCE `INSTRUMENT`, INSTRPERMID `8589967521`.
`PERMISINDATA` ISIN for that instrument: `US9091961071`.

Do not bind UNH / UnitedHealth to `UNHC` or `US9091961071`.
Quartr 10-K documentId 2974558 (filed 2026-01-27) cover confirms
ticker UNH and registrant UnitedHealth Group Incorporated; CUSIP
was not in the page-1 extract.
