---
id: deci-monitored-universe
type: decision
project: earnings-call-summarizer
parent_id: plan-monitor-automation
title: Monitoring watches every onboarded company; the research book stays separate
node_label: Monitored universe split
tags: monitor,eligibility,discovery,onboarding,gotcha
status: active
open_threads: 0
success: 'null'
files: ''
created_at: '2026-09-02T14:00:00+00:00'
updated_at: '2026-09-02T14:20:00+00:00'
---
The monitor was watching **5 companies out of 45 onboarded**, and nothing anywhere said so.

> **Scope correction (2 Sept).** This fixes a real gate, but it is *not* the whole reason
> calls were missed. Forensics on the live DB showed only one event ever armed
> automatically -- see the "Automation never actually ran" note. Eligibility is the second
> gate; the missing event source is the first.

## The two questions that had been conflated
Who we watch for earnings calls, and who Rank IC ranks against each other, are different
questions. `eligible_discovery_tickers` answered both with one list: the research book
intersected with the on-disk overlays. That was invisible while both sets were the same
tech names.

Two independent things then broke it, and both fail silently -- `service.discover` just
does `if event.ticker not in eligible: continue`, with no log line.

1. **The healthcare onboard passed `skip_book_sync=True`** (deliberately, to protect the
   Rank IC comparison pool), which kept 20 names out of `roz_book_tickers` and therefore
   out of discovery as a side effect nobody intended.
2. **The original tech book has no overlay files at all.** AAPL, MSFT, AMZN, AVGO and 16
   others predate the overlay format and live only in `company_config.COMPANIES`. The
   intersection dropped every one of them. This is the bigger half of the bug and had
   nothing to do with healthcare.

## The decision
The monitored universe is **every onboarded company** -- the union of on-disk overlays and
the in-code `COMPANIES` registry, since `get_company` already treats both as valid
onboarding records. `roz_book_tickers` stays exactly what it was: the research comparison
set. `skip_book_sync` now means only "keep off the research book" and no longer removes a
company from monitoring.

Measured on the live repo: **5 watched before, 45 after (+40)**.

## Escape hatches, both one env var
- `EARNINGS_MONITOR_EXCLUDE_TICKERS` drops a name from watch without deleting the record
  that it was onboarded.
- `EARNINGS_MONITOR_UNIVERSE_MODE=book` restores the old intersection wholesale.

## Why not backfill overlays for the legacy names instead
It was the tempting fix -- make overlays the single source of truth -- but `get_company`
**prefers an on-disk overlay over the in-code profile**, so a thin generated overlay would
shadow a correct `COMPANIES` entry and could quietly change scoring inputs. Reading both
sources touches no data and cannot affect the pipeline.

`registry_tickers` checks that the imported `company_config.__file__` actually lives under
the requested repo_root. Python caches modules by bare name, so without that check a test
using a temp repo_root silently inherits the real repo's 23 tickers.
