"""Claims Desk page (Streamlit multipage).

Multi-quarter promise and goal trees, 2-axis call scorecard, and management
transparency. NVIDIA gold book. Shared Roz sector / custom-list filter.
"""
from __future__ import annotations

from services.earnings_monitor.dashboard.claims_scorecard import render_scorecard
from services.earnings_monitor.dashboard.claims_trees import render_claims_trees
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
    configure_page(st, page_title="Claims Desk")
    st.title("Claims Desk")
    st.caption(
        "Multi-quarter promise and goal trees. Sector, custom list, and the "
        "Companies picker scope every book — rates follow the visible trees."
    )

    ctx = load_dashboard_shell(st)
    if ctx is None:
        return

    render_research_status_sidebar(st, ctx.data)
    render_page_key(st, "claims_desk")
    render_claims_trees(
        st,
        ctx.data,
        sector_tickers=ctx.sector_tickers,
        sector_choice=ctx.sector_choice,
    )

    # ── Call Scorecard (2-axis: delivery vs engagement) ───────────────────────
    st.divider()
    render_scorecard(st, sector_tickers=list(ctx.sector_tickers or []) or None)

    # ── Management Transparency ────────────────────────────────────────────────
    st.divider()
    render_claims_regimes(
        st,
        ctx.data,
        sector_tickers=ctx.sector_tickers,
        sector_choice=ctx.sector_choice,
    )


main()
