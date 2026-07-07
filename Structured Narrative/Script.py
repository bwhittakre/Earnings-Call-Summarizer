#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified Large-Cap SAM — LSEG × MSCI Historical Download
========================================================
Uses prebuilt Cassius tables instead of live cross-account LSEG/MSCI views.
Tables refreshed nightly by Snowflake Tasks (02:00 UTC LSEG, 02:30 UTC MSCI).
To force manual refresh: CALL CASSIUS.PUBLIC.REFRESH_LSEG_TABLES();
                         CALL CASSIUS.PUBLIC.REFRESH_MSCI_TABLES();

Table mapping (live → Cassius):
  vw_IBES2SumPer          → CASSIUS.PUBLIC.LSEG_CONSENSUS
  TREActRpt               → CASSIUS.PUBLIC.LSEG_ACTUALS
  ASSET_UNIVERSE_TS       → CASSIUS.PUBLIC.MSCI_UNIVERSE
  ASSET_MARKET_DATA_TS    → CASSIUS.PUBLIC.MSCI_MARKET_DATA
  ASSET_SPECIFIC_RETURN_TS→ CASSIUS.PUBLIC.MSCI_SPEC_RETURN
  SAM                     → CASSIUS.PUBLIC.SAMV1_DAILY (unchanged)

- Universe  : IRIS_V2.PUBLIC.IRIS_UNIV  (all US names, IS_BACKTEST_SAFE=TRUE)
- Cap filter : MSCI MARKET_CAP_IN_LOCAL >= $10B at Alpha_Start_0
- Survivor   : Dead companies included — IRIS_UNIV carries full history incl. delisted
- PIT LSEG   : Consensus gated by LSEG_FIRST_SEEN only (lower bound)
               Upper bound is CURRENT_DATE — LSEG_LAST_SEEN not used as ceiling
- Sectors    : All sectors, no filter — model is cross-sectional / sector-agnostic
- Measures   : (6),(9),(20),(22),(27),(185),(219),(229),(237),(240),(14),(8),
               (15),(19),(109),(141),(142),(153),(157),(173)
- Windows    : Alpha t0→60 and t60→90, anchored to actual next earnings date
- History    : 2013-01-01 → today
"""

import os
import pandas as pd
import pyarrow
from dotenv import load_dotenv
import snowflake.connector
from datetime import date

# ── Connection ────────────────────────────────────────────────────────────────
def get_snowflake_connection():
    # Load the .env sitting next to this script, regardless of the current
    # working directory the script is launched from.
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    conn = snowflake.connector.connect(
        account   = os.getenv("SNOWFLAKE_ACCOUNT"),
        user      = os.getenv("SNOWFLAKE_USER"),
        password  = os.getenv("SNOWFLAKE_PAT_TOKEN"),
        warehouse = os.getenv("SNOWFLAKE_WAREHOUSE"),
        database  = os.getenv("SNOWFLAKE_DATABASE"),
        schema    = os.getenv("SNOWFLAKE_SCHEMA"),
        role      = os.getenv("SNOWFLAKE_ROLE"),
    )
    return conn


# ── Market cap floor (USD millions) ──────────────────────────────────────────
MARKET_CAP_FLOOR_USD = 10_000_000_000   # $10 billion in raw USD (MSCI field is raw dollars)


# ── Query ─────────────────────────────────────────────────────────────────────
query = f"""
-- ============================================================================
-- Unified Large-Cap SAM  —  LSEG × MSCI PIT Download
-- ============================================================================
-- Universe : IRIS_V2.PUBLIC.IRIS_UNIV
--   • COUNTRY = 'US', IS_BACKTEST_SAFE = TRUE, ESTPERMID IS NOT NULL
--   • Includes delisted names (no survivor bias)
--   • LSEG consensus lower-gated by LSEG_FIRST_SEEN (upper bound = CURRENT_DATE)
-- Cap filter applied at Alpha_Start_0 via MSCI ASSET_MARKET_DATA_TS
--   • Only events where MARKET_CAP_IN_LOCAL >= {MARKET_CAP_FLOOR_USD} pass
-- Alpha windows dynamic, anchored to actual next earnings date
-- ============================================================================

WITH
chosen AS (
  SELECT
    'EFMUSATRD'::STRING  AS model,
    TO_DATE('2013-01-01') AS start_dt,
    CURRENT_DATE          AS end_dt,
    60::INT               AS forward_days,       -- fallback window 1 (no next earnings)
    30::INT               AS next_forward_days,  -- fallback window 2 (60→90)
    120::INT              AS lookback_days
),

-- ============================================================================
-- UNIVERSE  —  replaces sec_master + ibes_map + qaid_to_est
-- IRIS_UNIV already carries QAID, BARRA_ID, ISIN, SECCODE, ESTPERMID in one row.
-- IS_BACKTEST_SAFE = TRUE includes delisted names — no survivor bias.
-- LSEG_FIRST_SEEN used as lower bound for consensus pulls (LSEG_LAST_SEEN not used).
-- ============================================================================
input_univ AS (
  SELECT
      u.QAID,
      u.BARRA_ID,
      u.ISIN,
      u.SECCODE,
      u.TICKER,   -- add this after u.SECCODE
      u.ESTPERMID,
      u.SECTOR,
      u.LSEG_FIRST_SEEN,
      u.LSEG_LAST_SEEN
  FROM IRIS_V2.PUBLIC.IRIS_UNIV u
  WHERE u.COUNTRY        = 'US'
    AND u.IS_BACKTEST_SAFE = TRUE
    AND u.ESTPERMID       IS NOT NULL
    AND u.QAID            IS NOT NULL
    AND u.ISIN NOT LIKE 'CA%'              -- exclude Canadian cross-listed names
    AND u.LSEG_LAST_SEEN >= '2020-01-01'   -- exclude stale/dead names
),

