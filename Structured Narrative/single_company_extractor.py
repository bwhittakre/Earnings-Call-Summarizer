#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AMZN Single-Company Narrative-Quant Extractor
==============================================

Builds the point-in-time (PIT) quantitative spine that the LLM narrative
features attach to. For each Amazon earnings event it captures, per financial
measure:

  * the reported-quarter ACTUAL vs the PRE-announcement consensus  -> earnings_surprise
  * the PRE vs POST-7-day consensus for forward periods (FY1/FY2/next-Q)
        -> fwd_estimate_revision  (the "guidance / management confidence" signal)
  * forward MSCI specific returns (alpha) over 0-60 / 60-90 / 0-90 day windows
    measured from the model date (earnings date + 7 business-adjusted days)

Everything is PIT-correct: consensus is only ever read as it stood *before* the
relevant date, actuals are anchored on their disclosure (ANNOUNCEDATE), and a
forward-return label is only written once its window has fully closed.

Every quantitative value carries provenance (source view, measure code, the
EFFECTIVEDATE it became known, and the analyst count behind each consensus
point) so both halves of the research dataset are evidence-backed.

Read-only. Output: output/AMZN_narrative_quant.parquet (+ .csv for eyeballing).
"""

import os
import sys
import datetime as dt

import pandas as pd
from dotenv import load_dotenv
import snowflake.connector as sc

from excel_export import write_excel

# ── Company constants (resolved from the raw shares in discovery) ─────────────
TICKER    = "AMZN"
ESTPERMID = 30064828538          # LSEG IBES estimate PermID (IBESTICKER 'AMZN')
ISIN      = "US0231351067"
BARRA_ID  = "USAXO31"            # MSCI primary US listing (XNGS, estimation univ)

# MSCI factor model used for the specific-return (alpha) label.
RETURN_MODEL = "EFMUSALTS"       # long-term structural model; EFMUSATRD also avail.

# ── Measure universe ──────────────────────────────────────────────────────────
# Core narrative drivers: always kept regardless of coverage.
CORE_MEASURES = {
    20: "Sales", 6: "EBIT", 8: "EBITDA", 27: "Gross Margin",
    9: "EPS", 237: "Free Cash Flow", 22: "Capex",
}
# AMZN sector candidates: kept only if they clear the consensus-coverage gate.
CANDIDATE_MEASURES = {
    213: "Stock-Based Comp", 418: "Advertising Revenue", 431: "GMV",
    373: "Deferred Revenue", 445: "LT Deferred Revenue",
    368: "Service Revenue", 333: "Subscribers", 332: "Net Subscriber Adds",
}
MIN_CONSENSUS_QUARTERS = 8       # candidate coverage gate

# Only build events from this date forward (transcript-era default; lower freely).
START_DATE = dt.date(2015, 1, 1)

MODEL_DELAY_DAYS = 7             # earnings date -> model date (info-diffusion lag)
ALPHA_WINDOWS = [(0, 60), (60, 90), (0, 90)]  # calendar-day forward return windows

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
OUT_PARQUET = os.path.join(OUT_DIR, "AMZN_narrative_quant.parquet")
OUT_CSV     = os.path.join(OUT_DIR, "AMZN_narrative_quant.csv")


# ── Connection ────────────────────────────────────────────────────────────────
def connect():
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    return sc.connect(
        account   = os.getenv("SNOWFLAKE_ACCOUNT"),
        user      = os.getenv("SNOWFLAKE_USER"),
        password  = os.getenv("SNOWFLAKE_PAT_TOKEN"),
        warehouse = os.getenv("SNOWFLAKE_WAREHOUSE"),
        role      = os.getenv("SNOWFLAKE_ROLE"),
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


# ── Raw pulls ─────────────────────────────────────────────────────────────────
def pull_consensus(cur, lseg, measures):
    inlist = ",".join(str(m) for m in measures)
    df = q(cur, f"""
        select MEASURE, MEASURE_CODE, MEASURE_DESC, PERTYPE, PERENDDATE,
               EFFECTIVEDATE, EXPIREDATE, DEFMEANEST, DEFMEDIANEST,
               DEFHIGHEST, DEFLOWEST, NORMMEANEST, NUMINCESTS, UNITTYPE, DEFSCALE
        from "{lseg}".DBO.VW_IBES2SUMPER
        where ESTPERMID = {ESTPERMID} and MEASURE in ({inlist}) and PERTYPE in (3,4)
    """)
    for c in ("perenddate", "effectivedate", "expiredate"):
        df[c] = pd.to_datetime(df[c])
    return df


def pull_actuals(cur, lseg, measures):
    inlist = ",".join(str(m) for m in measures)
    df = q(cur, f"""
        select MEASURE, PERTYPE, PERENDDATE, ANNOUNCEDATE, EFFECTIVEDATE,
               DEFACTVALUE, NORMACTVALUE, UNITTYPE, DEFSCALE
        from "{lseg}".DBO.TREACTRPT
        where ESTPERMID = {ESTPERMID} and MEASURE in ({inlist}) and PERTYPE in (3,4)
    """)
    for c in ("perenddate", "announcedate", "effectivedate"):
        df[c] = pd.to_datetime(df[c])
    return df


def pull_returns(cur, msci):
    df = q(cur, f"""
        select DATE_OF_DATA, SPECIFIC_RETURN
        from "{msci}".ANALYTICS.ASSET_SPECIFIC_RETURN_TS
        where BARRA_ID = '{BARRA_ID}' and MODEL = '{RETURN_MODEL}' and HORIZON = 'D'
    """)
    df["date_of_data"] = pd.to_datetime(df["date_of_data"])
    df["specific_return"] = pd.to_numeric(df["specific_return"], errors="coerce")
    return df.sort_values("date_of_data").reset_index(drop=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def quarter_label(perend: pd.Timestamp) -> str:
    return f"FY{perend.year}-Q{(perend.month - 1) // 3 + 1}"


def annual_label(perend: pd.Timestamp) -> str:
    return f"FY{perend.year}"


def model_date_from(earnings_date: pd.Timestamp) -> pd.Timestamp:
    d = earnings_date + pd.Timedelta(days=MODEL_DELAY_DAYS)
    while d.weekday() >= 5:            # roll Sat/Sun forward to Monday
        d += pd.Timedelta(days=1)
    return d


def pit_consensus(cons: pd.DataFrame, measure, pertype, perend, asof, inclusive):
    """Latest consensus snapshot for (measure, pertype, perend) known as of `asof`.
    inclusive=False -> strictly before asof (the pre-announcement read).
    inclusive=True  -> on/before asof (the post-window read)."""
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


def compound_specific_return(ret: pd.DataFrame, start_excl, end_incl):
    """Compounded specific return (fraction) over (start_excl, end_incl].
    Returns (value, complete_flag). NULL/incomplete if window hasn't closed."""
    if ret["date_of_data"].max() < end_incl:
        return None, False
    w = ret[(ret["date_of_data"] > start_excl) & (ret["date_of_data"] <= end_incl)]
    if w.empty:
        return None, False
    return float((1.0 + w["specific_return"] / 100.0).prod() - 1.0), True


