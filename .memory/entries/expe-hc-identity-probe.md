---
id: expe-hc-identity-probe
type: experiment
project: earnings-call-summarizer
parent_id: plan-hc-overnight-gate
title: LSEG ticker-hop probe for seven healthcare leftovers
node_label: HC identity probe
tags: healthcare,identity,lseg,isin,august-2026
status: active
open_threads: 1
success: 'false'
files: ''
created_at: '2026-08-25T18:26:54+00:00'
updated_at: '2026-08-25T18:26:54+00:00'
---
Read-only `lookup_ids_from_lseg` with ISIN cleared. Snowflake connect
took ~3.5 minutes. Source: local probe 25 Aug 2026 18:26Z.

LLY resolved: estpermid `30064846182`, ISIN `US5324571083`,
barra `USAI951`, IBES `LLY`. The overlay ISIN `GB0005163141` is still
wrong (Lloyds). The estpermid matches that overlay; the new fact is
the US ISIN plus IBES ticker `LLY` on the cleared hop.

UNH DHR SYK GILD VRTX ELV: all fields None. Do not invent ISINs.
Do not treat those six as resolved.