-- ============================================================================
-- LSEG SECTION
-- ============================================================================

-- Explicit measure list
-- Core (unchanged) : 6=EBIT, 9=EPS, 20=Sales, 22=Capex, 27=GrossMargin,
--                    185=R&DExp, 219=SG&A, 229=CFO, 237=FCF, 240=Inventory,
--                    14=NetDebt, 8=EBITDA
-- Added for unified: 15=NetIncome, 19=ROE, 109=InterestExpense, 141=FFO,
--                    142=NOI, 153=ShareholdersEquity, 157=TotalAssets, 173=NIM
measures (Measure) AS (
  SELECT * FROM VALUES
    (6),(9),(20),(22),(27),(185),(219),(229),(237),(240),(14),(8),
    (15),(19),(109),(141),(142),(153),(157),(173)
),

-- Consensus snapshots — reads from prebuilt Cassius table (replaces live vw_IBES2SumPer)
-- PIT lower bound: LSEG_FIRST_SEEN (when coverage started)
-- Upper bound: CURRENT_DATE only — LSEG_LAST_SEEN NOT used as ceiling
-- (LSEG_LAST_SEEN caused premature data cutoff in prior version)
a AS (
  SELECT
      u.QAID,
      u.ISIN,
      c.EstPermID,
      c.PerEndDate,
      c.Measure,
      c.MEASURE_DESC,
      c.PerType,
      c.FYEMonth,
      c.HPIShort_Desc,
      c.EffectiveDate_Consensus  AS EffectiveDate_Consensus,
      c.DefMeanEst,
      c.NumEsts
  FROM CASSIUS.PUBLIC.LSEG_CONSENSUS c
  JOIN input_univ u
    ON c.EstPermID = u.ESTPERMID
  WHERE c.Measure      IN (6,9,20,22,27,185,219,229,237,240,14,8,
                            15,19,109,141,142,153,157,173)
    AND c.PerType      IN (3,4)
    AND c.HPIShort_Desc IN ('FQ1','FQ2','FY1','FY2')
    -- PIT lower bound: only pull consensus after LSEG coverage started
    AND c.EffectiveDate_Consensus >= COALESCE(u.LSEG_FIRST_SEEN, (SELECT start_dt FROM chosen))
    -- Upper bound: always CURRENT_DATE — never LSEG_LAST_SEEN
    AND c.EffectiveDate_Consensus <= (SELECT end_dt FROM chosen)
    -- Global date range
    AND c.EffectiveDate_Consensus BETWEEN (SELECT start_dt FROM chosen)
                                      AND (SELECT end_dt   FROM chosen)
),

-- Dominant FY regime per stock (most frequently observed FYEMonth)
fyemonth_stats AS (
  SELECT
      QAID, ISIN, FYEMonth,
      COUNT(*)                          AS obs_count,
      COUNT(DISTINCT EffectiveDate_Consensus) AS snapshot_count,
      MAX(EffectiveDate_Consensus)      AS last_seen
  FROM a
  WHERE FYEMonth IS NOT NULL
  GROUP BY QAID, ISIN, FYEMonth
),

fyemonth_ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY QAID, ISIN
      ORDER BY snapshot_count DESC, obs_count DESC, last_seen DESC
    ) AS rn
  FROM fyemonth_stats
),

main_fyemonth AS (
  SELECT QAID, ISIN, FYEMonth AS Main_FYEMonth
  FROM fyemonth_ranked
  WHERE rn = 1
),

-- Deduplicate identical (EstPermID, period, effective date) by highest coverage
a_post_dedup AS (
  SELECT *
  FROM (
    SELECT
        a.QAID, a.ISIN, a.EstPermID, a.PerEndDate,
        a.Measure, a.MEASURE_DESC, a.PerType, a.FYEMonth,
        a.HPIShort_Desc, a.EffectiveDate_Consensus,
        a.DefMeanEst, a.NumEsts,
        ROW_NUMBER() OVER (
          PARTITION BY a.EstPermID, a.PerType, a.Measure,
                       a.HPIShort_Desc, a.EffectiveDate_Consensus
          ORDER BY a.NumEsts DESC
        ) AS rnk
    FROM a
    JOIN main_fyemonth mf
      ON  mf.QAID      = a.QAID
      AND mf.ISIN      = a.ISIN
      AND mf.Main_FYEMonth = a.FYEMonth   -- single FY regime per stock
  )
  WHERE rnk = 1
),

