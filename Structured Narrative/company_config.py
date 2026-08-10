#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-ticker registry for the Structured Narrative multi-company pilot."""
from __future__ import annotations

from dataclasses import dataclass, field, replace


FY2025_OUTPUT_QUARTERS = (
    "FY2025-Q1",
    "FY2025-Q2",
    "FY2025-Q3",
    "FY2025-Q4",
)

FY2026_OUTPUT = (
    "FY2026-Q1",
    "FY2026-Q2",
    "FY2026-Q3",
)

# Legacy calendar-aligned 8Q window for eval exports. Live batch runs use ROIC.ai
# ``--last 8`` (see roic_quarters.py / run_pilot_8q_batch.py) — the 8 most recent
# earnings calls ROIC has per company, not this fixed FY2025–FY2026 span.
PILOT_OUTPUT_QUARTERS = FY2025_OUTPUT_QUARTERS + FY2026_OUTPUT + ("FY2026-Q4",)

FY2024_PRIOR_QUARTERS = ()

# FY2024-Q4 is fully scored (dimensions/delta/surprise/novelty) for MSFT and AAPL
# and now bridges their 5-year historical backfill into the FY2025-FY2026 pilot
# window as a real output quarter, mirroring AMZN_FULL_OUTPUT_QUARTERS below.
# NVDA's FY2024-Q4 is intentionally excluded here: only a partial dimensions
# score exists (no delta/surprise/novelty, no local transcript) — see
# output/NVDA/json/quarter_registry.json.
FY2024_Q4_BRIDGE = ("FY2024-Q4",)
PILOT_OUTPUT_QUARTERS_WITH_BRIDGE = FY2024_Q4_BRIDGE + PILOT_OUTPUT_QUARTERS

# AMZN 5-year historical run: transcripts in Structured Narrative/AMZN/
# FY2019-Q2 is prior-only (delta baseline for FY2019-Q3); not in published outputs.
# Kept as-is (unchanged) because get_company(scope="five_year") below still
# returns exactly this narrower window for callers that ask for it.
AMZN_FIVE_YEAR_PRIOR_QUARTERS = ("FY2019-Q2",)
AMZN_FIVE_YEAR_OUTPUT_QUARTERS = (
    "FY2019-Q3",
    "FY2019-Q4",
    "FY2020-Q1",
    "FY2020-Q2",
    "FY2020-Q3",
    "FY2020-Q4",
    "FY2021-Q1",
    "FY2021-Q2",
    "FY2021-Q3",
    "FY2021-Q4",
    "FY2022-Q1",
    "FY2022-Q2",
    "FY2022-Q3",
    "FY2022-Q4",
    "FY2023-Q1",
    "FY2023-Q2",
    "FY2023-Q3",
    "FY2023-Q4",
    "FY2024-Q1",
    "FY2024-Q2",
    "FY2024-Q3",
)

# 2026-07-27: transcripts extended back to FY2016-Q2 (Structured Narrative/AMZN/).
# New prior-only baseline is FY2016-Q2; FY2016-Q3..FY2019-Q1 are new output
# quarters; FY2019-Q2 (the old prior-only baseline) is promoted to a full
# output quarter — run_universe_batch.py needs --extra-output-quarters
# FY2019-Q2 the first time this runs, same promotion pattern used for
# IBM_PRIOR_QUARTERS's FY2017-Q3 above.
# 2026-07-29: extended one more quarter back to FY2016-Q1 (Quartr transcript,
# eventId 63596) so the FY2016-Q1 quant-Z PIT warmup clears comfortably before
# the requested 2016-Q2 calendar-quarter analysis start (see START_DATE
# widening in single_company_extractor.py). FY2016-Q2 (the old prior-only
# baseline) is promoted to a full output quarter, prepended below —
# run_universe_batch.py needs --extra-output-quarters FY2016-Q2 the first
# time this runs, same promotion pattern as FY2019-Q2 above.
AMZN_EXTENDED_PRIOR_QUARTERS = ("FY2016-Q1",)
AMZN_EXTENDED_NEW_OUTPUT_QUARTERS = (
    "FY2016-Q2",
    "FY2016-Q3",
    "FY2016-Q4",
    "FY2017-Q1",
    "FY2017-Q2",
    "FY2017-Q3",
    "FY2017-Q4",
    "FY2018-Q1",
    "FY2018-Q2",
    "FY2018-Q3",
    "FY2018-Q4",
    "FY2019-Q1",
)

# AMZN published panel: FY2016-Q3 extended history + promoted FY2019-Q2 +
# five-year history + FY2024-Q4 bridge (already scored) + pilot FY2025-FY2026.
AMZN_FULL_OUTPUT_QUARTERS = (
    AMZN_EXTENDED_NEW_OUTPUT_QUARTERS
    + ("FY2019-Q2",)
    + AMZN_FIVE_YEAR_OUTPUT_QUARTERS
    + ("FY2024-Q4",)
    + PILOT_OUTPUT_QUARTERS
)

