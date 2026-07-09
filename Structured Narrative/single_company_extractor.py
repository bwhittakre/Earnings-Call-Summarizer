#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-Company Narrative-Quant Extractor
========================================

Builds the point-in-time (PIT) quantitative spine that the LLM narrative
features attach to.

Read-only. Output: output/{TICKER}_narrative_quant.parquet (+ .csv).

    python "Structured Narrative/single_company_extractor.py" --ticker AMZN
    python "Structured Narrative/single_company_extractor.py" --ticker MSFT
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd
from dotenv import load_dotenv
import snowflake.connector as sc

from company_config import get_company, resolve_company_ids
from excel_export import write_excel
from fiscal_period_util import company_fiscal_period
from output_paths import company_artifact

RETURN_MODEL = "EFMUSALTS"
MIN_CONSENSUS_QUARTERS = 8
START_DATE = dt.date(2015, 1, 1)
MODEL_DELAY_DAYS = 7
ALPHA_WINDOWS = [(0, 60), (60, 90), (0, 90)]

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "output")


def connect():
    load_dotenv(os.path.join(HERE, ".env"))
    return sc.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PAT_TOKEN"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        role=os.getenv("SNOWFLAKE_ROLE"),
    )


def resolve_dbs(cur):
    cur.execute("show databases")
    dbs = [r[1] for r in cur.fetchall()]
    lseg = next((d for d in dbs if d.startswith("LSEG_") and "A822" in d), None)
    msci = next((d for d in dbs if d.startswith("MSCI_")), None)
    if not lseg or not msci:
        sys.exit(f"Could not resolve share DBs (LSEG={lseg}, MSCI={msci}).")
    return lseg, msci


