# Healthcare large-cap — expansion finish leftovers

Stopped **25 Aug 2026 ~13:23 ET**. Watcher and keep-awake killed on request.
Do not restart `scripts/_healthcare_onboard_watch.py` until the identity list below is resolved.
Do not invent ISINs. Identity is ISIN-first (`note-isin-identity`).
Do not compute Rank IC until the gate in `plan-healthcare-rank-ic-studies` is met.
Do not mix into live `xlk_tech` / SQLite Roz book.

## Onboarded (feature panels exist)

13 names, `Structured Narrative/output/{TICKER}` scored:

`ABBV ABT AMGN BMY BSX CI ISRG JNJ MDT MRK PFE REGN TMO`

Seed for all 20 is already on disk (known Quartr gaps left missing).

## Still needed — identity, then `run_onboard`

All seven failed Snowflake/LSEG `estpermid` lookup. Transcripts are seeded. Pass a **verified ISIN** (recommended) or `--estpermid` / `--barra-id`. Then:

```
run_onboard(skip_pull=True, skip_book_sync=True, research_sector=healthcare_large_cap)
```

| Ticker | Seed | Why parked | Overlay note |
|---|---|---|---|
| LLY | seeded | `estpermid` missing / refused | `LLY.json` ISIN `GB0005163141` is **unverified** (looks like Lloyds, not Lilly). `estpermid` `30064846182` is from a failed run. Do not treat as Lilly. |
| UNH | seeded | `estpermid` missing | no overlay |
| DHR | seeded | `estpermid` missing | no overlay |
| SYK | seeded | `estpermid` missing | no overlay |
| GILD | seeded | `estpermid` missing | no overlay |
| VRTX | seeded | `estpermid` missing | no overlay |
| ELV | seeded (FY2018-Q1–FY2026-Q2; gaps FY2015–2017 Q4) | `estpermid` missing | no overlay |

Machine list: `expansion_leftovers.json`.
