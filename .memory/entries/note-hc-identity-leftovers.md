---
id: note-hc-identity-leftovers
type: note
project: earnings-call-summarizer
parent_id: plan-healthcare-onboard
title: 'Healthcare onboard leftover: 7 names need verified ISINs'
node_label: HC identity leftovers
tags: healthcare,onboard,identity,isin,leftover,august-2026
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-25T17:23:00+00:00'
updated_at: '2026-08-25T17:23:00+00:00'
---
Watcher and keep-awake stopped 25 Aug 2026 ~13:23 ET on user request.

Onboarded (feature panels exist, split `healthcare_large_cap-2026-08-25`):
ABBV ABT AMGN BMY BSX CI ISRG JNJ MDT MRK PFE REGN TMO (13).

Pending identity — `estpermid` missing after Snowflake/LSEG lookup; transcripts already seeded:
LLY UNH DHR SYK GILD VRTX ELV (7).

Resume: verified ISIN (or estpermid / barra-id) per name, then
`run_onboard(skip_pull=True, skip_book_sync=True, research_sector=healthcare_large_cap)`.
Then stamp the `healthcare_large_cap` book. Do not invent ISINs. Do not invent `generated_at`.
LLY overlay ISIN `GB0005163141` is unverified (likely Lloyds, not Lilly).

Disk: `data/healthcare_large_cap/EXPANSION_FINISH.md` and `expansion_leftovers.json`.
