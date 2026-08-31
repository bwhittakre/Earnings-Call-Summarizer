"""Read-only Claims Desk page. Locked 17 Aug book. No new LLM."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.earnings_monitor.dashboard.company_labels import format_company_label
from services.earnings_monitor.dashboard.data import DashboardData

# Keep these local. Do not import scripts._desk_claims_v1 or rank_ic_lab —
# those modules pull Lab / Path ID code that is not in the running image.
PROMISE_TYPES = ("forward_clock", "pending_close")
_LOCKED_STAMP = "2026-08-17T17:28:40+00:00"
_CLAIMS_FILENAME = "desk_claims_v1.json"


def load_desk_claims_v1(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read the typed claims desk. Refuse a mismatched stamp."""
    raw = history_source or os.environ.get(
        "EARNINGS_MONITOR_HISTORY_SOURCE",
        "Structured Narrative/output",
    )
    root = Path(raw)
    if root.name == "cross_company":
        cross_company = root
    elif root.name == "output" or (root / "cross_company").is_dir():
        cross_company = root / "cross_company"
    else:
        cross_company = root / "output" / "cross_company"
    path = cross_company / "json" / _CLAIMS_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("generated_at") or "") != _LOCKED_STAMP:
        return None
    return payload

_FY_RE = re.compile(r"^FY(\d{4})-Q([1-4])$")
_BACKDROP_PAD = 2


def fiscal_key(fiscal: str) -> tuple[int, int]:
    match = _FY_RE.fullmatch(str(fiscal or "").strip().upper())
    if not match:
        return (-1, -1)
    return (int(match.group(1)), int(match.group(2)))


def clock_is_due(clock: str | None, fiscal_period: str) -> bool:
    if not clock:
        return False
    clock_key = fiscal_key(clock)
    here = fiscal_key(fiscal_period)
    if clock_key[0] < 0 or here[0] < 0:
        return False
    return here >= clock_key


def shift_fiscal(fiscal: str, delta: int) -> str | None:
    year, quarter = fiscal_key(fiscal)
    if year < 0:
        return None
    index = year * 4 + (quarter - 1) + int(delta)
    if index < 0:
        return None
    new_year, new_q0 = divmod(index, 4)
    return f"FY{new_year}-Q{new_q0 + 1}"


def history_backdrop_window(
    history: Sequence[Mapping[str, Any]],
    seed_fiscal: str,
    follow_up_fiscal: str | None,
    *,
    pad: int = _BACKDROP_PAD,
) -> list[dict[str, Any]]:
    """Company-history slice around the seed, plus follow-up when it exists."""
    start = shift_fiscal(seed_fiscal, -pad)
    end = shift_fiscal(follow_up_fiscal, pad) if follow_up_fiscal else None
    start_key = fiscal_key(start) if start else (-1, -1)
    end_key = fiscal_key(end) if end else None
    seed = str(seed_fiscal or "").strip().upper()
    follow = str(follow_up_fiscal or "").strip().upper()
    window: list[dict[str, Any]] = []
    for row in history:
        period = str(row.get("fiscal_period") or "").strip().upper()
        key = fiscal_key(period)
        if key[0] < 0:
            continue
        if start and key < start_key:
            continue
        if end_key is not None and key > end_key:
            continue
        if period == seed:
            role = "seed"
        elif follow and period == follow:
            role = "follow-up"
        else:
            role = ""
        window.append(
            {
                "fiscal_period": period,
                "narrative_level": row.get("narrative_level"),
                "narrative_change": row.get("narrative_change"),
                "quant_z": row.get("quant_z"),
                "surprise_quant_gap": row.get("narrative_quant_gap"),
                "highlight": bool(role),
                "role": role,
            }
        )
    return window


def same_beat_trail(
    rows: Sequence[Mapping[str, Any]],
    beat_id: str,
    exclude_key: str,
) -> list[dict[str, str]]:
    want = str(beat_id or "")
    skip = str(exclude_key or "").strip()
    trail: list[dict[str, str]] = []
    for row in rows:
        if str(row.get("beat_id") or "") != want:
            continue
        name = f"{row.get('ticker') or ''} {row.get('period') or ''}".strip()
        if not name or name == skip:
            continue
        trail.append(
            {
                "name": name,
                "state": str(row.get("state") or ""),
                "delivery": str(row.get("delivery") or ""),
            }
        )
    return trail


def format_deliver_rate(rate: object) -> str:
    if rate is None:
        return "—"
    try:
        number = float(rate)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.0%}"


def promise_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("claim_type") or "") in PROMISE_TYPES
    ]


def kept_printed_facts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if row.get("state") == "kept"
        and str(row.get("claim_type") or "") not in PROMISE_TYPES
    ]