-- Reported actuals — reads from prebuilt Cassius table (replaces live TREActRpt)
-- LSEG_ACTUALS is pre-deduped at source; field names match original b CTE exactly
b AS (
  SELECT
      ac.EstPermID,
      ac.PerType,
      ac.Measure,
      ac.PerEndDate,
      ac.FYEMonth,
      ac.EffectiveDate_Actuals,
      ac.NormActValue
  FROM CASSIUS.PUBLIC.LSEG_ACTUALS ac
  WHERE ac.EffectiveDate_Actuals BETWEEN (SELECT start_dt FROM chosen)
                                     AND (SELECT end_dt   FROM chosen)
    AND ac.Measure IN (6,9,20,22,27,185,219,229,237,240,14,8,
                       15,19,109,141,142,153,157,173)
    AND ac.PerType IN (3,4)
),

-- Distinct earnings dates per QAID/ISIN
earnings_dates AS (
  SELECT DISTINCT
      u.QAID, u.ISIN,
      b.EffectiveDate_Actuals
  FROM input_univ u
  JOIN b ON b.EstPermID = u.ESTPERMID
),

-- Next earnings date per event via LEAD()
next_earnings AS (
  SELECT
      QAID, ISIN, EffectiveDate_Actuals,
      LEAD(EffectiveDate_Actuals) OVER (
          PARTITION BY QAID, ISIN
          ORDER BY EffectiveDate_Actuals
      ) AS Next_Earnings_Date
  FROM earnings_dates
),

-- Event grid: earnings × period × measure
grid AS (
  SELECT
      e.QAID, e.ISIN,
      e.EffectiveDate_Actuals,
      ne.Next_Earnings_Date,
      p.HPIShort_Desc,
      m.Measure,
      -- Model date: earnings + 7 days, adjusted off weekends
      CASE
        WHEN DAYOFWEEK(DATEADD(day,7,e.EffectiveDate_Actuals)) = 1
          THEN DATEADD(day,6,e.EffectiveDate_Actuals)
        WHEN DAYOFWEEK(DATEADD(day,7,e.EffectiveDate_Actuals)) = 7
          THEN DATEADD(day,8,e.EffectiveDate_Actuals)
        ELSE DATEADD(day,7,e.EffectiveDate_Actuals)
      END AS EffectiveDate_Model
  FROM earnings_dates e
  JOIN next_earnings ne
    ON  ne.QAID                  = e.QAID
    AND ne.ISIN                  = e.ISIN
    AND ne.EffectiveDate_Actuals = e.EffectiveDate_Actuals
  CROSS JOIN (
    SELECT 'FQ1' AS HPIShort_Desc UNION ALL
    SELECT 'FQ2'                  UNION ALL
    SELECT 'FY1'                  UNION ALL
    SELECT 'FY2'
  ) p
  CROSS JOIN measures m
),

-- Dynamic alpha window anchors
anchors AS (
  SELECT
      g.*,
      g.EffectiveDate_Model AS Alpha_Start_0,

      -- Alpha_End_60: next earnings − 30d  (fallback: +60d fixed)
      CASE
        WHEN g.Next_Earnings_Date IS NULL
          THEN DATEADD(day, (SELECT forward_days FROM chosen), g.EffectiveDate_Model)
        WHEN DATEDIFF(day, g.EffectiveDate_Model, g.Next_Earnings_Date) > 120
          THEN DATEADD(day, (SELECT forward_days FROM chosen), g.EffectiveDate_Model)
        ELSE DATEADD(day, -30, g.Next_Earnings_Date)
      END AS Alpha_End_60,

      -- Alpha_End_90: next earnings date itself (fallback: +90d fixed)
      CASE
        WHEN g.Next_Earnings_Date IS NULL
          THEN DATEADD(day, (SELECT forward_days + next_forward_days FROM chosen), g.EffectiveDate_Model)
        WHEN DATEDIFF(day, g.EffectiveDate_Model, g.Next_Earnings_Date) > 120
          THEN DATEADD(day, (SELECT forward_days + next_forward_days FROM chosen), g.EffectiveDate_Model)
        ELSE g.Next_Earnings_Date
      END AS Alpha_End_90

  FROM grid g
),

-- PRE consensus: latest snapshot <= earnings date, within lookback window
consensus_pre_final AS (
  SELECT
      g.QAID, g.ISIN, g.EffectiveDate_Actuals, g.HPIShort_Desc, g.Measure,
      a.EstPermID, a.PerType, a.FYEMonth, a.PerEndDate, a.MEASURE_DESC,
      a.DefMeanEst               AS DefMeanEst_Pre,
      a.EffectiveDate_Consensus  AS EffectiveDate_Consensus_Pre
  FROM anchors g
  LEFT JOIN a_post_dedup a
    ON  a.QAID            = g.QAID
    AND a.HPIShort_Desc   = g.HPIShort_Desc
    AND a.Measure         = g.Measure
    AND a.EffectiveDate_Consensus <= g.EffectiveDate_Actuals
    AND a.EffectiveDate_Consensus >= DATEADD(day, -(SELECT lookback_days FROM chosen), g.EffectiveDate_Actuals)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY g.QAID, g.ISIN, g.EffectiveDate_Actuals, g.HPIShort_Desc, g.Measure
    ORDER BY a.EffectiveDate_Consensus DESC, a.NumEsts DESC
  ) = 1
),

