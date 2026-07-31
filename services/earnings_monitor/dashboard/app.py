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

    st.sidebar.caption(f"Dataset: {selected_path}")
    st.sidebar.caption(
        f"{len(data.rows):,} records · {len(data.tickers)} companies"
    )
    view_name = st.sidebar.radio("View", list(VIEWS))
    VIEWS[view_name](st, data)


def main() -> None:
    render_app()


if __name__ == "__main__":
    main()
