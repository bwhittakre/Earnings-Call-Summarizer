---
id: chec-aug17-session
type: checkpoint
project: earnings-call-summarizer
parent_id: plan-rank-ic-phase1
title: '17 Aug: workbench merged, artifacts regenerated, 546 tests green'
node_label: '17 Aug checkpoint'
tags: checkpoint,august-2026,regen,merge
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-08-17T20:06:00+00:00'
updated_at: '2026-08-17T20:06:00+00:00'
---
State at the end of 17 August 2026.

## Done
- **Correctness pass** over three weeks of unreviewed code produced nine fixes, spanning
  horizon ordering, fiscal-period matching in the Street overlay, corrupt-store handling in
  `lab_store.py`, the consolidated panel's default period bucket, and a `.gitignore` bug
  where unanchored ticker patterns (`NVDA/`) were silently ignoring `tests/fixtures/filings`.
- **Merge** of `cursor/automated-earnings-monitor` into `cursor/call-ticker-reaction`
  (commit `981c673`), with a `pre-merge-aem-backup` tag for rollback. Conflicts resolved in
  `panel_html.py`, `build_consolidated_panel_report.py`, `company_config.py`,
  `run_company_pipeline.py`, `narrative_zscore.py` and `quant_quality.py`.
- **Jackknife ghost-file fix** plus a full 24.5-minute Rank IC regeneration with jackknife
  enabled. All artifacts now stamped consistently 08-17 13:28 across 25 tickers, and the
  consolidated feature panel rebuilt (it had been stale from 08-11).
- **546 tests passing**, including two new regression tests for `drop_stale_csv`.
- Pre-regen artifacts backed up at `C:\Users\BobbyWhittaker\AppData\Local\Temp\roz-crosscompany-backup-20260817`.

## Corpus scale
26 companies, 950 scored quarters, 46 fiscal periods, 14,855 evidence excerpts at 100%
transcript-supported (10,587 verbatim / 3,357 composite / 911 anchored).

## Open threads
- Rebuild `.venv` on Python 3.12 — currently dead, pipeline runs on system Python.
- Reconcile the `.new` config files left by `angelo update --keep-edits`.
- Angelo assessment concluded the zettelkasten's grounded-extraction feature duplicates what
  this pipeline already does better; its real use here would be a methodology-literature
  corpus, not earnings calls. Do **not** run the shipped `earnings` extraction schema over
  the transcripts.