-- POST7 consensus: latest snapshot in (0,7] days after earnings
consensus_post7_final AS (
  SELECT
      g.QAID, g.ISIN, g.EffectiveDate_Actuals, g.HPIShort_Desc, g.Measure,
      a.EstPermID, a.PerType, a.FYEMonth, a.PerEndDate, a.MEASURE_DESC,
      a.DefMeanEst               AS DefMeanEst_Post7,
      a.EffectiveDate_Consensus  AS EffectiveDate_Consensus_Post7
  FROM anchors g
  LEFT JOIN a_post_dedup a
    ON  a.QAID            = g.QAID
    AND a.HPIShort_Desc   = g.HPIShort_Desc
    AND a.Measure         = g.Measure
    AND a.EffectiveDate_Consensus >  g.EffectiveDate_Actuals
    AND a.EffectiveDate_Consensus <= DATEADD(day, 7, g.EffectiveDate_Actuals)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY g.QAID, g.ISIN, g.EffectiveDate_Actuals, g.HPIShort_Desc, g.Measure
    ORDER BY a.EffectiveDate_Consensus DESC, a.NumEsts DESC
  ) = 1
),

-- POST60 consensus: latest snapshot in (7d, Alpha_End_60]
consensus_post60_final AS (
  SELECT
      g.QAID, g.ISIN, g.EffectiveDate_Actuals, g.HPIShort_Desc, g.Measure,
      a.EstPermID, a.PerType, a.FYEMonth, a.PerEndDate, a.MEASURE_DESC,
      a.DefMeanEst               AS DefMeanEst_Post60,
      a.EffectiveDate_Consensus  AS EffectiveDate_Consensus_Post60
  FROM anchors g
  LEFT JOIN a_post_dedup a
    ON  a.QAID            = g.QAID
    AND a.HPIShort_Desc   = g.HPIShort_Desc
    AND a.Measure         = g.Measure
    AND a.EffectiveDate_Consensus >  g.EffectiveDate_Actuals
    AND a.EffectiveDate_Consensus <= g.Alpha_End_60
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY g.QAID, g.ISIN, g.EffectiveDate_Actuals, g.HPIShort_Desc, g.Measure
    ORDER BY a.EffectiveDate_Consensus DESC, a.NumEsts DESC
  ) = 1
),

-- Reported actuals (FQ1/FY1 only, matched to FY regime)
actuals_reported AS (
  SELECT
      u.QAID, u.ISIN,
      b.EffectiveDate_Actuals,
      b.Measure,
      CASE WHEN b.PerType = 3 THEN 'FQ1'
           WHEN b.PerType = 4 THEN 'FY1'
      END AS HPIShort_Desc,
      b.NormActValue AS Actual_Value
  FROM input_univ u
  JOIN b ON b.EstPermID = u.ESTPERMID
  JOIN main_fyemonth mf
    ON  mf.QAID = u.QAID
    AND mf.ISIN = u.ISIN
    AND mf.Main_FYEMonth = b.FYEMonth   -- single FY regime lock
),

-- Assembled LSEG layer
lseg AS (
  SELECT
      g.QAID, g.ISIN, g.Measure,
      COALESCE(cp.MEASURE_DESC, c7.MEASURE_DESC)  AS MEASURE_DESC,
      COALESCE(cp.PerType,      c7.PerType)        AS PerType,
      COALESCE(cp.FYEMonth,     c7.FYEMonth)       AS FYEMonth,
      COALESCE(cp.PerEndDate,   c7.PerEndDate)     AS PerEndDate,
      g.HPIShort_Desc,

      cp.DefMeanEst_Pre    AS Consensus_Pre,
      c7.DefMeanEst_Post7  AS Consensus_Post7,
      c60.DefMeanEst_Post60 AS Consensus_Post60,

      ar.Actual_Value,

      cp.EffectiveDate_Consensus_Pre,
      c7.EffectiveDate_Consensus_Post7,
      c60.EffectiveDate_Consensus_Post60,

      g.EffectiveDate_Actuals,
      g.EffectiveDate_Model,
      g.Alpha_Start_0,
      g.Alpha_End_60,
      g.Alpha_End_90,
      g.Next_Earnings_Date

  FROM anchors g
  LEFT JOIN consensus_pre_final    cp  ON  cp.QAID = g.QAID  AND cp.ISIN = g.ISIN
                                       AND cp.EffectiveDate_Actuals = g.EffectiveDate_Actuals
                                       AND cp.HPIShort_Desc = g.HPIShort_Desc
                                       AND cp.Measure = g.Measure
  LEFT JOIN consensus_post7_final  c7  ON  c7.QAID = g.QAID  AND c7.ISIN = g.ISIN
                                       AND c7.EffectiveDate_Actuals = g.EffectiveDate_Actuals
                                       AND c7.HPIShort_Desc = g.HPIShort_Desc
                                       AND c7.Measure = g.Measure
  LEFT JOIN consensus_post60_final c60 ON c60.QAID = g.QAID  AND c60.ISIN = g.ISIN
                                       AND c60.EffectiveDate_Actuals = g.EffectiveDate_Actuals
                                       AND c60.HPIShort_Desc = g.HPIShort_Desc
                                       AND c60.Measure = g.Measure
  LEFT JOIN actuals_reported       ar  ON  ar.QAID = g.QAID  AND ar.ISIN = g.ISIN
                                       AND ar.EffectiveDate_Actuals = g.EffectiveDate_Actuals
                                       AND ar.Measure = g.Measure
                                       AND ar.HPIShort_Desc = g.HPIShort_Desc
),

