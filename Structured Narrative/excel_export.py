#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Excel export helper for the Structured Narrative outputs.

Why this exists
---------------
CSV cannot carry cell number-formats or column widths, so when the output
sheets are opened in Excel the date/time columns (e.g. ``earnings_datetime``
= "2015-01-29 16:01:00") are auto-detected as dates and rendered as
``########`` whenever the default column is too narrow.

``write_excel`` produces a real ``.xlsx`` where every date / datetime column
carries an explicit number format (``yyyy-mm-dd`` or ``yyyy-mm-dd hh:mm``) and
every column is widened to fit its contents, so nothing ever collapses to
``########``. The header row is frozen for easy scanning.

Used by single_company_extractor.py and narrative_zscore.py. Run directly to
(re)generate an .xlsx next to every .parquet already in output/:

    python "Structured Narrative/excel_export.py"
"""
import os
import glob

import pandas as pd
from openpyxl.utils import get_column_letter

DATE_FMT = "yyyy-mm-dd"
DATETIME_FMT = "yyyy-mm-dd hh:mm"
MAX_WIDTH = 42  # cap so a stray long string can't blow out a column


def _date_kind(series: pd.Series, name: str):
    """Return 'date', 'datetime', or None for a column.

    A column is treated as temporal if it is already a datetime dtype or its
    name looks date-ish. It is 'date' when every non-null value lands exactly
    on midnight, otherwise 'datetime'.
    """
    name_l = name.lower()
    looks_datey = any(k in name_l for k in ("date", "_end"))
    if not (pd.api.types.is_datetime64_any_dtype(series) or looks_datey):
        return None
    s = pd.to_datetime(series, errors="coerce")
    if s.notna().sum() == 0:
        return None
    nonnull = s.dropna()
    all_midnight = bool(
        (nonnull.dt.hour == 0).all()
        and (nonnull.dt.minute == 0).all()
        and (nonnull.dt.second == 0).all()
    )
    return "date" if all_midnight else "datetime"


def _col_width(series: pd.Series, header: str, kind) -> float:
    if kind == "date":
        content = 10          # yyyy-mm-dd
    elif kind == "datetime":
        content = 16          # yyyy-mm-dd hh:mm
    else:
        sample = series.dropna().astype(str)
        if len(sample) > 500:
            sample = sample.sample(500, random_state=0)
        content = int(sample.map(len).max()) if not sample.empty else 0
    return min(max(content, len(str(header))) + 2, MAX_WIDTH)


def write_excel(df: pd.DataFrame, path: str, sheet_name: str = "data") -> str:
    """Write ``df`` to ``path`` (.xlsx) with Excel-friendly date/time formatting
    and fitted column widths. Returns the path written."""
    out = df.copy()
    kinds = {}
    for col in out.columns:
        kind = _date_kind(out[col], col)
        if kind:
            out[col] = pd.to_datetime(out[col], errors="coerce")
            kinds[col] = kind

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        out.to_excel(writer, index=False, sheet_name=sheet_name)
        ws = writer.sheets[sheet_name]
        ws.freeze_panes = "A2"
        for i, col in enumerate(out.columns, start=1):
            letter = get_column_letter(i)
            kind = kinds.get(col)
            if kind:
                fmt = DATE_FMT if kind == "date" else DATETIME_FMT
                for cell in ws[letter][1:]:   # data cells only, skip header
                    cell.number_format = fmt
            ws.column_dimensions[letter].width = _col_width(out[col], col, kind)
    return path


def _regen_all(out_dir: str):
    parquets = sorted(glob.glob(os.path.join(out_dir, "*.parquet")))
    if not parquets:
        print(f"No .parquet files found in {out_dir}")
        return
    for pq in parquets:
        df = pd.read_parquet(pq)
        xlsx = os.path.splitext(pq)[0] + ".xlsx"
        write_excel(df, xlsx)
        print(f"Wrote {xlsx}  ({len(df)} rows)")


if __name__ == "__main__":
    OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    _regen_all(OUT_DIR)
