"""Shared Streamlit shell: dataset load + sector/custom-list universe sidebar."""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.earnings_monitor.dashboard.company_labels import format_company_label
from services.earnings_monitor.dashboard.data import (
    DashboardData,
    default_dataset_path,
    load_dashboard_data,
)
from services.earnings_monitor.dashboard.quartr_watchlists import (
    sync_is_fresh,
    sync_quartr_watchlists,
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
    CUSTOM_LIST,
    list_sector_options,
    resolve_active_universe,
    sector_option_label,
)

# Shared session keys so Roz and Rank IC Research use one universe filter.
SECTOR_KEY = "roz_sector"
CUSTOM_TICKERS_KEY = "roz_custom_tickers"


@dataclass(frozen=True)
class ShellContext:
    st: Any
    data: DashboardData
    dataset_path: Path
    sector_choice: str
    sector_tickers: list[str]


def get_streamlit() -> Any:
    """Import Streamlit only when the UI is actually started."""
    try:
        return importlib.import_module("streamlit")
    except ImportError as exc:
        raise RuntimeError(
            "The dashboard requires Streamlit. Install it in the dashboard runtime "
            "or import dashboard.data for headless use."
        ) from exc


def configure_page(
    st: Any,
    *,
    page_title: str,
    layout: str = "wide",
) -> None:
    st.set_page_config(page_title=page_title, layout=layout)


def load_dashboard_shell(
    st: Any,
    *,
    data: DashboardData | None = None,
    dataset_path: str | os.PathLike[str] | None = None,
) -> ShellContext | None:
    """Load dataset and ensure static report links. Returns None on load failure."""
    selected_path = Path(dataset_path or default_dataset_path())
    if data is None:
        try:
            data = load_dashboard_data(selected_path)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            st.error(f"Unable to load dataset: {exc}")
            st.caption(
                "Set EARNINGS_MONITOR_DATASET or run the historical importer first."
            )
            return None

    ensure_reports_static_link()
    st.sidebar.caption(f"Dataset: {selected_path}")
    st.sidebar.caption(
        f"{len(data.rows):,} records · {len(data.tickers)} companies"
    )
    sector_choice, sector_tickers = render_universe_sidebar(st, data)
    return ShellContext(
        st=st,
        data=data,
        dataset_path=selected_path,
        sector_choice=sector_choice,
        sector_tickers=list(sector_tickers),
    )


def render_universe_sidebar(st: Any, data: DashboardData) -> tuple[str, list[str]]:
    """Sector / custom list filter shared by Roz and Rank IC Research."""
    sector_options = list_sector_options()
    default_sector = (
        "xlk_tech" if "xlk_tech" in sector_options else sector_options[0]
    )
    sector_choice = st.sidebar.selectbox(
        "Sector",
        sector_options,
        index=sector_options.index(default_sector),
        format_func=sector_option_label,
        key=SECTOR_KEY,
    )
    custom_tickers: list[str] = []
    if sector_choice == CUSTOM_LIST:
        custom_tickers = list(
            st.sidebar.multiselect(
                "Custom list companies",
                options=list(data.tickers),
                default=list(st.session_state.get(CUSTOM_TICKERS_KEY) or []),
                format_func=format_company_label,
                key=CUSTOM_TICKERS_KEY,
            )
        )
        if not custom_tickers:
            st.sidebar.info("Select one or more companies for the custom list.")
    sector_tickers = resolve_active_universe(
        sector_choice,
        data.tickers,
        custom_tickers=custom_tickers,
    )
    st.sidebar.caption(
        f"Filter: {sector_option_label(sector_choice)} · "
        f"{len(sector_tickers)} companies"
    )
    st.sidebar.caption(
        "Roz, Rank IC Research, and Rank IC Lab share this company filter."
    )
    return sector_choice, list(sector_tickers)


def render_quartr_sidebar(st: Any, data: DashboardData) -> None:
    """Quartr watchlist sync controls (Roz page)."""
    repo_root = Path(__file__).resolve().parents[3]
    if not sync_is_fresh():
        try:
            auto = sync_quartr_watchlists(
                repo_root=repo_root,
                available_tickers=data.tickers,
                micro_onboard=False,
                force=False,
            )
            if auto.error:
                st.sidebar.caption(f"Quartr watchlists: {auto.error}")
            elif not auto.from_cache:
                st.sidebar.caption(
                    f"Quartr watchlists synced ({auto.watchlists} lists)."
                )
        except Exception as exc:  # noqa: BLE001
            st.sidebar.caption(f"Quartr watchlists: {exc}")

    if st.sidebar.button("Refresh Quartr watchlists", key="roz_quartr_refresh"):
        with st.spinner("Syncing Quartr watchlists (may micro-onboard new names)…"):
            refreshed = sync_quartr_watchlists(
                repo_root=repo_root,
                available_tickers=data.tickers,
                micro_onboard=True,
                max_micro_onboards=5,
                force=True,
            )
        if refreshed.error:
            st.sidebar.error(refreshed.error)
        else:
            st.sidebar.success(
                f"{refreshed.watchlists} lists · "
                f"{len(refreshed.micro_onboarded)} micro-onboarded · "
                f"{len(refreshed.pending_transcript)} pending transcript"
            )
            if refreshed.micro_onboarded:
                st.sidebar.caption(
                    "Deepen history later via full Onboard for: "
                    + ", ".join(refreshed.micro_onboarded)
                )
            st.rerun()


def render_research_status_sidebar(st: Any, data: DashboardData) -> None:
    """Rank IC / consolidated artifact freshness + dirty-book warnings."""
    rank_html = resolve_rank_ic_html()
    consolidated_html = resolve_consolidated_html()
    rank_meta = html_report_meta(rank_html)
    consol_meta = html_report_meta(consolidated_html)
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