-- SAM period end date adjustment (used by SAM overlay joins)
sam_keys AS (
  SELECT
      l.*,
      CASE
        WHEN l.HPIShort_Desc IN ('FQ1','FQ2')
          THEN DATEADD(quarter, 1, l.PerEndDate)
        ELSE l.PerEndDate
      END AS SAM_PerEndDate_Post
  FROM lseg l
),

-- SAM PRE
sam_pre_final AS (
  SELECT
      l.QAID, l.ISIN, l.Measure, l.HPIShort_Desc, l.EffectiveDate_Actuals,
      s.VALUE_    AS SAM_EST_PRE,
      s.STARTDATE AS SAM_EFFECTIVEDATE_PRE
  FROM sam_keys l
  LEFT JOIN CASSIUS.PUBLIC.SAMV1_DAILY s
    ON  s.QAID    = l.QAID
    AND s.MEASURE = l.Measure
    AND s.ITEM    = 1
    AND s.FSCPERIOD = CASE
      WHEN l.HPIShort_Desc = 'FQ1' THEN 1
      WHEN l.HPIShort_Desc = 'FQ2' THEN 2
      WHEN l.HPIShort_Desc = 'FY1' THEN 3
      WHEN l.HPIShort_Desc = 'FY2' THEN 4
    END
    AND s.STARTDATE <= l.EffectiveDate_Actuals
    AND s.STARTDATE >= DATEADD(day, -180, l.EffectiveDate_Actuals)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY l.QAID, l.ISIN, l.Measure, l.HPIShort_Desc, l.EffectiveDate_Actuals
    ORDER BY s.FSCPERDATE DESC, s.STARTDATE DESC
  ) = 1
),

-- SAM POST7
sam_post7_final AS (
  SELECT
      l.QAID, l.ISIN, l.Measure, l.HPIShort_Desc, l.EffectiveDate_Actuals,
      s.VALUE_    AS SAM_EST_POST7,
      s.STARTDATE AS SAM_EFFECTIVEDATE_POST7
  FROM sam_keys l
  LEFT JOIN CASSIUS.PUBLIC.SAMV1_DAILY s
    ON  s.QAID    = l.QAID
    AND s.MEASURE = l.Measure
    AND s.ITEM    = 1
    AND s.FSCPERIOD = CASE
      WHEN l.HPIShort_Desc = 'FQ1' THEN 1
      WHEN l.HPIShort_Desc = 'FQ2' THEN 2
      WHEN l.HPIShort_Desc = 'FY1' THEN 3
      WHEN l.HPIShort_Desc = 'FY2' THEN 4
    END
    AND s.STARTDATE >  l.EffectiveDate_Actuals
    AND s.STARTDATE <= l.EffectiveDate_Model
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY l.QAID, l.ISIN, l.Measure, l.HPIShort_Desc, l.EffectiveDate_Actuals
    ORDER BY s.FSCPERDATE DESC, s.STARTDATE DESC
  ) = 1
),

-- SAM POST60
sam_post60_final AS (
  SELECT
      l.QAID, l.ISIN, l.Measure, l.HPIShort_Desc, l.EffectiveDate_Actuals,
      s.VALUE_    AS SAM_EST_POST60,
      s.STARTDATE AS SAM_EFFECTIVEDATE_POST60
  FROM sam_keys l
  LEFT JOIN CASSIUS.PUBLIC.SAMV1_DAILY s
    ON  s.QAID    = l.QAID
    AND s.MEASURE = l.Measure
    AND s.ITEM    = 1
    AND s.FSCPERIOD = CASE
      WHEN l.HPIShort_Desc = 'FQ1' THEN 1
      WHEN l.HPIShort_Desc = 'FQ2' THEN 2
      WHEN l.HPIShort_Desc = 'FY1' THEN 3
      WHEN l.HPIShort_Desc = 'FY2' THEN 4
    END
    AND s.STARTDATE >  l.EffectiveDate_Actuals
    AND s.STARTDATE <= l.Alpha_End_60
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY l.QAID, l.ISIN, l.Measure, l.HPIShort_Desc, l.EffectiveDate_Actuals
    ORDER BY s.FSCPERDATE DESC, s.STARTDATE DESC
  ) = 1
),

-- ============================================================================
-- MSCI SECTION
-- ============================================================================

