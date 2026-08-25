---
id: note-isin-identity
type: note
project: earnings-call-summarizer
parent_id: plan-rank-ic-phase1
title: Identity resolution is ISIN-first because IBES tickers get recycled
node_label: ISIN-first identity
tags: gotcha,snowflake,lseg,ibes,identity,onboarding
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-17T20:04:00+00:00'
updated_at: '2026-08-17T20:04:00+00:00'
---
Why `lookup_ids_from_lseg` in `Structured Narrative/company_config.py` takes the route it does.

## The hazard
`IBESTICKER` is recycled. STRW's IBES ticker historically pointed at a 1990s entity, so a
bare ticker lookup can silently bind a company to another firm's `ESTPERMID` — and every
downstream quant join inherits that error without complaint.

## The resolution order
1. **ISIN to INSTRPERMID to the instrument's primary IBES mapping.** This deliberately does
   *not* require `IBESTICKER` to equal the exchange ticker — STRW legitimately maps to `04Y9`.
2. **If no ISIN is configured**, recover one from the ticker via `VW_IBES2MAPPING` to
   `PERMISINDATA`, then rejoin at step 1. This hop still trusts `IBESTICKER`, so a recycled
   ticker can mislead it — always pass ISIN at onboard when it is known.
3. **Bare ticker lookup is the last resort only.**

For Barra, prefer `ROOT_BARRAID` (the US issuer root) over listing-local `BARRA_ID`
variants, and accept any `US*` prefix rather than only `USA*` — STRW is `USBOFP1` while
CSCO is `USACX21`.

## Verified live
`scripts/_probe_identity_resolution.py` is a read-only probe that resolves each ticker twice,
once as configured and once with the ISIN cleared, against the live LSEG/MSCI share. It
demonstrated the recycled-ticker hazard on STRW directly. As of 17 August every company in
`COMPANIES` has an ISIN configured, so none are currently exposed to the risky path.
