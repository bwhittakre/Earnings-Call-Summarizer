"""Claims Trees page (Streamlit multipage).

NVIDIA gold book. Shared Roz sector / custom-list filter.
Does not rewrite the locked v1 Claims Desk page.
"""
from __future__ import annotations

from services.earnings_monitor.dashboard.claims_trees import render_claims_trees
from services.earnings_monitor.dashboard.shell import (
    configure_page,
    get_streamlit,
    load_dashboard_shell,
    render_research_status_sidebar,
)


def main() -> None:
    st = get_streamlit()
    configure_page(st, page_title="Claims Trees")
    st.title("Claims Trees")
    st.caption(
        "Multi-quarter promise and goal trees. Company filter is shared with Roz — "
        "the NVIDIA gold book is selectable without retuning xlk_tech."
    )

    ctx = load_dashboard_shell(st)
    if ctx is None:
        return

    render_research_status_sidebar(st, ctx.data)
    render_claims_trees(
        st,
        ctx.data,
        sector_tickers=ctx.sector_tickers,
        sector_choice=ctx.sector_choice,
    )


main()