PILOT_TICKERS = ("AMZN", "MSFT", "NVDA", "AAPL")
DEFAULT_TICKER = "AMZN"

# ---------------------------------------------------------------------------
# 2026-07-27: pilot-4 historical backfill. Transcripts in Structured
# Narrative/<TICKER>/ now extend back to 2016-2017 for AAPL/MSFT/NVDA (mirrors
# the AMZN five-year-run backfill above and the Phase 3 tickers below). Each
# ticker's prior_quarters is its single earliest available transcript (delta
# baseline only); *_NEW_OUTPUT_QUARTERS is every other transcript on disk
# through FY2024-Q3/Q4, prepended to the existing PILOT tail so the FY2025-
# FY2026 pilot window and (for MSFT/AAPL) the FY2024-Q4 bridge are unaffected.
# 2026-07-29: extended back to FY2016-Q2 (new prior-only baseline), mirroring
# AMZN_EXTENDED_PRIOR_QUARTERS above. FY2016-Q3 (the old prior-only baseline)
# is promoted to a full output quarter, prepended to AAPL_NEW_OUTPUT_QUARTERS.
# 2026-07-29 (later same day): extended one more quarter back to FY2016-Q1
# (Quartr transcript, eventId 63219) for quant-Z PIT warmup buffer ahead of
# the 2016-Q2 calendar-quarter analysis start. FY2016-Q2 (the old prior-only
# baseline) is promoted to output, prepended below — run_universe_batch.py
# needs --extra-output-quarters FY2016-Q2 the first time this runs.
AAPL_PRIOR_QUARTERS = ("FY2016-Q1",)
AAPL_NEW_OUTPUT_QUARTERS = (
    "FY2016-Q2",
    "FY2016-Q3",
    "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3", "FY2017-Q4", "FY2018-Q1",
    "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1", "FY2019-Q2", "FY2019-Q3",
    "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3", "FY2020-Q4", "FY2021-Q1",
    "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1", "FY2022-Q2", "FY2022-Q3",
    "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3", "FY2023-Q4", "FY2024-Q1",
    "FY2024-Q2", "FY2024-Q3",
)
# AAPL's FY2024-Q4 is already scored via PILOT_OUTPUT_QUARTERS_WITH_BRIDGE (see
# FY2024_Q4_BRIDGE comment above) — do not duplicate it here.
AAPL_FULL_OUTPUT_QUARTERS = AAPL_NEW_OUTPUT_QUARTERS + PILOT_OUTPUT_QUARTERS_WITH_BRIDGE

# 2026-07-29: extended back to FY2016-Q2 (new prior-only baseline), mirroring
# AMZN_EXTENDED_PRIOR_QUARTERS above. FY2016-Q3/Q4 (the old prior-only
# baseline) are promoted to full output quarters, prepended below.
# 2026-07-29 (later same day): extended one more quarter back to FY2016-Q1
# (Quartr transcript, eventId 62736) for quant-Z PIT warmup buffer ahead of
# the 2016-Q2 calendar-quarter analysis start. FY2016-Q2 (the old prior-only
# baseline) is promoted to output, prepended below — run_universe_batch.py
# needs --extra-output-quarters FY2016-Q2 the first time this runs.
MSFT_PRIOR_QUARTERS = ("FY2016-Q1",)
MSFT_NEW_OUTPUT_QUARTERS = (
    "FY2016-Q2",
    "FY2016-Q3", "FY2016-Q4",
    "FY2017-Q1", "FY2017-Q2", "FY2017-Q3", "FY2017-Q4", "FY2018-Q1", "FY2018-Q2",
    "FY2018-Q3", "FY2018-Q4", "FY2019-Q1", "FY2019-Q2", "FY2019-Q3", "FY2019-Q4",
    "FY2020-Q1", "FY2020-Q2", "FY2020-Q3", "FY2020-Q4", "FY2021-Q1", "FY2021-Q2",
    "FY2021-Q3", "FY2021-Q4", "FY2022-Q1", "FY2022-Q2", "FY2022-Q3", "FY2022-Q4",
    "FY2023-Q1", "FY2023-Q2", "FY2023-Q3", "FY2023-Q4", "FY2024-Q1", "FY2024-Q2",
    "FY2024-Q3",
)
# MSFT's FY2024-Q4 is already scored via PILOT_OUTPUT_QUARTERS_WITH_BRIDGE — do
# not duplicate it here.
MSFT_FULL_OUTPUT_QUARTERS = MSFT_NEW_OUTPUT_QUARTERS + PILOT_OUTPUT_QUARTERS_WITH_BRIDGE

