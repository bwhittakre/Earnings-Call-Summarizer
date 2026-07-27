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
AMZN_EXTENDED_PRIOR_QUARTERS = ("FY2016-Q2",)
AMZN_EXTENDED_NEW_OUTPUT_QUARTERS = (
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
AAPL_PRIOR_QUARTERS = ("FY2016-Q3",)
AAPL_NEW_OUTPUT_QUARTERS = (
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

MSFT_PRIOR_QUARTERS = ("FY2016-Q4",)
MSFT_NEW_OUTPUT_QUARTERS = (
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
NVDA_PRIOR_QUARTERS = ("FY2017-Q2",)
NVDA_NEW_OUTPUT_QUARTERS = (
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
)

ORCL_PRIOR_QUARTERS = ("FY2016-Q1",)
ORCL_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4",
)

CRM_PRIOR_QUARTERS = ("FY2016-Q3",)
CRM_OUTPUT_QUARTERS = (
    "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3", "FY2017-Q4", "FY2018-Q1",
    "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1", "FY2019-Q2", "FY2019-Q3",
    "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3", "FY2020-Q4", "FY2021-Q1",
    "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1", "FY2022-Q2", "FY2022-Q3",
    "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3", "FY2023-Q4", "FY2024-Q1",
    "FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1",
)

# IBM's earliest available transcript moved from FY2017-Q3 to FY2016-Q2 once
# the fetcher filled in more history, so FY2017-Q3 -- previously the prior-
# only baseline -- is now an output quarter itself. run_universe_batch.py
# needs --extra-output-quarters FY2017-Q3 the first time this runs so
# finalize_and_write() promotes it (flips prior_only/output_scope, backfills
# CSV rows) instead of leaving it stranded with the old flag.
IBM_PRIOR_QUARTERS = ("FY2016-Q2",)
IBM_OUTPUT_QUARTERS = (
    "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3", "FY2017-Q4",
    "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1", "FY2019-Q2",
    "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3", "FY2020-Q4",
    "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1", "FY2022-Q2",
    "FY2022-Q3", "FY2022-Q4", "FY2023-Q3",
)

ADBE_PRIOR_QUARTERS = ("FY2016-Q1",)
ADBE_OUTPUT_QUARTERS = (
    "FY2016-Q2", "FY2016-Q3", "FY2016-Q4", "FY2017-Q1", "FY2017-Q2", "FY2017-Q3",
    "FY2017-Q4", "FY2018-Q1", "FY2018-Q2", "FY2018-Q3", "FY2018-Q4", "FY2019-Q1",
    "FY2019-Q2", "FY2019-Q3", "FY2019-Q4", "FY2020-Q1", "FY2020-Q2", "FY2020-Q3",
    "FY2020-Q4", "FY2021-Q1", "FY2021-Q2", "FY2021-Q3", "FY2021-Q4", "FY2022-Q1",
    "FY2022-Q2", "FY2022-Q3", "FY2022-Q4", "FY2023-Q1", "FY2023-Q2", "FY2023-Q3",
    "FY2023-Q4", "FY2024-Q1", "FY2024-Q2", "FY2024-Q3", "FY2024-Q4",
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
    """Resolve ESTPERMID / BARRA_ID from ISIN via raw LSEG/MSCI shares."""
    if not profile.isin:
        return {}
    cur.execute("show databases")
    dbs = [r[1] for r in cur.fetchall()]
    lseg = next((d for d in dbs if d.startswith("LSEG_") and "A822" in d), None)
    msci = next((d for d in dbs if d.startswith("MSCI_")), None)
    if not lseg:
        return {}

    out: dict[str, str | int] = {"isin": profile.isin}
    cur.execute(
        f'SELECT INSTRPERMID FROM "{lseg}".DBO.PERMISINDATA WHERE ISIN = %s LIMIT 1',
        (profile.isin,),
    )
    row = cur.fetchone()
    if row:
        instr = row[0]
        cur.execute(
            f'''SELECT ESTPERMID, IBESTICKER FROM "{lseg}".DBO.VW_IBES2MAPPING
                WHERE INSTRPERMID = %s AND UPPER(IBESTICKER) = %s
                ORDER BY CASE WHEN SOURCE_ = 'INSTRPRIMARYQUOTE' THEN 0 ELSE 1 END
                LIMIT 1''',
            (instr, profile.ticker),
        )
        map_row = cur.fetchone()
        if map_row:
            out["estpermid"] = int(map_row[0])

    if msci:
        cur.execute(
            f'''SELECT BARRA_ID, COUNT(*) AS n
                FROM "{msci}".ANALYTICS.ASSET_UNIVERSE_TS
                WHERE ISIN = %s AND BARRA_ID LIKE 'USA%%'
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
