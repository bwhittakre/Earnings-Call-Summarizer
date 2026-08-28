---
id: expe-hc-identity-debug
type: experiment
project: earnings-call-summarizer
parent_id: plan-unh-two-quarter
title: Debug leftover identity — exact IBES miss, prefix is other issuers
node_label: Identity debug
tags: healthcare,identity,lseg,debug,august-2026
status: active
open_threads: 1
success: 'false'
files: ''
created_at: '2026-08-25T19:03:00+00:00'
updated_at: '2026-08-25T19:03:00+00:00'
---
Source: `debug-bacdcd.log` pre-fix run 25 Aug 2026.

H1 confirmed: LLY exact IBES hit; UNH DHR SYK GILD VRTX ELV exact_hit false.
H2 confirmed as IRIS *database missing* (10 dbs, not a ticker miss).
H3 rejected: LSEG A822 share is present (`_SHARE_A822_UDC29514`).
H4 confirmed: bare ticker also empty; not a dead cursor.
H5 confirmed: prefix aliases are other instruments (UNHC, DHRM,
SYK1/SYKE, ELVT/ELVA). GILD and VRTX have zero prefix hits.
Do not auto-bind aliases. Require a sourced ISIN.