def q(cur, sql):
    cur.execute(sql)
    cols = [d[0].lower() for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def pull_consensus(cur, lseg, company, measures):
    inlist = ",".join(str(m) for m in measures)
    df = q(cur, f"""
        select MEASURE, MEASURE_CODE, MEASURE_DESC, PERTYPE, PERENDDATE,
               EFFECTIVEDATE, EXPIREDATE, DEFMEANEST, DEFMEDIANEST,
               DEFHIGHEST, DEFLOWEST, NORMMEANEST, NUMINCESTS, UNITTYPE, DEFSCALE
        from "{lseg}".DBO.VW_IBES2SUMPER
        where ESTPERMID = {company.estpermid} and MEASURE in ({inlist}) and PERTYPE in (3,4)
    """)
    for c in ("perenddate", "effectivedate", "expiredate"):
        df[c] = pd.to_datetime(df[c])
    return df


def pull_actuals(cur, lseg, company, measures):
    inlist = ",".join(str(m) for m in measures)
    df = q(cur, f"""
        select MEASURE, PERTYPE, PERENDDATE, ANNOUNCEDATE, EFFECTIVEDATE,
               DEFACTVALUE, NORMACTVALUE, UNITTYPE, DEFSCALE
        from "{lseg}".DBO.TREACTRPT
        where ESTPERMID = {company.estpermid} and MEASURE in ({inlist}) and PERTYPE in (3,4)
    """)
    for c in ("perenddate", "announcedate", "effectivedate"):
        df[c] = pd.to_datetime(df[c])
    return df


def pull_returns(cur, msci, company):
    df = q(cur, f"""
        select DATE_OF_DATA, SPECIFIC_RETURN
        from "{msci}".ANALYTICS.ASSET_SPECIFIC_RETURN_TS
        where BARRA_ID = '{company.barra_id}' and MODEL = '{RETURN_MODEL}' and HORIZON = 'D'
    """)
    df["date_of_data"] = pd.to_datetime(df["date_of_data"])
    df["specific_return"] = pd.to_numeric(df["specific_return"], errors="coerce")
    return df.sort_values("date_of_data").reset_index(drop=True)


def fiscal_year_label(ticker: str, perend: pd.Timestamp) -> str:
    return company_fiscal_period(ticker, perend).split("-")[0]


def model_date_from(earnings_date: pd.Timestamp) -> pd.Timestamp:
    d = earnings_date + pd.Timedelta(days=MODEL_DELAY_DAYS)
    while d.weekday() >= 5:
        d += pd.Timedelta(days=1)
    return d


def pit_consensus(cons, measure, pertype, perend, asof, inclusive):
    m = ((cons["measure"] == measure) & (cons["pertype"] == pertype) &
         (cons["perenddate"] == perend))
    if not m.any():
        return None
    sub = cons[m]
    sub = sub[sub["effectivedate"] < asof] if not inclusive \
        else sub[sub["effectivedate"] <= asof]
    if sub.empty:
        return None
    return sub.loc[sub["effectivedate"].idxmax()]


def compound_specific_return(ret, start_excl, end_incl):
    if ret["date_of_data"].max() < end_incl:
        return None, False
    w = ret[(ret["date_of_data"] > start_excl) & (ret["date_of_data"] <= end_incl)]
    if w.empty:
        return None, False
    return float((1.0 + w["specific_return"] / 100.0).prod() - 1.0), True


def _num(x):
    return None if x is None or pd.isna(x) else float(x)


def build(company):
    conn = connect()
    cur = conn.cursor()
    company = resolve_company_ids(cur, company)
    if not company.estpermid or not company.barra_id:
        sys.exit(
            f"Missing ESTPERMID/BARRA_ID for {company.ticker}. "
            "Update company_config.py or ensure IRIS_UNIV access."
        )

    lseg, msci = resolve_dbs(cur)
    print(f"Ticker     : {company.ticker}")
    print(f"ESTPERMID  : {company.estpermid}")
    print(f"BARRA_ID   : {company.barra_id}")
    print(f"LSEG share : {lseg}")
    print(f"MSCI share : {msci}")
    print(f"Return model: {RETURN_MODEL}\n")

    core = {k: v for k, v in company.all_measures().items() if k not in company.candidate_measures}
    candidate = dict(company.candidate_measures)
    all_measures = list(company.all_measures())

    cons = pull_consensus(cur, lseg, company, all_measures)
    act = pull_actuals(cur, lseg, company, all_measures)
    ret = pull_returns(cur, msci, company)
    cur.close()
    conn.close()

    desc_map = (cons.dropna(subset=["measure_desc"])
                    .groupby("measure")["measure_desc"].first().to_dict())

    qcons = cons[cons["pertype"] == 3]
    cov = (qcons.groupby("measure")["perenddate"].nunique()
                .reindex(all_measures).fillna(0).astype(int))
    kept = []
    print("Consensus-coverage gate (quarterly PERENDDATEs):")
    print(f"{'measure':>7} {'label':<22} {'q_periods':>9}  status")
    for mcode in all_measures:
        label = company.all_measures().get(mcode, str(mcode))
        n = int(cov.get(mcode, 0))
        is_core = mcode not in candidate
        keep = is_core or n >= MIN_CONSENSUS_QUARTERS
        if keep:
            kept.append(mcode)
        tag = "CORE-keep" if is_core else ("keep" if keep else "DROP (thin)")
        print(f"{mcode:>7} {label:<22} {n:>9}  {tag}")
    print(f"\nKept {len(kept)} measures.\n")

    qact = act[act["pertype"] == 3].dropna(subset=["announcedate"])
    events = (qact.groupby("perenddate")["announcedate"].min()
                  .reset_index().sort_values("announcedate").reset_index(drop=True))
    events = events[events["announcedate"].dt.date >= START_DATE].reset_index(drop=True)
    events["next_earnings_date"] = events["announcedate"].shift(-1)

    annual_perends = sorted(cons.loc[cons["pertype"] == 4, "perenddate"].unique())
    quarter_perends = sorted(cons.loc[cons["pertype"] == 3, "perenddate"].unique())

    rows = []
    ticker = company.ticker
    for _, ev in events.iterrows():
        q_perend = ev["perenddate"]
        edate = ev["announcedate"]
        ndate = ev["next_earnings_date"]
        mdate = model_date_from(edate.normalize())

        alpha = {}
        for a, b in ALPHA_WINDOWS:
            val, ok = compound_specific_return(
                ret, mdate + pd.Timedelta(days=a), mdate + pd.Timedelta(days=b))
            alpha[f"alpha_spec_{a}_{b}"] = val
            alpha[f"alpha_spec_{a}_{b}_complete"] = ok
        overlaps_next = bool(ndate is not None and pd.notna(ndate)
                             and ndate <= mdate + pd.Timedelta(days=90))

        nxt_q = next((p for p in quarter_perends if p > q_perend), None)
        fwd_fy = [p for p in annual_perends if p > edate][:2]
        role_targets = {
            "reported_q": (3, q_perend),
            "next_q": (3, nxt_q),
            "fy1": (4, fwd_fy[0] if len(fwd_fy) > 0 else None),
            "fy2": (4, fwd_fy[1] if len(fwd_fy) > 1 else None),
        }

        event_fiscal_period = company_fiscal_period(ticker, q_perend)

        for mcode in kept:
            label = company.all_measures().get(mcode, str(mcode))
            for role, (ptype, tgt) in role_targets.items():
                if tgt is None:
                    continue

                pre = pit_consensus(cons, mcode, ptype, tgt, edate, inclusive=False)
                post7 = pit_consensus(cons, mcode, ptype, tgt,
                                      edate + pd.Timedelta(days=MODEL_DELAY_DAYS),
                                      inclusive=True)

                actual_val = actual_eff = None
                if role == "reported_q":
                    am = ((act["measure"] == mcode) & (act["pertype"] == 3) &
                          (act["perenddate"] == q_perend))
                    if am.any():
                        arow = act[am].sort_values("effectivedate").iloc[-1]
                        actual_val = _num(arow["defactvalue"])
                        actual_eff = arow["effectivedate"]

                pre_mean = _num(pre["defmeanest"]) if pre is not None else None
                post_mean = _num(post7["defmeanest"]) if post7 is not None else None

                surprise = surprise_pct = None
                if actual_val is not None and pre_mean is not None:
                    surprise = actual_val - pre_mean
                    if pre_mean != 0:
                        surprise_pct = surprise / abs(pre_mean)

                revision = revision_pct = None
                if pre_mean is not None and post_mean is not None:
                    revision = post_mean - pre_mean
                    if pre_mean != 0:
                        revision_pct = revision / abs(pre_mean)

                if ptype == 3:
                    tgt_label = company_fiscal_period(ticker, tgt)
                else:
                    tgt_label = fiscal_year_label(ticker, tgt)

                rows.append({
                    "ticker": ticker,
                    "estpermid": company.estpermid,
                    "isin": company.isin,
                    "barra_id": company.barra_id,
                    "fiscal_period": event_fiscal_period,
                    "fiscal_quarter_end": q_perend.date(),
                    "earnings_date": edate.normalize().date(),
                    "earnings_datetime": edate,
                    "model_date": mdate.date(),
                    "next_earnings_date": ndate.normalize().date() if pd.notna(ndate) else None,
                    "measure": mcode,
                    "measure_label": label,
                    "measure_desc": desc_map.get(mcode),
                    "period_role": role,
                    "target_pertype": ptype,
                    "target_period": tgt_label,
                    "target_period_end": tgt.date(),
                    "actual_value": actual_val,
                    "actual_effectivedate": actual_eff if actual_eff is not None else None,
                    "consensus_pre_mean": pre_mean,
                    "consensus_pre_median": _num(pre["defmedianest"]) if pre is not None else None,
                    "consensus_pre_high": _num(pre["defhighest"]) if pre is not None else None,
                    "consensus_pre_low": _num(pre["deflowest"]) if pre is not None else None,
                    "consensus_pre_numests": int(pre["numincests"]) if pre is not None and pd.notna(pre["numincests"]) else None,
                    "consensus_pre_effectivedate": pre["effectivedate"] if pre is not None else None,
                    "consensus_post7_mean": post_mean,
                    "consensus_post7_numests": int(post7["numincests"]) if post7 is not None and pd.notna(post7["numincests"]) else None,
                    "consensus_post7_effectivedate": post7["effectivedate"] if post7 is not None else None,
                    "earnings_surprise": surprise,
                    "earnings_surprise_pct": surprise_pct,
                    "fwd_estimate_revision": revision,
                    "fwd_estimate_revision_pct": revision_pct,
                    "unittype": pre["unittype"] if pre is not None else None,
                    "defscale": _num(pre["defscale"]) if pre is not None else None,
                    **alpha,
                    "window_overlaps_next_earnings": overlaps_next,
                    "src_consensus_view": "VW_IBES2SUMPER",
                    "src_actual_view": "TREACTRPT",
                    "src_return_view": "ASSET_SPECIFIC_RETURN_TS",
                    "return_model": RETURN_MODEL,
                })

    return pd.DataFrame(rows)


def validate(df: pd.DataFrame):
    print("=" * 70)
    print("VALIDATION")
    print("-" * 70)
    if df.empty:
        sys.exit("No rows produced - aborting.")

    errs = []
    edt = pd.to_datetime(df["earnings_datetime"])

    m = df["consensus_pre_effectivedate"].notna()
    if (pd.to_datetime(df.loc[m, "consensus_pre_effectivedate"]) >= edt[m]).any():
        errs.append("pre-consensus effectivedate not strictly before earnings announcement")

    m = df["consensus_post7_effectivedate"].notna()
    if (pd.to_datetime(df.loc[m, "consensus_post7_effectivedate"]) >
            edt[m] + pd.Timedelta(days=7)).any():
        errs.append("post7-consensus effectivedate later than earnings + 7d")

    if (pd.to_datetime(df["model_date"]) <= pd.to_datetime(df["earnings_date"])).any():
        errs.append("model_date not strictly after earnings_date")

    m = (df["period_role"] == "reported_q") & \
        df["consensus_pre_effectivedate"].notna() & df["actual_effectivedate"].notna()
    if (pd.to_datetime(df.loc[m, "consensus_pre_effectivedate"]) >
            pd.to_datetime(df.loc[m, "actual_effectivedate"])).any():
        errs.append("pre-consensus dated after the actual it is compared to")

    for a, b in ALPHA_WINDOWS:
        col, flag = f"alpha_spec_{a}_{b}", f"alpha_spec_{a}_{b}_complete"
        if (df[~df[flag]][col].notna()).any():
            errs.append(f"{col} populated on an unclosed window")

    if errs:
        for e in errs:
            print("  FAIL:", e)
        sys.exit("PIT/evidence validation failed - not writing output.")
    print("  PASS: all PIT & evidence assertions hold.\n")

    print(f"Events            : {df['fiscal_period'].nunique()} quarters "
          f"({df['earnings_date'].min()} -> {df['earnings_date'].max()})")
    print(f"Rows              : {len(df)}  (event x measure x role)")
    print(f"Measures kept     : {sorted(df['measure'].unique().tolist())}\n")

    sample = sorted(df["fiscal_period"].unique())[-8:]
    print(f"Recent fiscal_period labels: {', '.join(sample)}\n")


def write_output(df: pd.DataFrame, ticker: str):
    parquet_path = company_artifact(ticker, "parquet", "narrative_quant", "parquet", mkdir=True)
    try:
        df.to_parquet(parquet_path, index=False)
        print(f"Wrote {parquet_path}  ({len(df)} rows)")
    except Exception as e:
        print(f"Parquet write skipped ({e}).")
    xlsx_path = company_artifact(ticker, "workbooks", "narrative_quant", "xlsx", mkdir=True)
    write_excel(df, str(xlsx_path))
    print(f"Wrote {xlsx_path}")


def main():
    ap = argparse.ArgumentParser(description="Build PIT quant spine for one ticker.")
    ap.add_argument("--ticker", default="AMZN", help="Ticker symbol (AMZN, MSFT, NVDA).")
    args = ap.parse_args()
    company = get_company(args.ticker)
    df = build(company)
    validate(df)
    write_output(df, company.ticker)
    return df


if __name__ == "__main__":
    main()
