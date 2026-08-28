# Healthcare Large-Cap onboard status

Sector file: `config/sectors/healthcare_large_cap.txt`
Quartr watchlist: 27941 (https://web.quartr.com/watchlist/27941)
Lookback: 2016-01-01 → 2026-08-19
Path: Quartr MCP `read_transcript` → `Structured Narrative/transcripts_raw/{TICKER}_FY….txt` → Roz onboard `--skip-pull --skip-book-sync`

Live `xlk_tech` / SQLite Roz book is **not** rewritten.

Onboard watcher: `scripts/_healthcare_onboard_watch.py` — **stopped**.
Do not restart it.

Leftover history scored 26 Aug 2026 (no `--force`, no `run_onboard`).
Tagged eval: `narrative_signal_eval_healthcare_large_cap.json`
`generated_at=2026-08-26T22:48:11+00:00`. Locked tech book unchanged
(`generated_at=2026-08-17T17:28:40+00:00`).
Known remaining one-quarter panel holes (not leftovers): CI FY2018-Q4,
TMO FY2017-Q2.

## Seed waves

| Wave | Tickers |
|---|---|
| A | LLY UNH JNJ ABBV MRK |
| B | TMO ABT DHR PFE AMGN |
| C | ISRG SYK GILD VRTX MDT |
| D | BMY REGN CI ELV BSX |