-- MSCI BARRA_ID resolution — reads from prebuilt CASSIUS.PUBLIC.MSCI_UNIVERSE
-- As-of join: latest BARRA_ID on or before Alpha_Start_0
-- Matches extract.py map_resolved logic exactly (QUALIFY replaces subquery)
map_resolved AS (
  SELECT DISTINCT
      l.ISIN, l.Alpha_Start_0, l.Alpha_End_60, l.Alpha_End_90,
      u.BARRA_ID, u.MODEL
  FROM (
    SELECT DISTINCT ISIN, Alpha_Start_0, Alpha_End_60, Alpha_End_90
    FROM lseg
  ) l
  LEFT JOIN CASSIUS.PUBLIC.MSCI_UNIVERSE u
    ON  u.ISIN          = l.ISIN
    AND u.MODEL         = 'EFMUSATRD'
    AND u.DATE_OF_DATA <= l.Alpha_Start_0
    AND u.DATE_OF_DATA BETWEEN (SELECT start_dt FROM chosen)
                            AND DATEADD(day, 180, (SELECT end_dt FROM chosen))
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY l.ISIN, l.Alpha_Start_0
    ORDER BY u.DATE_OF_DATA DESC
  ) = 1
),

-- Market cap — reads from prebuilt CASSIUS.PUBLIC.MSCI_MARKET_DATA
market_cap AS (
  SELECT m.MODEL, m.BARRA_ID, m.DATE_OF_DATA, m.MARKET_CAP_IN_LOCAL
  FROM CASSIUS.PUBLIC.MSCI_MARKET_DATA m
  WHERE m.MODEL = 'EFMUSATRD'
    AND m.DATE_OF_DATA BETWEEN (SELECT start_dt FROM chosen)
                            AND DATEADD(day, 180, (SELECT end_dt FROM chosen))
),

-- Specific return — reads from prebuilt CASSIUS.PUBLIC.MSCI_SPEC_RETURN
-- Pre-filtered to HORIZON='D' at source — no HORIZON filter needed here
spec_d AS (
  SELECT s.MODEL, s.BARRA_ID, s.DATE_OF_DATA, s.SPECIFIC_RETURN
  FROM CASSIUS.PUBLIC.MSCI_SPEC_RETURN s
  WHERE s.MODEL = 'EFMUSATRD'
    AND s.DATE_OF_DATA BETWEEN (SELECT start_dt FROM chosen)
                            AND DATEADD(day, 180, (SELECT end_dt FROM chosen))
    AND s.SPECIFIC_RETURN IS NOT NULL
    AND s.SPECIFIC_RETURN > -0.999999
),

-- Compounded specific return: t0 → t60
alpha_0_60 AS (
  SELECT
      m.ISIN, m.Alpha_Start_0, m.Alpha_End_60,
      EXP(SUM(CASE WHEN s.SPECIFIC_RETURN > -0.999999
                   THEN LN(1 + s.SPECIFIC_RETURN) END)) - 1 AS alpha_spec_0_60
  FROM map_resolved m
  LEFT JOIN spec_d s
    ON  s.MODEL       = m.MODEL
    AND s.BARRA_ID    = m.BARRA_ID
    AND s.DATE_OF_DATA >  m.Alpha_Start_0
    AND s.DATE_OF_DATA <= m.Alpha_End_60
  WHERE s.SPECIFIC_RETURN IS NOT NULL
  GROUP BY m.ISIN, m.Alpha_Start_0, m.Alpha_End_60
),

-- Compounded specific return: t60 → t90
alpha_60_90 AS (
  SELECT
      m.ISIN, m.Alpha_End_60, m.Alpha_End_90,
      EXP(SUM(CASE WHEN s.SPECIFIC_RETURN > -0.999999
                   THEN LN(1 + s.SPECIFIC_RETURN) END)) - 1 AS alpha_spec_60_90
  FROM map_resolved m
  LEFT JOIN spec_d s
    ON  s.MODEL       = m.MODEL
    AND s.BARRA_ID    = m.BARRA_ID
    AND s.DATE_OF_DATA >  m.Alpha_End_60
    AND s.DATE_OF_DATA <= m.Alpha_End_90
  WHERE s.SPECIFIC_RETURN IS NOT NULL
  GROUP BY m.ISIN, m.Alpha_End_60, m.Alpha_End_90
),

-- Compounded specific return: t0 → t90 (full window)
alpha_0_90 AS (
  SELECT
      m.ISIN, m.Alpha_Start_0, m.Alpha_End_90,
      EXP(SUM(CASE WHEN s.SPECIFIC_RETURN > -0.999999
                   THEN LN(1 + s.SPECIFIC_RETURN) END)) - 1 AS alpha_spec_0_90
  FROM map_resolved m
  LEFT JOIN spec_d s
    ON  s.MODEL       = m.MODEL
    AND s.BARRA_ID    = m.BARRA_ID
    AND s.DATE_OF_DATA >  m.Alpha_Start_0
    AND s.DATE_OF_DATA <= m.Alpha_End_90
  WHERE s.SPECIFIC_RETURN IS NOT NULL
  GROUP BY m.ISIN, m.Alpha_Start_0, m.Alpha_End_90
),

-- Market cap as of Alpha_Start_0 — equality join (no correlated subquery)
-- map_resolved already resolved the latest BARRA_ID as-of Alpha_Start_0
-- so equality join on DATE_OF_DATA = Alpha_Start_0 is correct and fast
-- $10B filter applied here — events below threshold are excluded entirely
cap_latest AS (
  SELECT
      m.ISIN, m.Alpha_Start_0,
      mc.MARKET_CAP_IN_LOCAL
  FROM map_resolved m
  LEFT JOIN market_cap mc
    ON  mc.MODEL        = m.MODEL
    AND mc.BARRA_ID     = m.BARRA_ID
    AND mc.DATE_OF_DATA = m.Alpha_Start_0
  WHERE mc.MARKET_CAP_IN_LOCAL >= {MARKET_CAP_FLOOR_USD}      -- $10B large-cap filter (raw USD)
)