def _num(x):
    return None if x is None or pd.isna(x) else float(x)


# ── Build ─────────────────────────────────────────────────────────────────────
def main():
    conn = connect()
    cur = conn.cursor()
    lseg, msci = resolve_dbs(cur)
    print(f"LSEG share : {lseg}")
    print(f"MSCI share : {msci}")
    print(f"Return model: {RETURN_MODEL}\n")

    all_measures = list(CORE_MEASURES) + list(CANDIDATE_MEASURES)
    cons = pull_consensus(cur, lseg, all_measures)
    act  = pull_actuals(cur, lseg, all_measures)
    ret  = pull_returns(cur, msci)
    cur.close(); conn.close()

    # Authoritative descriptions straight from the view (no external dictionary).
    desc_map = (cons.dropna(subset=["measure_desc"])
                    .groupby("measure")["measure_desc"].first().to_dict())

    # ── Coverage gate ──────────────────────────────────────────────────────────
    qcons = cons[cons["pertype"] == 3]
    cov = (qcons.groupby("measure")["perenddate"].nunique()
                .reindex(all_measures).fillna(0).astype(int))
    kept, dropped = [], []
    print("Consensus-coverage gate (quarterly PERENDDATEs):")
    print(f"{'measure':>7} {'label':<22} {'q_periods':>9}  status")
    for mcode in all_measures:
        label = CORE_MEASURES.get(mcode) or CANDIDATE_MEASURES.get(mcode)
        n = int(cov.get(mcode, 0))
        is_core = mcode in CORE_MEASURES
        keep = is_core or n >= MIN_CONSENSUS_QUARTERS
        (kept if keep else dropped).append(mcode)
        tag = "CORE-keep" if is_core else ("keep" if keep else "DROP (thin)")
        print(f"{mcode:>7} {label:<22} {n:>9}  {tag}")
    print(f"\nKept {len(kept)} measures; dropped {len(dropped)}.\n")

    # ── Earnings calendar (one event per fiscal quarter) ─────────────────────────
    qact = act[act["pertype"] == 3].dropna(subset=["announcedate"])
    events = (qact.groupby("perenddate")["announcedate"].min()
                  .reset_index().sort_values("announcedate").reset_index(drop=True))
    events = events[events["announcedate"].dt.date >= START_DATE].reset_index(drop=True)
    events["next_earnings_date"] = events["announcedate"].shift(-1)

    annual_perends  = sorted(cons.loc[cons["pertype"] == 4, "perenddate"].unique())
    quarter_perends = sorted(cons.loc[cons["pertype"] == 3, "perenddate"].unique())

    rows = []
    for _, ev in events.iterrows():
        q_perend = ev["perenddate"]
        edate    = ev["announcedate"]                 # full timestamp (post-close time)
        ndate    = ev["next_earnings_date"]
        mdate    = model_date_from(edate.normalize())  # calendar-date basis for returns

        # Forward specific-return label (event level).
        alpha = {}
        for a, b in ALPHA_WINDOWS:
            val, ok = compound_specific_return(
                ret, mdate + pd.Timedelta(days=a), mdate + pd.Timedelta(days=b))
            alpha[f"alpha_spec_{a}_{b}"] = val
            alpha[f"alpha_spec_{a}_{b}_complete"] = ok
        overlaps_next = bool(ndate is not None and pd.notna(ndate)
                             and ndate <= mdate + pd.Timedelta(days=90))

        # Target periods per role.
        nxt_q = next((p for p in quarter_perends if p > q_perend), None)
        fwd_fy = [p for p in annual_perends if p > edate][:2]
        role_targets = {
            "reported_q": (3, q_perend),
            "next_q":     (3, nxt_q),
            "fy1":        (4, fwd_fy[0] if len(fwd_fy) > 0 else None),
            "fy2":        (4, fwd_fy[1] if len(fwd_fy) > 1 else None),
        }

        for mcode in kept:
            label = CORE_MEASURES.get(mcode) or CANDIDATE_MEASURES.get(mcode)
            for role, (ptype, tgt) in role_targets.items():
                if tgt is None:
                    continue

                pre   = pit_consensus(cons, mcode, ptype, tgt, edate, inclusive=False)
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

                pre_mean   = _num(pre["defmeanest"])   if pre   is not None else None
                post_mean  = _num(post7["defmeanest"]) if post7 is not None else None

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

                tgt_label = quarter_label(tgt) if ptype == 3 else annual_label(tgt)
                rows.append({
                    "ticker": TICKER, "estpermid": ESTPERMID, "isin": ISIN,
                    "barra_id": BARRA_ID,
                    "fiscal_period": quarter_label(q_perend),
                    "fiscal_quarter_end": q_perend.date(),
                    "earnings_date": edate.normalize().date(),
                    "earnings_datetime": edate,          # PIT precision (post-close time)
                    "model_date": mdate.date(),
                    "next_earnings_date": ndate.normalize().date() if pd.notna(ndate) else None,
                    "measure": mcode, "measure_label": label,
                    "measure_desc": desc_map.get(mcode),
                    "period_role": role, "target_pertype": ptype,
                    "target_period": tgt_label, "target_period_end": tgt.date(),
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

    df = pd.DataFrame(rows)
    validate(df)
    write_output(df)
    return df


# ── Validation (hard PIT + evidence gate) ──────────────────────────────────────
def validate(df: pd.DataFrame):
    print("=" * 70)
    print("VALIDATION")
    print("-" * 70)
    if df.empty:
        sys.exit("No rows produced - aborting.")

    errs = []
    edt = pd.to_datetime(df["earnings_datetime"])

    # PIT: pre-consensus strictly before the earnings announcement timestamp.
    m = df["consensus_pre_effectivedate"].notna()
    if (pd.to_datetime(df.loc[m, "consensus_pre_effectivedate"]) >= edt[m]).any():
        errs.append("pre-consensus effectivedate not strictly before earnings announcement")

    # PIT: post7 within 7 days of the earnings announcement.
    m = df["consensus_post7_effectivedate"].notna()
    if (pd.to_datetime(df.loc[m, "consensus_post7_effectivedate"]) >
            edt[m] + pd.Timedelta(days=7)).any():
        errs.append("post7-consensus effectivedate later than earnings + 7d")

    # PIT: model date strictly after earnings date.
    if (pd.to_datetime(df["model_date"]) <= pd.to_datetime(df["earnings_date"])).any():
        errs.append("model_date not strictly after earnings_date")

    # PIT: for the reported quarter, pre-consensus must predate the actual disclosure.
    m = (df["period_role"] == "reported_q") & \
        df["consensus_pre_effectivedate"].notna() & df["actual_effectivedate"].notna()
    if (pd.to_datetime(df.loc[m, "consensus_pre_effectivedate"]) >
            pd.to_datetime(df.loc[m, "actual_effectivedate"])).any():
        errs.append("pre-consensus dated after the actual it is compared to")

    # Label integrity: incomplete return windows must be NULL, not fabricated.
    for a, b in ALPHA_WINDOWS:
        col, flag = f"alpha_spec_{a}_{b}", f"alpha_spec_{a}_{b}_complete"
        if (df[~df[flag]][col].notna()).any():
            errs.append(f"{col} populated on an unclosed window")

    if errs:
        for e in errs:
            print("  FAIL:", e)
        sys.exit("PIT/evidence validation failed - not writing output.")
    print("  PASS: all PIT & evidence assertions hold.\n")

    # Coverage report.
    print(f"Events            : {df['fiscal_period'].nunique()} quarters "
          f"({df['earnings_date'].min()} -> {df['earnings_date'].max()})")
    print(f"Rows              : {len(df)}  (event x measure x role)")
    print(f"Measures kept     : {sorted(df['measure'].unique().tolist())}\n")

    rq = df[df["period_role"] == "reported_q"]
    print("Reported-quarter surprise coverage (non-null) per measure:")
    cov = (rq.groupby("measure_label")
             .agg(events=("fiscal_period", "nunique"),
                  actual=("actual_value", lambda s: s.notna().sum()),
                  consensus=("consensus_pre_mean", lambda s: s.notna().sum()),
                  surprise=("earnings_surprise", lambda s: s.notna().sum()))
             .sort_values("surprise", ascending=False))
    print(cov.to_string())
    lbl = "alpha_spec_0_90"
    n_lbl = rq.loc[rq[lbl].notna(), "fiscal_period"].nunique()
    print(f"\nForward-return label ({lbl}) complete for "
          f"{n_lbl} / {rq['fiscal_period'].nunique()} events "
          f"(recent events NULL until their window closes)\n")

    # One-quarter ground-truth spot check.
    spot = df[(df["fiscal_period"] == "FY2019-Q2") &
              (df["period_role"] == "reported_q") &
              (df["measure"].isin([9, 20]))]
    if not spot.empty:
        print("Spot check FY2019-Q2 (tie out to the transcript/press release):")
        for _, r in spot.iterrows():
            print(f"  {r['measure_label']:<8} actual={r['actual_value']}  "
                  f"pre-consensus={r['consensus_pre_mean']:.4f}  "
                  f"surprise={r['earnings_surprise']:.4f} "
                  f"({r['earnings_surprise_pct']*100:.1f}%)  "
                  f"n_est={r['consensus_pre_numests']}  "
                  f"as_of={r['consensus_pre_effectivedate']}")
        print()


def write_output(df: pd.DataFrame):
    os.makedirs(OUT_DIR, exist_ok=True)
    try:
        df.to_parquet(OUT_PARQUET, index=False)
        print(f"Wrote {OUT_PARQUET}  ({len(df)} rows)")
    except Exception as e:
        print(f"Parquet write skipped ({e}); writing CSV only.")
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}")
    out_xlsx = os.path.splitext(OUT_PARQUET)[0] + ".xlsx"
    write_excel(df, out_xlsx)
    print(f"Wrote {out_xlsx}")


if __name__ == "__main__":
    main()
