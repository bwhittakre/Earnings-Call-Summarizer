"""Expose cross_company HTML reports via Streamlit static file serving."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence
from urllib.parse import quote, urlencode

from .research_data import resolve_cross_company_root
from .sectors import ALL_COMPANIES, CUSTOM_LIST

# Streamlit serves ``<app_dir>/static`` when enableStaticServing is on.
# Confirmed URL shape (Streamlit 1.60): ``/app/static/<relative-path>``.
_STATIC_URL_PREFIX = "/app/static/reports"


def html_report_filter_args(
    sector_choice: str,
    sector_tickers: Sequence[str] | None,
    available_tickers: Sequence[str],
) -> tuple[list[str] | None, str | None]:
    """Map Roz sidebar sector choice → iframe ``tickers`` / ``preset`` query args.

    Returns ``(tickers, preset)`` where either or both may be ``None``:
    - All Companies → ``(None, None)`` (plain URL; HTML shows full book)
    - Named sector stem → ``(None, preset)`` so HTML loads that sector checklist
    - Custom List → ``(tickers, None)`` preserving sidebar order
    """
    available = [str(t).upper() for t in available_tickers if str(t).strip()]
    if not sector_choice or sector_choice == ALL_COMPANIES:
        return None, None
    if sector_choice == CUSTOM_LIST:
        selected = [str(t).upper() for t in (sector_tickers or ()) if str(t).strip()]
        available_set = set(available)
        tickers = [t for t in selected if t in available_set]
        return (tickers or None), None
    return None, str(sector_choice)


def reports_source_dir(
    history_source: str | os.PathLike[str] | None = None,
) -> Path:
    return resolve_cross_company_root(history_source) / "reports"


def _link_reports(static_reports: Path, source: Path) -> bool:
    static_reports.parent.mkdir(parents=True, exist_ok=True)
    try:
        if static_reports.is_symlink():
            if static_reports.resolve() == source.resolve():
                return True
            static_reports.unlink()
        elif static_reports.exists():
            if static_reports.is_dir() and not any(static_reports.iterdir()):
                static_reports.rmdir()
            else:
                return any(static_reports.glob("*.html"))
        os.symlink(source, static_reports, target_is_directory=True)
    except OSError:
        return False
    return static_reports.exists()


def ensure_reports_static_link(
    history_source: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Symlink reports into Streamlit's static folder(s).

    Streamlit looks next to the main script
    (``…/dashboard/static``). Also link ``cwd/static`` for local runs.
    """
    source = reports_source_dir(history_source)
    if not source.is_dir():
        return None

    candidates = [
        Path(__file__).resolve().parent / "static" / "reports",
        Path.cwd() / "static" / "reports",
    ]
    ready: Path | None = None
    for target in candidates:
        if _link_reports(target, source):
            ready = target
    return ready


def static_report_url(
    filename: str,
    *,
    tickers: Sequence[str] | str | None = None,
    preset: str | None = None,
) -> str:
    """Browser URL path for a report file under Streamlit static serving.

    Optional ``tickers`` / ``preset`` become query params so in-report JS can
    filter (``?tickers=AAPL,MSFT&preset=xlk_tech``).
    """
    name = Path(filename).name
    url = f"{_STATIC_URL_PREFIX}/{name}"
    params: dict[str, str] = {}
    if tickers is not None:
        if isinstance(tickers, str):
            cleaned = [
                part.strip().upper()
                for part in tickers.split(",")
                if part.strip()
            ]
        else:
            cleaned = [
                str(ticker).strip().upper()
                for ticker in tickers
                if str(ticker).strip()
            ]
        if cleaned:
            params["tickers"] = ",".join(cleaned)
    if preset and str(preset).strip():
        params["preset"] = str(preset).strip()
    if not params:
        return url
    # Keep tickers commas unescaped for readability / JS split.
    if "tickers" in params and len(params) == 1:
        return f"{url}?tickers={quote(params['tickers'], safe=',')}"
    if "tickers" in params:
        tickers_q = quote(params["tickers"], safe=",")
        rest = {k: v for k, v in params.items() if k != "tickers"}
        return f"{url}?tickers={tickers_q}&{urlencode(rest)}"
    return f"{url}?{urlencode(params)}"