# NVDA now has a real local FY2024-Q4 transcript (previously only a partial
# dimensions-only score existed with no transcript — see the now-stale
# FY2024_Q4_BRIDGE comment above, which still applies to MSFT/AAPL only).
# Because FY2024-Q4 is included directly in NVDA_NEW_OUTPUT_QUARTERS below,
# NVDA must use the plain PILOT_OUTPUT_QUARTERS tail (NOT
# PILOT_OUTPUT_QUARTERS_WITH_BRIDGE), or FY2024-Q4 would be duplicated.
# NVDA also has a new FY2027-Q1 transcript (closest available quarter to the
# requested 2026-Q1 calendar boundary) appended after the pilot tail.
# 2026-07-29: extended back to FY2016-Q2 (new prior-only baseline), mirroring
# AMZN_EXTENDED_PRIOR_QUARTERS above. FY2016-Q3/Q4 and FY2017-Q1/Q2 (the old
# prior-only baseline) are promoted to full output quarters, prepended below.
# 2026-07-29 (later same day): extended one more quarter back to FY2016-Q1
# (Quartr transcript, eventId 63139) for quant-Z PIT warmup buffer ahead of
# the 2016-Q2 calendar-quarter analysis start. FY2016-Q2 (the old prior-only
# baseline) is promoted to output, prepended below — run_universe_batch.py
# needs --extra-output-quarters FY2016-Q2 the first time this runs.
NVDA_PRIOR_QUARTERS = ("FY2016-Q1",)
NVDA_NEW_OUTPUT_QUARTERS = (
    "FY2016-Q2",
    "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2",
    "FY2017-Q3", "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4",
    "FY2019-Q1", "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2",
    "FY2020-Q3", "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4",
    "FY2022-Q1", "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2",
    "FY2023-Q3", "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4",
)
NVDA_FULL_OUTPUT_QUARTERS = NVDA_NEW_OUTPUT_QUARTERS + PILOT_OUTPUT_QUARTERS + ("FY2027-Q1",)

# ---------------------------------------------------------------------------
# Phase 3 universe expansion — first wave onboarded from ROIC.ai-scraped
# transcripts (Structured Narrative/<TICKER>/FYyyyy-Qn.txt). Each ticker's
# prior_quarters is its single earliest available transcript (delta baseline
# only, not in published outputs); output_quarters is every other transcript
# actually on disk, in fiscal order. Some tickers have calendar gaps (ROIC
# didn't have every quarter, or a scrape attempt was Cloudflare-blocked) —
# delta scoring treats consecutive *entries in this list* as the transition,
# so a gap just means that one delta spans more than one calendar quarter;
# it does not break the pipeline. estpermid/isin/barra_id were resolved via
# Snowflake (LSEG/IBES + MSCI) on 2026-07-27 once the network policy allowed
# this environment through; the first surprise-scoring pass for these 4
# tickers ran *before* that (Snowflake was unreachable — "network policy is
# required"), so it has agrees_with_quant/narrative_quant_gap = null. A
# --force re-run of surprise scoring after single_company_extractor.py
# backfills narrative_quant.parquet will fill those in.
AVGO_PRIOR_QUARTERS = ("FY2016-Q1",)
AVGO_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2",
    # 2026-07-28: Quartr gap-fill — new transcripts through FY2026-Q2.
    "FY2024-Q3", "FY2024-Q4", "FY2025-Q1", "FY2025-Q2", "FY2025-Q3", "FY2025-Q4",
    "FY2026-Q1", "FY2026-Q2",
)

ORCL_PRIOR_QUARTERS = ("FY2016-Q1",)
ORCL_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4",
    # 2026-07-28: Quartr gap-fill — new transcripts through FY2026-Q4.
    "FY2025-Q1", "FY2025-Q2", "FY2025-Q3", "FY2025-Q4",
    "FY2026-Q1", "FY2026-Q2", "FY2026-Q3", "FY2026-Q4",
)

CRM_PRIOR_QUARTERS = ("FY2016-Q3",)
CRM_OUTPUT_QUARTERS = (
    "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3", "FY2017-Q4", "FY2018-Q1",
    "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1", "FY2019-Q2", "FY2019-Q3",
    "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3", "FY2020-Q4", "FY2021-Q1",
    "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1", "FY2022-Q2", "FY2022-Q3",
    "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3", "FY2023-Q4", "FY2024-Q1",
    "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    # 2026-07-28: Quartr gap-fill — new transcripts through FY2027-Q1.
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4",
    "FY2026-Q1", "FY2026-Q2", "FY2026-Q3", "FY2026-Q4", "FY2027-Q1",
)

