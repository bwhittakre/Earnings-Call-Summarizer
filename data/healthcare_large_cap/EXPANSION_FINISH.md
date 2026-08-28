# Healthcare large-cap — expansion finish leftovers

Two-quarter identity+join tests finished **26 Aug 2026**. Watcher stays
stopped. Do not restart `scripts/_healthcare_onboard_watch.py`.
Do not invent ISINs. Identity is ISIN-first.
Do not compute Rank IC until the gate in `plan-healthcare-rank-ic-studies`
is met (tagged `healthcare_large_cap` pack with a real `generated_at`).
Do not mix into live `xlk_tech` / SQLite Roz book.
Do not overwrite the locked 17 Aug tech eval
(`generated_at=2026-08-17T17:28:40+00:00`).

Overnight leftover-history prep: `scripts/_hc_leftover_history.py`
(default dry-run). Do not `--apply-overlays` / `--score` until the user
says go.

## Onboarded (full feature panels)

13 names: `ABBV ABT AMGN BMY BSX CI ISRG JNJ MDT MRK PFE REGN TMO`

## Leftovers — two-quarter panels exist, history not scored

Seed for all 20 is on disk (known Quartr gaps left missing).
Each leftover has a 16-row FY2026-Q1/Q2 panel and chronological deltas.
Overlays are still short (prior FY2025-Q4, output FY2026-Q1/Q2).

| Ticker | ISIN | Quartr | estpermid | IBES | Barra | Transcripts |
|---|---|---|---|---|---|---|
| LLY | US5324571083 | 5159 | 30064846182 | (Lilly) | USAI951 | 43 (FY2015-Q4–FY2026-Q2) |
| UNH | US91324P1021 | 4258 | 30064860782 | UNIH | USAO6Z1 | 43 |
| DHR | US2358511028 | 3685 | 30064836230 | DMG | USADTY1 | 43 |
| SYK | US8636671013 | 4857 | 30064857950 | STRY | USAN4Z1 | 43 |
| GILD | US3755581036 | 5113 | 30064840651 | GIL1 | USAREJ1 | 34 (FY2018-Q1–FY2026-Q2) |
| VRTX | US92532F1003 | 6557 | 30064861819 | VRT1 | USAOKE1 | 34 |
| ELV | US0367521038 | 3742 | 30064829391 | ATHI | USA4NM1 | 34; FY2015–2017 Q4 missing |

Lloyds `GB0005163141` is dropped. Do not call full `run_onboard`.

When scoring history: `python scripts/_hc_leftover_history.py --apply-overlays`
then `--score` (no `--force`). Stamp only with
`--output-tag healthcare_large_cap`.
