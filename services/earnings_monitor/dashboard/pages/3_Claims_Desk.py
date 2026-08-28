"""Claims Desk page (Streamlit multipage).

Read-only locked 17 Aug book. Shared Roz sector / custom-list filter.
Not a Lab sandbox. production_v1 is never written.
"""
from __future__ import annotations

from services.earnings_monitor.dashboard.claims_desk import render_claims_desk
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
        "Typed promises with a follow-up cite. Company filter is shared with Roz — "
        "onboarded names appear here automatically."
    )

    ctx = load_dashboard_shell(st)
    if ctx is None:
        return

    render_research_status_sidebar(st, ctx.data)
    render_claims_desk(
        st,
        ctx.data,
        sector_tickers=ctx.sector_tickers,
        sector_choice=ctx.sector_choice,
    )


main()