# IBM's earliest available transcript moved from FY2017-Q3 to FY2016-Q2 once
# the fetcher filled in more history, so FY2017-Q3 -- previously the prior-
# only baseline -- is now an output quarter itself. run_universe_batch.py
# needs --extra-output-quarters FY2017-Q3 the first time this runs so
# finalize_and_write() promotes it (flips prior_only/output_scope, backfills
# CSV rows) instead of leaving it stranded with the old flag.
# 2026-07-29: extended one more quarter back to FY2016-Q1. Quartr's IBM
# transcript coverage only goes back to Q1 2021 (confirmed via list_documents
# across 2010-2021; nothing before 2021-04-19) and the Quartr MCP's API key
# has no ROIC.ai equivalent, so this one came from the user's Playwright/
# Camoufox ROIC.ai scraper (Transcript retriever/fetcher.py) instead, which
# had already scraped IBM/FY2016-Q1.txt (dated 2016-04-18) in a prior run --
# copied verbatim into Structured Narrative/IBM/FY2016-Q1.txt. FY2016-Q2 (the
# old prior-only baseline) is promoted to a full output quarter, prepended
# below -- run_universe_batch.py needs --extra-output-quarters FY2016-Q2 the
# first time this runs, same promotion pattern as AMZN/MSFT/NVDA/AAPL.
IBM_PRIOR_QUARTERS = ("FY2016-Q1",)
IBM_OUTPUT_QUARTERS = (
    "FY2016-Q2",
    "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3", "FY2017-Q4",
    "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1", "FY2019-Q2",
    "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3", "FY2020-Q4",
    "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1", "FY2022-Q2",
    "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    # 2026-07-28: Quartr gap-fill — new transcripts through FY2026-Q2.
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2",
)

ADBE_PRIOR_QUARTERS = ("FY2016-Q1",)
ADBE_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4",
    # 2026-07-28: Quartr gap-fill — new transcripts through FY2026-Q2.
    "FY2025-Q1", "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2",
)

# ---------------------------------------------------------------------------
# 2026-07-28: XLK tech-sector universe expansion — 11 new tickers (ACN, TXN,
# INTU, AMAT, MU, ADI, LRCX, APH, CTSH, ADSK, TEL), completing the sector
# alongside the already-onboarded MSFT/NVDA/AAPL/AVGO/ORCL/CRM/IBM/ADBE.
# Transcripts sourced from the same external ROIC.ai scrape used for the
# Phase 3 tickers above (FY2016-Q1 through ~FY2024-Q1/Q3 locally), then
# gap-filled via Quartr through each ticker's fiscal quarter closest to the
# 2026-Q1 calendar target (end of March 2026). Fiscal-quarter-end conventions
# were verified via the SEC EDGAR fiscal-profile bootstrap
# (src/ingest/edgar/fiscal_profile.py, cached under
# output_confidence/edgar_cache/fiscal_profiles/) against each ticker's real
# 10-Q/10-K reportDate history — all 11 resolved to either plain calendar-year
# fiscal years (TXN, APH, CTSH) or month-end/near-month-end offset fiscal
# years (ACN Aug31, INTU Jul31, ADSK Jan31) or 52/53-week offset fiscal years
# with a non-month-end FYE day (AMAT ~Oct26, MU ~Aug29-Sep3, ADI ~Nov1,
# LRCX ~Jun28-30, TEL ~Sep25-27) that the existing _offset_fiscal_quarter_end
# AVGO-style fix (_subtract_months_keep_day) already handles automatically —
# none of the 11 needed a new config/fiscal_calendars.yaml entry (same as
# AVGO/ORCL/CRM/IBM/ADBE above, which also have none). TEL (TE Connectivity,
# a Swiss-domiciled foreign private issuer) was double-checked and DOES file
# 10-Q/10-K on EDGAR (not 20-F/6-K), so the EDGAR-based fiscal bootstrap and
# earnings-date tooling both work normally for it. estpermid/isin/barra_id are
# left unset for all 11 — Snowflake was unreachable for the entire onboarding
# session ("Network policy is required"), so IDs could not be resolved or
# verified; run resolve_company_ids()/lookup_ids_from_snowflake() (with an
# ISIN-based lookup fallback, watching for legacy IBES ticker aliases as with
# AVGO->"AOVG" and CRM->"CRMN") once Snowflake access is restored.
ACN_PRIOR_QUARTERS = ("FY2016-Q1",)
ACN_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2",
)

TXN_PRIOR_QUARTERS = ("FY2016-Q1",)
TXN_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1",
)

INTU_PRIOR_QUARTERS = ("FY2016-Q1",)
INTU_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2", "FY2026-Q3",
)

AMAT_PRIOR_QUARTERS = ("FY2016-Q1",)
AMAT_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2",
)

MU_PRIOR_QUARTERS = ("FY2016-Q1",)
MU_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2",
)