def filter_rows_to_universe(
    rows: Sequence[Mapping[str, Any]],
    universe: Sequence[str] | None,
) -> list[dict[str, Any]]:
    if universe is None:
        return [dict(row) for row in rows]
    allowed = {str(ticker).upper() for ticker in universe}
    return [
        dict(row)
        for row in rows
        if str(row.get("ticker") or "").upper() in allowed
    ]


def _row_key(row: Mapping[str, Any]) -> str:
    return f"{row.get('ticker') or ''} {row.get('period') or ''}".strip()


def _is_flex_bar(row: Mapping[str, Any]) -> bool:
    return str(row.get("ticker") or "") == "ADSK" and str(row.get("period") or "") == "2021-Q2"


def render_claims_desk(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    payload = load_desk_claims_v1()
    if payload is None:
        st.info("Claims desk v1 is missing or the stamp does not match the locked 17 Aug book.")
        return
    universe = None
    if sector_tickers is not None:
        universe = [str(ticker).upper() for ticker in sector_tickers]
    rows = filter_rows_to_universe(list(payload.get("rows") or []), universe)
    if not rows:
        st.info("No claims-desk names in the current Roz universe filter.")
        return

    rates = payload.get("deliver_rates") or {}
    book = rates.get("book") or {}
    st.caption(str(payload.get("caption") or ""))
    st.caption(
        f"Stamp {payload.get('generated_at')} · {payload.get('split')} · "
        f"kept is not delivered. Sector filter {sector_choice or 'all'}."
    )
    st.subheader("Deliver rate")
    st.caption(
        "Scored promises only: delivered / (delivered + missed). "
        "Unresolved clocks and printed facts are excluded."
    )
    n_scoreable = int(book.get("n_scoreable") or 0)
    st.metric(
        "Book deliver rate",
        format_deliver_rate(book.get("deliver_rate")),
    )
    st.caption(f"{book.get('delivered', 0)} delivered / {n_scoreable} scored")
    ticker_rates = [
        item
        for item in (rates.get("by_ticker") or [])
        if universe is None or str(item.get("ticker") or "").upper() in set(universe)
    ]
    if ticker_rates:
        st.dataframe(
            [
                {
                    "company": format_company_label(str(item.get("ticker") or "")),
                    "delivered": item.get("delivered"),
                    "missed": item.get("missed"),
                    "n_scoreable": item.get("n_scoreable"),
                    "deliver_rate": format_deliver_rate(item.get("deliver_rate")),
                }
                for item in ticker_rates
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Promises")
    st.caption("Forward clocks and pending closes. Flex launch is the bar.")
    for row in promise_rows(rows):
        title = (
            f"{format_company_label(str(row.get('ticker') or ''))} "
            f"{row.get('period')} · {row.get('beat_id')} · "
            f"{row.get('state')} / {row.get('delivery')}"
        )
        with st.expander(title, expanded=_is_flex_bar(row)):
            st.caption(
                f"{row.get('claim_type')} · {row.get('citation') or ''}"
            )
            st.write(row.get("excerpt"))
            follow = row.get("follow_up_excerpt")
            if follow:
                st.caption(str(row.get("follow_up_citation") or ""))
                st.write(follow)
            elif row.get("state") == "open":
                st.info("Still open. No next-quarter cite on this object.")
            else:
                st.info("No follow-up cite on this object.")
            if row.get("coverage_summary"):
                st.markdown(f"**Coverage.** {row.get('coverage_summary')}")
            if row.get("delivery_basis"):
                st.caption(str(row.get("delivery_basis")))
            backdrop = history_backdrop_window(
                data.company_history(str(row.get("ticker") or "")),
                str(row.get("fiscal_period") or ""),
                str(row.get("next_fiscal_period") or "") or None,
            )
            if backdrop:
                st.caption("Historical backdrop — Roz company history around this clock.")
                st.dataframe(
                    [
                        {
                            "fiscal_period": item["fiscal_period"],
                            "role": item["role"] or "—",
                            "narrative_level": item["narrative_level"],
                            "narrative_change": item["narrative_change"],
                            "quant_z": item["quant_z"],
                            "surprise_quant_gap": item["surprise_quant_gap"],
                        }
                        for item in backdrop
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            trail = same_beat_trail(rows, str(row.get("beat_id") or ""), _row_key(row))
            if trail:
                st.caption("Same-beat trail on this desk — not the remaining 125.")
                st.dataframe(trail, hide_index=True, use_container_width=True)

    printed = kept_printed_facts(rows)
    if not printed:
        return
    st.subheader("Kept printed facts")
    st.caption("Object came back. These are not promises and do not enter deliver rate.")
    st.dataframe(
        [
            {
                "name": _row_key(row),
                "beat": row.get("beat_id"),
                "coverage": row.get("coverage_summary"),
                "cite": row.get("excerpt"),
                "follow_up": row.get("follow_up_excerpt"),
            }
            for row in printed
        ],
        hide_index=True,
        use_container_width=True,
    )