-- ============================================================================
-- FINAL OUTPUT
-- ============================================================================
SELECT
    l.QAID,
    l.ISIN,
    u.SECTOR,                              -- carried from IRIS_UNIV (informational only)
    u.TICKER,                              -- exchange ticker (AAPL, MSFT) — for portfolio display
    u.SECCODE,                             -- IBES security code — fallback identifier
    l.Measure,
    l.MEASURE_DESC,
    l.PerType,
    l.FYEMonth,
    l.HPIShort_Desc,

    -- Consensus
    l.Consensus_Pre,
    l.Consensus_Post7,
    l.Consensus_Post60,

    -- SAM overlay
    sp.SAM_EST_PRE       AS SAM_Pre,
    s7.SAM_EST_POST7     AS SAM_Post7,
    s60.SAM_EST_POST60   AS SAM_Post60,

    -- Actuals
    l.Actual_Value,

    -- Effective dates — consensus
    l.EffectiveDate_Consensus_Pre,
    l.EffectiveDate_Consensus_Post7,
    l.EffectiveDate_Consensus_Post60,

    -- Effective dates — SAM
    sp.SAM_EFFECTIVEDATE_PRE,
    s7.SAM_EFFECTIVEDATE_POST7,
    s60.SAM_EFFECTIVEDATE_POST60,

    -- Event dates
    l.EffectiveDate_Actuals,
    l.EffectiveDate_Model,

    -- Alpha (specific return)
    a60.alpha_spec_0_60    AS Alpha_Specific_Return_0_60,
    a6090.alpha_spec_60_90 AS Alpha_Specific_Return_60_90,
    a90.alpha_spec_0_90    AS Alpha_Specific_Return_0_90,

    -- Market cap at event date (already filtered >= $10B)
    c.MARKET_CAP_IN_LOCAL  AS Market_Cap_Local_USD,

    -- Window metadata
    l.Next_Earnings_Date,
    DATEDIFF(day, l.EffectiveDate_Model, l.Alpha_End_90) AS Forward_Days_90,
    DATEDIFF(day, l.EffectiveDate_Model, l.Alpha_End_60) AS Forward_Days_60,
    l.Alpha_Start_0   AS Alpha_Start_Date,
    l.Alpha_End_60    AS Alpha_End_Date_60,
    l.Alpha_End_90    AS Alpha_End_Date_90

FROM lseg l

-- Bring in SECTOR, TICKER, SECCODE from IRIS_UNIV (informational — not used as filter)
JOIN input_univ u
  ON u.QAID = l.QAID AND u.ISIN = l.ISIN

LEFT JOIN sam_pre_final  sp
  ON  sp.QAID = l.QAID AND sp.ISIN = l.ISIN
  AND sp.Measure = l.Measure AND sp.HPIShort_Desc = l.HPIShort_Desc
  AND sp.EffectiveDate_Actuals = l.EffectiveDate_Actuals

LEFT JOIN sam_post7_final s7
  ON  s7.QAID = l.QAID AND s7.ISIN = l.ISIN
  AND s7.Measure = l.Measure AND s7.HPIShort_Desc = l.HPIShort_Desc
  AND s7.EffectiveDate_Actuals = l.EffectiveDate_Actuals

LEFT JOIN sam_post60_final s60
  ON  s60.QAID = l.QAID AND s60.ISIN = l.ISIN
  AND s60.Measure = l.Measure AND s60.HPIShort_Desc = l.HPIShort_Desc
  AND s60.EffectiveDate_Actuals = l.EffectiveDate_Actuals

LEFT JOIN alpha_0_60 a60
  ON  a60.ISIN = l.ISIN
  AND a60.Alpha_Start_0 = l.Alpha_Start_0
  AND a60.Alpha_End_60  = l.Alpha_End_60

LEFT JOIN alpha_60_90 a6090
  ON  a6090.ISIN = l.ISIN
  AND a6090.Alpha_End_60 = l.Alpha_End_60
  AND a6090.Alpha_End_90 = l.Alpha_End_90

LEFT JOIN alpha_0_90 a90
  ON  a90.ISIN = l.ISIN
  AND a90.Alpha_Start_0 = l.Alpha_Start_0
  AND a90.Alpha_End_90  = l.Alpha_End_90

-- Cap filter: INNER join enforces $10B threshold — events below cap are dropped
JOIN cap_latest c
  ON  c.ISIN         = l.ISIN
  AND c.Alpha_Start_0 = l.Alpha_Start_0

-- NOTE: a90.alpha_spec_0_90 IS NOT NULL removed — recent event dates whose
-- 90-day return window has not yet closed have NULL alpha but valid features.
-- They are needed for daily scoring with the frozen model. The feature
-- engineering module (02) and scorer handle NULL targets correctly.