ADI_PRIOR_QUARTERS = ("FY2016-Q1",)
ADI_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2",
)

LRCX_PRIOR_QUARTERS = ("FY2016-Q1",)
LRCX_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2", "FY2026-Q3",
)

APH_PRIOR_QUARTERS = ("FY2016-Q1",)
APH_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1",
)

CTSH_PRIOR_QUARTERS = ("FY2016-Q1",)
CTSH_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1",
)

ADSK_PRIOR_QUARTERS = ("FY2016-Q1",)
ADSK_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2", "FY2026-Q3",
    "FY2026-Q4", "FY2027-Q1",
)

TEL_PRIOR_QUARTERS = ("FY2016-Q1",)
TEL_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
    "FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1", "FY2026-Q2",
)


# Core LSEG measures — shared across tickers.
CORE_MEASURES = {
    20: "Sales",
    6: "EBIT",
    8: "EBITDA",
    27: "Gross Margin",
    9: "EPS",
    237: "Free Cash Flow",
    22: "Capex",
}

AMZN_CANDIDATE_MEASURES = {
    213: "Stock-Based Comp",
    418: "Advertising Revenue",
    431: "GMV",
    373: "Deferred Revenue",
    445: "LT Deferred Revenue",
    368: "Service Revenue",
    333: "Subscribers",
    332: "Net Subscriber Adds",
}


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    company_name: str
    estpermid: int | None = None
    isin: str | None = None
    barra_id: str | None = None
    output_quarters: tuple[str, ...] = PILOT_OUTPUT_QUARTERS
    prior_quarters: tuple[str, ...] = FY2024_PRIOR_QUARTERS
    candidate_measures: dict[int, str] = field(default_factory=dict)

    def scoring_quarters(self) -> list[str]:
        return list(self.prior_quarters) + list(self.output_quarters)

    def is_output_quarter(self, fiscal_period: str) -> bool:
        return fiscal_period in self.output_quarters

    def is_prior_only(self, fiscal_period: str) -> bool:
        return fiscal_period in self.prior_quarters

    def all_measures(self) -> dict[int, str]:
        out = dict(CORE_MEASURES)
        out.update(self.candidate_measures)
        return out


