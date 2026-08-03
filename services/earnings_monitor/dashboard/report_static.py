"""Expose cross_company HTML reports via Streamlit static file serving."""

from __future__ import annotations

import os
from pathlib import Path

from .research_data import resolve_cross_company_root

# Streamlit serves ``<app_dir>/static`` when enableStaticServing is on.
# Confirmed URL shape (Streamlit 1.60): ``/app/static/<relative-path>``.
_STATIC_URL_PREFIX = "/app/static/reports"


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


def static_report_url(filename: str) -> str:
    """Browser URL path for a report file under Streamlit static serving."""
    name = Path(filename).name
    return f"{_STATIC_URL_PREFIX}/{name}"
