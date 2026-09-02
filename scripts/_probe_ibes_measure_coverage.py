"""One-off Snowflake coverage probe for dimension-metric strengthening.

Not part of the runtime path. Run:
  python scripts/_probe_ibes_measure_coverage.py

If Snowflake is blocked (network policy), lock membership from the catalog
prior in OFFLINE_LOCK below rather than inventing IBES codes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SN = Path(__file__).resolve().parents[1] / "Structured Narrative"
sys.path.insert(0, str(SN))

from company_config import COMPANIES, OVERLAY_DIR, load_company_overlay  # noqa: E402
from single_company_extractor import connect, q, resolve_dbs  # noqa: E402

CANDIDATES = {
    20: "Sales",
    6: "EBIT",
    8: "EBITDA",
    27: "Gross Margin",
    9: "EPS",
    237: "Free Cash Flow",
    22: "Capex",
    213: "Stock-Based Comp",
    418: "Advertising Revenue",
    431: "GMV",
    373: "Deferred Revenue",
    445: "LT Deferred Revenue",
    368: "Service Revenue",
    333: "Subscribers",
    332: "Net Subscriber Adds",
    185: "R&D Exp",
    219: "SG&A",
    229: "CFO",
    240: "Inventory",
    14: "Net Debt",
    15: "Net Income",
    19: "ROE",
    109: "Interest Expense",
    141: "FFO",
    142: "NOI",
    153: "Shareholders Equity",
    157: "Total Assets",
    173: "NIM",
}

KEYWORDS = (
    "book",
    "backlog",
    "order",
    "pretax",
    "pre-tax",
    "diluted",
    "dividend",
    "buyback",
    "repurchase",
    "operating margin",
    "op. margin",
    "units",
    "shipment",
)

MIN_QUARTERS = 8
MIN_BOOK_FRAC = 0.70
SKIP_PREFIXES = ("ZZZ", "ACME")


def book_profiles() -> list:
    by_ticker: dict[str, object] = {}
    for ticker, profile in COMPANIES.items():
        if ticker.startswith(SKIP_PREFIXES):
            continue
        by_ticker[ticker] = profile
    if OVERLAY_DIR.is_dir():
        for path in OVERLAY_DIR.glob("*.json"):
            overlay = load_company_overlay(path.stem)
            if overlay is None or overlay.ticker.startswith(SKIP_PREFIXES):
                continue
            by_ticker.setdefault(overlay.ticker, overlay)
    return [p for p in by_ticker.values() if getattr(p, "estpermid", None)]


def main() -> int:
    profiles = book_profiles()
    permids = {int(p.estpermid): p.ticker for p in profiles}
    print(f"Book names with ESTPERMID: {len(permids)}")
    print(" ".join(sorted(permids.values())))

    conn = connect()
    cur = conn.cursor()
    lseg, _msci = resolve_dbs(cur)
    inlist = ",".join(str(m) for m in CANDIDATES)
    ids = ",".join(str(i) for i in permids)

    cov = q(
        cur,
        f"""
        select ESTPERMID, MEASURE, max(MEASURE_DESC) as measure_desc,
               count(distinct PERENDDATE) as q_periods
        from "{lseg}".DBO.VW_IBES2SUMPER
        where ESTPERMID in ({ids})
          and MEASURE in ({inlist})
          and PERTYPE = 3
          and PERENDDATE >= '2010-01-01'
        group by ESTPERMID, MEASURE
        """,
    )
    desc = q(
        cur,
        f"""
        select MEASURE, max(MEASURE_DESC) as measure_desc,
               count(distinct ESTPERMID) as n_names,
               count(distinct PERENDDATE) as q_periods
        from "{lseg}".DBO.VW_IBES2SUMPER
        where ESTPERMID in ({ids})
          and PERTYPE = 3
          and PERENDDATE >= '2010-01-01'
          and (
            lower(coalesce(MEASURE_DESC,'')) like '%book%'
            or lower(coalesce(MEASURE_DESC,'')) like '%backlog%'
            or lower(coalesce(MEASURE_DESC,'')) like '%order%'
            or lower(coalesce(MEASURE_DESC,'')) like '%pretax%'
            or lower(coalesce(MEASURE_DESC,'')) like '%pre-tax%'
            or lower(coalesce(MEASURE_DESC,'')) like '%diluted%'
            or lower(coalesce(MEASURE_DESC,'')) like '%dividend%'
            or lower(coalesce(MEASURE_DESC,'')) like '%buyback%'
            or lower(coalesce(MEASURE_DESC,'')) like '%repurchase%'
            or lower(coalesce(MEASURE_DESC,'')) like '%operating margin%'
            or lower(coalesce(MEASURE_DESC,'')) like '%units%'
            or lower(coalesce(MEASURE_DESC,'')) like '%shipment%'
          )
        group by MEASURE
        order by n_names desc, q_periods desc
        """,
    )
    cur.close()
    conn.close()

    cov["ticker"] = cov["estpermid"].map(permids)
    # Denominator: names with ≥8 quarterly Sales prints (real IBES history).
    sales = cov[(cov["measure"] == 20) & (cov["q_periods"] >= MIN_QUARTERS)]
    eligible = sorted(sales["ticker"].dropna().unique().tolist())
    n_eligible = len(eligible)
    need = max(1, int(round(MIN_BOOK_FRAC * n_eligible))) if n_eligible else 0
    print(f"\nEligible names (≥{MIN_QUARTERS} Sales quarters): {n_eligible}  70% bar={need}")
    print(" ".join(eligible))

    print("\n=== Candidate coverage (eligible book) ===")
    print(f"{'code':>6} {'label':<22} {'n_ge8':>6} {'pct':>6} {'med_q':>6}  decision")
    keep: list[int] = []
    for code, label in CANDIDATES.items():
        sub = cov[(cov["measure"] == code) & (cov["ticker"].isin(eligible))]
        n_ge8 = int((sub["q_periods"] >= MIN_QUARTERS).sum())
        med = float(sub["q_periods"].median()) if not sub.empty else 0.0
        pct = (n_ge8 / n_eligible) if n_eligible else 0.0
        decision = "KEEP-CORE" if n_ge8 >= need else ("overlay" if n_ge8 else "DROP")
        if n_ge8 >= need:
            keep.append(int(code))
        print(f"{code:>6} {label:<22} {n_ge8:>6} {pct:6.0%} {med:6.0f}  {decision}")

    print("\n=== Keyword MEASURE_DESC hits (not in candidate list) ===")
    known = set(CANDIDATES)
    if desc.empty:
        print("(none)")
    else:
        for _, row in desc.iterrows():
            code = int(row["measure"])
            if code in known:
                continue
            print(
                f"{code:>6} {str(row['measure_desc'])[:40]:<40} "
                f"n_names={int(row['n_names'])} q={int(row['q_periods'])}"
            )

    print("\nKEEP-CORE codes:", keep)
    print(
        "\nIf Snowflake is blocked, lock from Script.py SAM + current CORE "
        "(see company_config.CORE_MEASURES / narrative_zscore.DIMENSIONS): "
        "KEEP 20,6,8,27,9,15,19,237,22,229,14,185,219; "
        "overlay 213,418,431,373,445,368,333,332; "
        "DROP 240 (demand WC), 141, 142, 173, 109, 153, 157, 28 (dup of 17), "
        "520 (68% buybacks), 381 bookings."
    )
    print(
        "Live lock: CORE adds 373 Deferred, 213 SBC, 17 Pretax, 4 DPS; "
        "earnings_power 9/15/17/19; cap alloc 237/22/229/14/213/4."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