COMPANIES: dict[str, CompanyProfile] = {
    "AMZN": CompanyProfile(
        ticker="AMZN",
        company_name="Amazon.com, Inc.",
        estpermid=30064828538,
        isin="US0231351067",
        barra_id="USAXO31",
        output_quarters=AMZN_FULL_OUTPUT_QUARTERS,
        prior_quarters=AMZN_EXTENDED_PRIOR_QUARTERS,
        candidate_measures=dict(AMZN_CANDIDATE_MEASURES),
    ),
    "MSFT": CompanyProfile(
        ticker="MSFT",
        company_name="Microsoft Corporation",
        estpermid=30064848647,
        isin="US5949181045",
        barra_id="USAJ471",
        output_quarters=MSFT_FULL_OUTPUT_QUARTERS,
        prior_quarters=MSFT_PRIOR_QUARTERS,
    ),
    "NVDA": CompanyProfile(
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        estpermid=30064850531,
        isin="US67066G1040",
        barra_id="USA2HB1",
        # FY2024-Q4 now has a full local transcript + is scored via the
        # historical backfill below (NVDA_NEW_OUTPUT_QUARTERS), not the
        # MSFT/AAPL-style FY2024_Q4_BRIDGE partial-score special case.
        output_quarters=NVDA_FULL_OUTPUT_QUARTERS,
        prior_quarters=NVDA_PRIOR_QUARTERS,
    ),
    "AAPL": CompanyProfile(
        ticker="AAPL",
        company_name="Apple Inc.",
        estpermid=30064826814,
        isin="US0378331005",
        barra_id="USAB1X1",
        output_quarters=AAPL_FULL_OUTPUT_QUARTERS,
        prior_quarters=AAPL_PRIOR_QUARTERS,
    ),
    "AVGO": CompanyProfile(
        ticker="AVGO",
        company_name="Broadcom Inc.",
        # IBES carries AVGO under the legacy "AOVG" ticker alias, so
        # estpermid was resolved directly by ISIN/INSTRPERMID rather than
        # via lookup_ids_from_lseg()'s ticker-matched query (2026-07-27).
        estpermid=30064828708,
        isin="US11135F1012",
        barra_id="USAAUE1",
        output_quarters=AVGO_OUTPUT_QUARTERS,
        prior_quarters=AVGO_PRIOR_QUARTERS,
    ),
    "ORCL": CompanyProfile(
        ticker="ORCL",
        company_name="Oracle Corporation",
        estpermid=30064851314,
        isin="US68389X1054",
        barra_id="USAKBG1",
        output_quarters=ORCL_OUTPUT_QUARTERS,
        prior_quarters=ORCL_PRIOR_QUARTERS,
    ),
    "CRM": CompanyProfile(
        ticker="CRM",
        company_name="Salesforce, Inc.",
        # IBES carries CRM under the legacy "CRMN" ticker alias — see AVGO
        # note above; estpermid resolved directly by ISIN/INSTRPERMID.
        estpermid=30064834719,
        isin="US79466L3024",
        barra_id="USA1MI1",
        output_quarters=CRM_OUTPUT_QUARTERS,
        prior_quarters=CRM_PRIOR_QUARTERS,
    ),
    "IBM": CompanyProfile(
        ticker="IBM",
        company_name="International Business Machines Corporation",
        estpermid=30064843098,
        isin="US4592001014",
        barra_id="USAHC71",
        output_quarters=IBM_OUTPUT_QUARTERS,
        prior_quarters=IBM_PRIOR_QUARTERS,
    ),
    "ADBE": CompanyProfile(
        ticker="ADBE",
        company_name="Adobe Inc.",
        estpermid=30064827258,
        isin="US00724F1012",
        barra_id="USAA821",
        output_quarters=ADBE_OUTPUT_QUARTERS,
        prior_quarters=ADBE_PRIOR_QUARTERS,
    ),
    # 2026-07-28: XLK universe expansion, 11 new tickers. estpermid/isin/
    # barra_id resolved via Snowflake (IRIS_UNIV direct-ticker lookup missed
    # all 11; resolved via LSEG PERMISINDATA ISIN lookup instead). 6 matched
    # VW_IBES2MAPPING directly on the current ticker; 5 needed the legacy
    # IBES-ticker-alias workaround (same pattern as AVGO->"AOVG",
    # CRM->"CRMN"): ACN->"ACNT", MU->"DRAM", APH->"APH1", ADSK->"ACAD",
    # TEL->"TELW".
    "ACN": CompanyProfile(
        ticker="ACN",
        company_name="Accenture plc",
        estpermid=30064827148,
        isin="IE00B4BNMY34",
        barra_id="USA4JB1",
        output_quarters=ACN_OUTPUT_QUARTERS,
        prior_quarters=ACN_PRIOR_QUARTERS,
    ),
    "TXN": CompanyProfile(
        ticker="TXN",
        company_name="Texas Instruments Incorporated",
        estpermid=30064860313,
        isin="US8825081040",
        barra_id="USANM71",
        output_quarters=TXN_OUTPUT_QUARTERS,
        prior_quarters=TXN_PRIOR_QUARTERS,
    ),
    "INTU": CompanyProfile(
        ticker="INTU",
        company_name="Intuit Inc.",
        estpermid=30064843955,
        isin="US4612021034",
        barra_id="USAQ9A1",
        output_quarters=INTU_OUTPUT_QUARTERS,
        prior_quarters=INTU_PRIOR_QUARTERS,
    ),
    "AMAT": CompanyProfile(
        ticker="AMAT",
        company_name="Applied Materials, Inc.",
        estpermid=30064828322,
        isin="US0382221051",
        barra_id="USAB2N1",
        output_quarters=AMAT_OUTPUT_QUARTERS,
        prior_quarters=AMAT_PRIOR_QUARTERS,
    ),
    "MU": CompanyProfile(
        ticker="MU",
        company_name="Micron Technology, Inc.",
        estpermid=30064836455,
        isin="US5951121038",
        barra_id="USAJ4O1",
        output_quarters=MU_OUTPUT_QUARTERS,
        prior_quarters=MU_PRIOR_QUARTERS,
    ),
    "ADI": CompanyProfile(
        ticker="ADI",
        company_name="Analog Devices, Inc.",
        estpermid=30064827293,
        isin="US0326541051",
        barra_id="USAAXZ1",
        output_quarters=ADI_OUTPUT_QUARTERS,
        prior_quarters=ADI_PRIOR_QUARTERS,
    ),
    "LRCX": CompanyProfile(
        ticker="LRCX",
        company_name="Lam Research Corporation",
        estpermid=30064846429,
        isin="US5128071082",
        barra_id="USAHZM1",
        output_quarters=LRCX_OUTPUT_QUARTERS,
        prior_quarters=LRCX_PRIOR_QUARTERS,
    ),
    "APH": CompanyProfile(
        ticker="APH",
        company_name="Amphenol Corporation",
        estpermid=30064828773,
        isin="US0320951017",
        barra_id="USAAX61",
        output_quarters=APH_OUTPUT_QUARTERS,
        prior_quarters=APH_PRIOR_QUARTERS,
    ),
    "CTSH": CompanyProfile(
        ticker="CTSH",
        company_name="Cognizant Technology Solutions Corporation",
        estpermid=30064835109,
        isin="US1924461023",
        barra_id="USAZPE1",
        output_quarters=CTSH_OUTPUT_QUARTERS,
        prior_quarters=CTSH_PRIOR_QUARTERS,
    ),
    "ADSK": CompanyProfile(
        ticker="ADSK",
        company_name="Autodesk, Inc.",
        estpermid=30064827025,
        isin="US0527691069",
        barra_id="USABAQ1",
        output_quarters=ADSK_OUTPUT_QUARTERS,
        prior_quarters=ADSK_PRIOR_QUARTERS,
    ),
    "TEL": CompanyProfile(
        ticker="TEL",
        company_name="TE Connectivity plc",
        estpermid=30064858946,
        isin="CH0102993182",
        barra_id="USAAKZ1",
        output_quarters=TEL_OUTPUT_QUARTERS,
        prior_quarters=TEL_PRIOR_QUARTERS,
    ),
    # First public earnings print (FY2026-Q2). No prior transcript / delta baseline.
    # estpermid from LSEG VW_IBES2MAPPING IBESTICKER=SPCX (2026-08-04 probe).
    "SPCX": CompanyProfile(
        ticker="SPCX",
        company_name="SpaceX",
        estpermid=30064887281,
        isin=None,
        barra_id=None,
        output_quarters=("FY2026-Q2",),
        prior_quarters=(),
    ),
    # Onboard via Quartr MCP (no REST): FY2019-Q1..FY2026-Q3 transcripts on disk.
    # estpermid/isin/barra from LSEG VW_IBES2MAPPING IBESTICKER=CSCO (2026-08-06).
    "CSCO": CompanyProfile(
        ticker="CSCO",
        company_name="Cisco Systems",
        estpermid=30064834857,
        isin="US17275R1023",
        barra_id="USACX21",
        prior_quarters=("FY2019-Q1",),
        output_quarters=(
            "FY2019-Q2",
            "FY2019-Q3",
            "FY2019-Q4",
            "FY2020-Q1",
            "FY2020-Q2",
            "FY2020-Q3",
            "FY2020-Q4",
            "FY2021-Q1",
            "FY2021-Q2",
            "FY2021-Q3",
            "FY2021-Q4",
            "FY2022-Q1",
            "FY2022-Q2",
            "FY2022-Q3",
            "FY2022-Q4",
            "FY2023-Q1",
            "FY2023-Q2",
            "FY2023-Q3",
            "FY2023-Q4",
            "FY2024-Q1",
            "FY2024-Q2",
            "FY2024-Q3",
            "FY2024-Q4",
            "FY2025-Q1",
            "FY2025-Q2",
            "FY2025-Q3",
            "FY2025-Q4",
            "FY2026-Q1",
            "FY2026-Q2",
            "FY2026-Q3",
            "FY2026-Q4",
        ),
    ),
    # Onboard via Quartr MCP → transcripts_raw (no REST). 3y lookback window.
    # estpermid: ISIN US8631821019 → INSTRPERMID → IBES 04Y9 / 30064884718
    # (2026-08-07). Do NOT use IBESTICKER=STRW — that is a recycled 1990s id.
    # barra: MSCI ASSET_UNIVERSE_TS → USBOFP1.
    "STRW": CompanyProfile(
        ticker="STRW",
        company_name="Strawberry Fields REIT",
        estpermid=30064884718,
        isin="US8631821019",
        barra_id="USBOFP1",
        prior_quarters=("FY2024-Q3",),
        output_quarters=(
            "FY2024-Q4",
            "FY2025-Q1",
            "FY2025-Q2",
            "FY2025-Q3",
            "FY2025-Q4",
            "FY2026-Q1",
            "FY2026-Q2",
        ),
    ),
}


