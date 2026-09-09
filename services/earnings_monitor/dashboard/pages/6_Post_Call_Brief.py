"""Post-Call Brief page (Streamlit multipage).

One-screen brief per (ticker, period) answering five questions in under 2 minutes:
  1. Did management deliver on what they promised?
  2. Are they strengthening or weakening forward commitments?
  3. What specific promises were resolved this call?
  4. What is still open, silently abandoned, or due soon?
  5. Who is management and what is their regime track record?
"""
from __future__ import annotations

from services.earnings_monitor.dashboard.claims_brief import (
    all_scored_periods,
    all_scored_tickers,
    generate_brief_markdown,
    load_brief_data,
    period_display_label,
    render_brief,
)
from services.earnings_monitor.dashboard.claims_scorecard import render_scorecard
from services.earnings_monitor.dashboard.metric_keys import render_page_key
from services.earnings_monitor.dashboard.shell import (
    configure_page,
    get_streamlit,
    load_dashboard_shell,
    render_research_status_sidebar,
)


def main() -> None:
    st = get_streamlit()
    configure_page(st, page_title="Post-Call Brief")
    st.title("Post-Call Brief")
    st.caption(
        "Claims desk + management regime signals for the 5-day window "
        "between an earnings call and consensus reactions."
    )

    ctx = load_dashboard_shell(st)
    if ctx is None:
        return

    render_research_status_sidebar(st, ctx.data)
    render_page_key(st, "post_call_brief")

    # ── Ticker + period pickers ───────────────────────────────────────────────
    tickers = all_scored_tickers()
    if not tickers:
        st.warning(
            "No scorecard entries found. "
            "Run `python scripts/_desk_call_scorecard.py` to generate them."
        )
        return

    sector_tickers = list(getattr(ctx, "sector_tickers", None) or [])
    sector_up = {str(t).upper() for t in sector_tickers}
    if sector_up:
        filtered = [t for t in tickers if t in sector_up]
        if filtered:
            tickers = filtered
    default_idx = 0

    col_ticker, col_period = st.columns(2)
    with col_ticker:
        ticker = st.selectbox("Ticker", tickers, index=default_idx, key="brief_ticker")

    periods = all_scored_periods(ticker)
    if not periods:
        st.info(f"No scored periods for {ticker} yet.")
        return

    with col_period:
        period = st.selectbox(
            "Call / period",
            periods,
            index=0,
            key="brief_period",
            format_func=lambda p: period_display_label(ticker, p),
        )

    # ── Load and render ───────────────────────────────────────────────────────
    try:
        # Pass DashboardData for narrative context if available
        dashboard_data = getattr(ctx, "data", None)
        brief = load_brief_data(ticker, period, dashboard_data=dashboard_data)
    except Exception as exc:
        st.error(f"Failed to load brief: {exc}")
        return

    if brief is None:
        st.info(f"No brief data for {ticker} {period}.")
        return

    render_brief(st, brief)

    # ── Download button ───────────────────────────────────────────────────────
    md_text = generate_brief_markdown(brief)
    st.download_button(
        label="Download brief (.md)",
        data=md_text.encode("utf-8"),
        file_name=f"{ticker}_{period.replace('-', '')}_brief.md",
        mime="text/markdown",
    )

    # ── Call Scorecard ────────────────────────────────────────────────────────
    with st.expander("Call Scorecard", expanded=False):
        render_scorecard(
            st,
            sector_tickers=list(ctx.sector_tickers or []) or None,
        )


main()
