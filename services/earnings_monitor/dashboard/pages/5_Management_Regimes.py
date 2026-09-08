"""Management Regimes page (Streamlit multipage).

CEO tenure tracking, regime comparisons, and cite-transfer ledger.
Shared Roz sector / custom-list filter.
"""
from __future__ import annotations

from services.earnings_monitor.dashboard.claims_regimes import render_claims_regimes
from services.earnings_monitor.dashboard.metric_keys import render_page_key
from services.earnings_monitor.dashboard.shell import (
    configure_page,
    get_streamlit,
    load_dashboard_shell,
    render_research_status_sidebar,
)


def main() -> None:
    st = get_streamlit()
    configure_page(st, page_title="Management Regimes")
    st.title("Management Regimes")
    st.caption(
        "CEO tenure tracking and accountability attribution. "
        "Trees are attributed to the regime under which they were seeded. "
        "The Transfer Ledger shows promises that crossed a CEO transition."
    )

    ctx = load_dashboard_shell(st)
    if ctx is None:
        return

    render_research_status_sidebar(st, ctx.data)
    render_page_key(st, "regimes")
    render_claims_regimes(
        st,
        ctx.data,
        sector_tickers=ctx.sector_tickers,
        sector_choice=ctx.sector_choice,
    )


main()
