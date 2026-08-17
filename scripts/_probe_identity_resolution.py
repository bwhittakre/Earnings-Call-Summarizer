"""Read-only probe for lookup_ids_from_lseg against the live LSEG/MSCI shares.

Verifies the merged ISIN-first resolution. For each ticker it resolves twice:
once as configured, and once with the ISIN cleared, because the ticker-to-ISIN
discovery hop only runs when no ISIN is on the profile.

Issues SELECTs and "show databases" only; writes nothing.
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SN = os.path.join(REPO, "Structured Narrative")
if SN not in sys.path:
    sys.path.insert(0, SN)

import snowflake.connector as sc  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from company_config import COMPANIES, lookup_ids_from_lseg  # noqa: E402

TICKERS = ("STRW", "SPCX", "CSCO")


def connect():
    load_dotenv(os.path.join(SN, ".env"))
    return sc.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PAT_TOKEN"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        role=os.getenv("SNOWFLAKE_ROLE"),
    )


def _fmt(value) -> str:
    return "-" if value in (None, "") else str(value)


def _compare(label: str, configured, looked: dict) -> None:
    got_est = looked.get("estpermid")
    got_isin = looked.get("isin")
    got_barra = looked.get("barra_id")
    verdict = "MATCH"
    if got_est and configured.estpermid and int(got_est) != int(configured.estpermid):
        verdict = "MISMATCH"
    elif not got_est:
        verdict = "UNRESOLVED"
    print(
        f"  {label:<18} estpermid={_fmt(got_est):<14}"
        f" isin={_fmt(got_isin):<14} barra={_fmt(got_barra):<9}"
        f" ibes={_fmt(looked.get('ibesticker')):<6} -> {verdict}"
    )


def main() -> int:
    exit_code = 0
    with connect() as conn:
        cur = conn.cursor()
        for ticker in TICKERS:
            profile = COMPANIES.get(ticker)
            if profile is None:
                print(f"{ticker}: not in COMPANIES, skipping")
                continue
            print(
                f"\n{ticker} configured: estpermid={_fmt(profile.estpermid)}"
                f" isin={_fmt(profile.isin)} barra={_fmt(profile.barra_id)}"
            )
            with_isin = dict(lookup_ids_from_lseg(cur, profile) or {})
            _compare("as configured", profile, with_isin)

            stripped = replace(profile, isin=None)
            without_isin = dict(lookup_ids_from_lseg(cur, stripped) or {})
            _compare("isin cleared", profile, without_isin)

            if with_isin.get("estpermid") and profile.estpermid:
                if int(with_isin["estpermid"]) != int(profile.estpermid):
                    exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
