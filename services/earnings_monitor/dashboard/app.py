"""Streamlit entry point for the consolidated earnings monitor.

Run with:
    streamlit run services/earnings_monitor/dashboard/app.py
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

from services.earnings_monitor.dashboard.data import (
    DashboardData,
    default_dataset_path,
    load_dashboard_data,
)
from services.earnings_monitor.dashboard.report_static import ensure_reports_static_link
from services.earnings_monitor.dashboard.research_data import (
    artifact_universe_status,
    format_universe_stale_message,
    html_report_meta,
    load_consolidated_panel,
    load_rank_ic_bundle,
    load_research_book_dirty,
    resolve_consolidated_html,
    resolve_rank_ic_html,
)
from services.earnings_monitor.dashboard.sectors import (
    list_sector_options,
    resolve_sector_tickers,
)
from services.earnings_monitor.dashboard.views import VIEWS


def get_streamlit() -> Any:
    """Import Streamlit only when the UI is actually started."""
    try:
        return importlib.import_module("streamlit")
    except ImportError as exc:
        raise RuntimeError(
            "The dashboard requires Streamlit. Install it in the dashboard runtime "
            "or import dashboard.data for headless use."
        ) from exc


def render_app(
    *,
    st: Any | None = None,
    data: DashboardData | None = None,
    dataset_path: str | os.PathLike[str] | None = None,
) -> None:
    """Render the app with injectable UI/data dependencies for tests."""
    st = st or get_streamlit()
    st.set_page_config(page_title="Roz", layout="wide")
    st.title("Roz")
    st.caption("Earnings intelligence: live pipeline state and historical scoring")

    selected_path = Path(dataset_path or default_dataset_path())
    if data is None:
        try:
            data = load_dashboard_data(selected_path)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            st.error(f"Unable to load dataset: {exc}")
            st.caption(
                "Set EARNINGS_MONITOR_DATASET or run the historical importer first."
            )
            return

    # Symlink history reports into cwd/static for large HTML iframes.
    ensure_reports_static_link()

    st.sidebar.caption(f"Dataset: {selected_path}")
    st.sidebar.caption(
        f"{len(data.rows):,} records · {len(data.tickers)} companies"
    )

    sector_options = list_sector_options()
    default_sector = (
        "xlk_tech" if "xlk_tech" in sector_options else sector_options[0]
    )
    sector_choice = st.sidebar.selectbox(
        "Sector",
        sector_options,
        index=sector_options.index(default_sector),
        key="roz_sector",
    )
    sector_tickers = resolve_sector_tickers(sector_choice, data.tickers)
    st.sidebar.caption(
        f"Sector filter: {sector_choice} · {len(sector_tickers)} companies"
    )

    rank_html = resolve_rank_ic_html()
    consolidated_html = resolve_consolidated_html()
    rank_meta = html_report_meta(rank_html)
    consol_meta = html_report_meta(consolidated_html)
    # Keep CSV provenance captions as a secondary freshness signal.
    rank_ic = load_rank_ic_bundle()
    consolidated = load_consolidated_panel()
    if rank_html is not None:
        st.sidebar.caption(
            f"Rank IC HTML: {rank_meta.get('generated_at') or 'available'}"
        )
    elif rank_ic.available:
        st.sidebar.caption(
            f"Rank IC CSV: {rank_ic.meta.get('generated_at') or 'available'} · "
            f"HTML missing"
        )
    else:
        st.sidebar.caption("Rank IC: not loaded")
    if consolidated_html is not None:
        st.sidebar.caption(
            f"Consolidated HTML: {consol_meta.get('stem') or 'available'} · "
            f"{consol_meta.get('generated_at') or '—'}"
        )
    elif consolidated.available:
        st.sidebar.caption(
            f"Consolidated CSV: {consolidated.meta.get('generated_at') or 'available'} · "
            f"HTML missing/too large"
        )
    else:
        st.sidebar.caption("Consolidated: not loaded")

    universe_status = artifact_universe_status(
        data.tickers,
        rank_ic.meta if rank_ic.available else None,
        consolidated.meta if consolidated.available else None,
    )
    stale_msg = format_universe_stale_message(universe_status)
    if stale_msg:
        st.sidebar.warning(stale_msg)

    dirty = load_research_book_dirty()
    if dirty:
        triggers = dirty.get("triggers") or []
        trigger_txt = ", ".join(str(t) for t in triggers[-3:]) if triggers else "—"
        st.sidebar.warning(
            "Research book regen pending "
            f"(reason={dirty.get('reason') or '—'}; recent={trigger_txt}). "
            "Wait for the research-regen loop or run "
            "`python -m services.earnings_monitor research-regen --force`."
        )

    view_name = st.sidebar.radio("View", list(VIEWS))
    VIEWS[view_name](st, data, sector_tickers=sector_tickers)


def main() -> None:
    render_app()


if __name__ == "__main__":
    main()