ORDER BY l.QAID, l.Measure, l.HPIShort_Desc, l.EffectiveDate_Model;
"""


# ── Execute & Save ────────────────────────────────────────────────────────────
import time
def run_query(conn, q, label):
    print(f"  Running: {label}...")
    t0  = time.time()
    cur = conn.cursor()
    cur.execute(q)
    cols = [d[0].upper() for d in cur.description]
    rows = cur.fetchall()
    cur.close()
    result = pd.DataFrame(rows, columns=cols)
    print(f"  ✅ {label}: {len(result):,} rows in {time.time()-t0:.1f}s")
    return result

conn = get_snowflake_connection()
print("✅ Snowflake connection established")
df = run_query(conn, query, "unified_largecap_sam_history")
conn.close()
print("✅ Snowflake connection closed")

# ── Diagnostics ───────────────────────────────────────────────────────────────
unique_qaids   = df["QAID"].nunique()
unique_sectors = df["SECTOR"].nunique()
date_range     = f"{df['EFFECTIVEDATE_MODEL'].min()} → {df['EFFECTIVEDATE_MODEL'].max()}" \
                 if "EFFECTIVEDATE_MODEL" in df.columns \
                 else f"{df['EffectiveDate_Model'].min()} → {df['EffectiveDate_Model'].max()}"

print(f"✅ Rows returned      : {len(df):,}")
print(f"✅ Unique QAIDs       : {unique_qaids:,}")
print(f"✅ Unique sectors     : {unique_sectors}")
print(f"✅ Date range         : {date_range}")

# Ticker coverage — confirm TICKER column populated
ticker_col = "TICKER" if "TICKER" in df.columns else None
if ticker_col:
    null_ticker = df[ticker_col].isna().mean()
    print(f"✅ Ticker coverage    : {1-null_ticker:.1%} non-null "
          f"({df[ticker_col].nunique():,} unique tickers)")
else:
    print("⚠️  TICKER column not found in output")

# Sector breakdown
sector_col = "SECTOR" if "SECTOR" in df.columns else "sector"
if sector_col in df.columns:
    print("\n── Sector breakdown (unique QAIDs) ──")
    print(df.groupby(sector_col)["QAID"].nunique().sort_values(ascending=False).to_string())

# Cap distribution sanity check
cap_col = "Market_Cap_Local_USD" if "Market_Cap_Local_USD" in df.columns else "MARKET_CAP_LOCAL_USD"
if cap_col in df.columns:
    print(f"\n── Market cap (USD mm) ──")
    print(df[cap_col].describe(percentiles=[.1,.25,.5,.75,.9,.99]).round(0).to_string())

# ── Save ──────────────────────────────────────────────────────────────────────
output_path = (
    r"C:\Users\BobbyWhittaker\OneDrive - Cassius Capital\Desktop"
    r"\Earnings Call Summarizer\Structured Narrative"
    r"\Unified\Unified_LargeCap_SAM_2013_history_v2.parquet"
)
os.makedirs(os.path.dirname(output_path), exist_ok=True)

# ── ISIN deduplication — keep latest QAID per ISIN ───────────────────────────
# Some companies have multiple QAIDs in IRIS_UNIV for the same ISIN due to
# corporate events (e.g. UAL = 'UAL' and 'UAUAV' both map to US9100471096).
# The Barra matrices only carry one QAID per name — typically the newer one.
# We deduplicate by keeping the QAID with the most recent EffectiveDate_Model
# per ISIN, which is the one the Barra universe will recognise.
date_col = "EFFECTIVEDATE_MODEL" if "EFFECTIVEDATE_MODEL" in df.columns else "EffectiveDate_Model"
if df.groupby("ISIN")["QAID"].nunique().max() > 1:
    duped_isins = df.groupby("ISIN")["QAID"].nunique()
    duped_isins = duped_isins[duped_isins > 1].index.tolist()
    print(f"\n── QAID deduplication ──")
    print(f"  ISINs with multiple QAIDs: {len(duped_isins)}")
    for isin in duped_isins[:10]:
        qaids = df[df["ISIN"] == isin]["QAID"].unique()
        # Keep the QAID with the most recent event date
        latest_qaid = (df[df["ISIN"] == isin]
                       .groupby("QAID")[date_col].max()
                       .idxmax())
        dropped = [q for q in qaids if q != latest_qaid]
        print(f"  ISIN={isin}: keeping {latest_qaid}, dropping {dropped}")
        df = df[~((df["ISIN"] == isin) & (df["QAID"].isin(dropped)))]
    print(f"  After dedup: {df['QAID'].nunique():,} unique QAIDs")


# Rename BK → BNY (Bank of New York Mellon rebranded ticker in 2024)
df["TICKER"] = df["TICKER"].replace("BK", "BNY")
df.to_parquet(output_path, index=False)

# Exclude non-US names that slip through the universe filter
# 05539010 = Canadian company incorrectly included via LSEG QAID mapping
EXCLUDE_QAIDS = {"05539010"}
n_before = len(df)
df = df[~df["QAID"].isin(EXCLUDE_QAIDS)].copy()
n_excluded = n_before - len(df)
if n_excluded > 0:
    print(f"  Excluded {n_excluded:,} rows for QAIDs: {EXCLUDE_QAIDS}")

df.to_parquet(output_path, index=False)
print(f"\n✅ Saved → {output_path}")
print(df.head())