def get_company(ticker: str | None = None, *, scope: str | None = None) -> CompanyProfile:
    key = (ticker or DEFAULT_TICKER).strip().upper()
    if key not in COMPANIES:
        known = ", ".join(sorted(COMPANIES))
        raise KeyError(f"Unknown ticker {key!r}. Known: {known}")
    profile = COMPANIES[key]
    if scope == "five_year":
        if key != "AMZN":
            raise ValueError(f"scope 'five_year' is only defined for AMZN (got {key}).")
        return replace(
            profile,
            prior_quarters=AMZN_FIVE_YEAR_PRIOR_QUARTERS,
            output_quarters=AMZN_FIVE_YEAR_OUTPUT_QUARTERS,
        )
    if scope:
        raise ValueError(f"Unknown company scope {scope!r}.")
    return profile


def lookup_ids_from_snowflake(cur, ticker: str) -> dict[str, str | int]:
    """Resolve ESTPERMID / ISIN / BARRA_ID from IRIS_UNIV when available."""
    ticker = ticker.strip().upper()
    cur.execute("show databases")
    dbs = [r[1] for r in cur.fetchall()]
    iris_db = next((d for d in dbs if d.upper().startswith("IRIS")), None)
    if not iris_db:
        return {}

    cur.execute(
        f"""
        select TICKER, ESTPERMID, ISIN, BARRA_ID
        from "{iris_db}".PUBLIC.IRIS_UNIV
        where upper(TICKER) = %s
          and ESTPERMID is not null
        limit 1
        """,
        (ticker,),
    )
    row = cur.fetchone()
    if not row:
        return {}
    cols = [d[0].lower() for d in cur.description]
    data = dict(zip(cols, row))
    return {
        "estpermid": int(data["estpermid"]),
        "isin": str(data["isin"] or ""),
        "barra_id": str(data["barra_id"] or ""),
    }


