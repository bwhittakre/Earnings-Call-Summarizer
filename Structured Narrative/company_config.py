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

FY2024_PRIOR_QUARTERS = (
    "FY2024-Q4",
)

# AMZN 5-year historical run: transcripts in Structured Narrative/AMZN/
# FY2019-Q2 is prior-only (delta baseline for FY2019-Q3); not in published outputs.
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

PILOT_TICKERS = ("AMZN", "MSFT", "NVDA")
DEFAULT_TICKER = "AMZN"

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
    output_quarters: tuple[str, ...] = FY2025_OUTPUT_QUARTERS
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
        candidate_measures=dict(AMZN_CANDIDATE_MEASURES),
    ),
    "MSFT": CompanyProfile(
        ticker="MSFT",
        company_name="Microsoft Corporation",
        estpermid=30064848647,
        isin="US5949181045",
        barra_id="USAJ471",
    ),
    "NVDA": CompanyProfile(
        ticker="NVDA",
        company_name="NVIDIA Corporation",
        estpermid=30064850531,
        isin="US67066G1040",
        barra_id="USA2HB1",
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
