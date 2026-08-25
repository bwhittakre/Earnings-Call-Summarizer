# Healthcare corpus brief — 25 Aug 2026

Linked to `plan-healthcare-onboard`, `note-hc-identity-leftovers`,
`todo-hc-expansion-finish`. Source of the leftover lists:
`data/healthcare_large_cap/EXPANSION_FINISH.md`.

This is an inventory, not the transcripts. Window JSON and SEC
text stay on disk and out of git.

## Onboarded (13)

Feature panels exist under `Structured Narrative/output/{TICKER}`:

`ABBV ABT AMGN BMY BSX CI ISRG JNJ MDT MRK PFE REGN TMO`

## Pending identity (7)

Transcripts are seeded. `estpermid` missing after LSEG lookup.
Do not invent ISINs. Then
`run_onboard(skip_pull=True, skip_book_sync=True, research_sector=healthcare_large_cap)`.

`LLY UNH DHR SYK GILD VRTX ELV`

LLY overlay ISIN `GB0005163141` is unverified (likely Lloyds, not
Lilly). Do not treat it as Lilly.

ELV seed: FY2018-Q1–FY2026-Q2; FY2015–2017 Q4 left missing.

## Watcher

Stopped 25 Aug 2026 ~13:23 ET. Do not restart until the identity
list is resolved.

## Disk (regenerable, gitignored)

- `data/healthcare_large_cap/windows/` — persist-window JSON
- `Structured Narrative/transcripts_raw/` — assembled calls
- `data/documents/` — AMZN / NVDA SEC pulls (not the healthcare path)