def lookup_ids_from_lseg(cur, profile: CompanyProfile) -> dict[str, str | int]:
    """Resolve ESTPERMID / BARRA_ID from ISIN or IBESTICKER via LSEG/MSCI shares."""
    cur.execute("show databases")
    dbs = [r[1] for r in cur.fetchall()]
    lseg = next((d for d in dbs if d.startswith("LSEG_") and "A822" in d), None)
    msci = next((d for d in dbs if d.startswith("MSCI_")), None)
    if not lseg:
        return {}

    ticker = profile.ticker.strip().upper()
    out: dict[str, str | int] = {}
    if profile.isin:
        out["isin"] = profile.isin
        cur.execute(
            f'SELECT INSTRPERMID FROM "{lseg}".DBO.PERMISINDATA WHERE ISIN = %s LIMIT 1',
            (profile.isin,),
        )
        row = cur.fetchone()
        if row:
            instr = row[0]
            # Prefer the instrument's primary IBES mapping. Do NOT require
            # IBESTICKER == exchange ticker — STRW's IBES ticker is 04Y9.
            cur.execute(
                f'''SELECT ESTPERMID, IBESTICKER FROM "{lseg}".DBO.VW_IBES2MAPPING
                    WHERE INSTRPERMID = %s
                    ORDER BY CASE
                        WHEN SOURCE_ = 'INSTRPRIMARYQUOTE' THEN 0
                        WHEN UPPER(IBESTICKER) = %s THEN 1
                        ELSE 2
                    END
                    LIMIT 1''',
                (instr, ticker),
            )
            map_row = cur.fetchone()
            if map_row:
                out["estpermid"] = int(map_row[0])
                out["ibesticker"] = str(map_row[1] or "")

    # Ticker fallback only when ISIN is unknown. IBESTICKER can be recycled
    # (STRW historically pointed at a 1990s entity) — prefer ISIN path.
    if "estpermid" not in out:
        cur.execute(
            f'''SELECT ESTPERMID, IBESTICKER FROM "{lseg}".DBO.VW_IBES2MAPPING
                WHERE UPPER(IBESTICKER) = %s
                ORDER BY CASE WHEN SOURCE_ = 'INSTRPRIMARYQUOTE' THEN 0 ELSE 1 END
                LIMIT 1''',
            (ticker,),
        )
        map_row = cur.fetchone()
        if map_row:
            out["estpermid"] = int(map_row[0])
            out["ibesticker"] = str(map_row[1] or "")

    if msci and profile.isin:
        # Prefer US-market Barra IDs (US… / USA…). Do not require the "USA"
        # prefix — e.g. STRW is USBOFP1, while CSCO is USACX21.
        cur.execute(
            f'''SELECT BARRA_ID, COUNT(*) AS n
                FROM "{msci}".ANALYTICS.ASSET_UNIVERSE_TS
                WHERE ISIN = %s
                  AND BARRA_ID LIKE 'US%%'
                  AND BARRA_ID NOT LIKE 'ISR%%'
                GROUP BY 1 ORDER BY n DESC LIMIT 1''',
            (profile.isin,),
        )
        barra_row = cur.fetchone()
        if barra_row:
            out["barra_id"] = str(barra_row[0])
    return out


def resolve_company_ids(cur, profile: CompanyProfile) -> CompanyProfile:
    """Fill or validate IDs from Snowflake mapping tables when possible."""
    looked = lookup_ids_from_snowflake(cur, profile.ticker)
    if not looked:
        looked = lookup_ids_from_lseg(cur, profile)
    if not looked:
        return profile
    return CompanyProfile(
        ticker=profile.ticker,
        company_name=profile.company_name,
        estpermid=int(looked.get("estpermid") or profile.estpermid or 0) or profile.estpermid,
        isin=str(looked.get("isin") or profile.isin or ""),
        barra_id=str(looked.get("barra_id") or profile.barra_id or ""),
        output_quarters=profile.output_quarters,
        prior_quarters=profile.prior_quarters,
        candidate_measures=profile.candidate_measures,
    )
