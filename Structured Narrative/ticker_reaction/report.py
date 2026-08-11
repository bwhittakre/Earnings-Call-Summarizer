"""Write typed Output artifacts: Reports HTML, Tables CSV, Diagnostics JSON."""

from __future__ import annotations

import html
import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from ticker_reaction.align import AlignedUtterance
from ticker_reaction.highlights import (
    HORIZON_MINUTES,
    HORIZONS,
    numbers_by_horizon,
)
from ticker_reaction.paths import (
    diagnostics_json_path,
    reactions_csv_path,
    reports_html_path,
)
from ticker_reaction.reactions import (
    ReactionRow,
    forward_return_anchors,
    reactions_to_frame,
    resolve_highlight_placement,
)
from ticker_reaction.speech_turns import trigger_preview

ET = ZoneInfo("America/New_York")

# Chart focus pads around report / call end (context chart).
PRE_REPORT_PAD = timedelta(minutes=15)
POST_CALL_PAD = timedelta(minutes=20)
# Call chart only: show a few minutes of tape after call end (overrunning speech).
CALL_CHART_POST_PAD = timedelta(minutes=5)


def _fmt_pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and (x != x)):  # NaN
        return "—"
    return f"{100.0 * float(x):+.2f}%"


def _parse_ts(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _fmt_et_clock(ts: pd.Timestamp | None, *, with_seconds: bool = False) -> str:
    """Format ET wall clock in 24-hour (military) time."""
    if ts is None:
        return "—"
    local = ts.tz_convert(ET)
    return local.strftime("%H:%M:%S" if with_seconds else "%H:%M")


def _fmt_et_tick(ts: pd.Timestamp) -> str:
    return _fmt_et_clock(ts, with_seconds=False)


def _nice_price_ticks(y_min: float, y_max: float, target: int = 5) -> list[float]:
    """Evenly spaced nice round price levels for gridlines."""
    if not math.isfinite(y_min) or not math.isfinite(y_max):
        return [0.0]
    if y_max <= y_min:
        return [float(y_min)]
    span = y_max - y_min
    raw = span / max(target - 1, 1)
    exp = math.floor(math.log10(raw)) if raw > 0 else 0
    mag = 10**exp
    step = mag
    for mult in (1.0, 2.0, 2.5, 5.0, 10.0):
        candidate = mult * mag
        if span / candidate <= target + 1:
            step = candidate
            break
    start = math.floor(y_min / step) * step
    ticks: list[float] = []
    v = start
    # Guard against float drift.
    for _ in range(50):
        if v >= y_min - step * 1e-9 and v <= y_max + step * 1e-9:
            ticks.append(round(v, 10))
        v += step
        if v > y_max + step:
            break
    return ticks or [float(y_min), float(y_max)]


def _ret_direction(value: float | None) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "na"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def compute_focus_window(
    bars: pd.DataFrame,
    *,
    report_at: pd.Timestamp | None,
    call_at: pd.Timestamp | None,
    call_end: pd.Timestamp | None,
    pre_report_pad: timedelta = PRE_REPORT_PAD,
    post_call_pad: timedelta = POST_CALL_PAD,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return (view_start, view_end) clamped to available bars when possible."""
    ts = pd.to_datetime(bars["ts_utc"], utc=True)
    bar_start = ts.min()
    bar_end = ts.max()

    anchor_start = report_at or call_at or bar_start
    anchor_end = call_end or call_at or report_at or bar_end

    view_start = anchor_start - pre_report_pad
    view_end = anchor_end + post_call_pad

    if pd.notna(bar_start) and view_start < bar_start:
        view_start = bar_start
    if pd.notna(bar_end) and view_end > bar_end:
        view_end = bar_end
    if view_end <= view_start:
        view_start, view_end = bar_start, bar_end
    return pd.Timestamp(view_start), pd.Timestamp(view_end)


def compute_call_window(
    bars: pd.DataFrame,
    *,
    call_at: pd.Timestamp | None,
    call_end: pd.Timestamp | None,
    post_call_pad: timedelta = CALL_CHART_POST_PAD,
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Call chart window: call start → call end + pad, clamped to bars.

    The pad keeps post-call tape (and any speech that slightly overruns) visible;
    highlight selection is unchanged.
    """
    if call_at is None:
        return None
    ts = pd.to_datetime(bars["ts_utc"], utc=True)
    bar_start = ts.min()
    bar_end = ts.max()
    end = (call_end or call_at) + post_call_pad
    view_start = max(call_at, bar_start) if pd.notna(bar_start) else call_at
    view_end = min(end, bar_end) if pd.notna(bar_end) else end
    if view_end <= view_start:
        return None
    return pd.Timestamp(view_start), pd.Timestamp(view_end)


def _nearest_close(ts: pd.Series, closes: pd.Series, t: pd.Timestamp) -> float | None:
    if len(ts) == 0:
        return None
    pos = int(ts.searchsorted(t, side="right") - 1)
    if pos < 0:
        pos = 0
    if pos >= len(ts):
        pos = len(ts) - 1
    val = float(closes.iloc[pos])
    return val if pd.notna(val) else None


def _svg_timeline(
    bars: pd.DataFrame,
    aligned: list[AlignedUtterance],
    *,
    view_start: pd.Timestamp,
    view_end: pd.Timestamp,
    nums_by_horizon: dict[str, dict[int, int]],
    report_at_iso: str | None = None,
    call_at_iso: str | None = None,
    call_end_iso: str | None = None,
    qa_start_iso: str | None = None,
    call_at: pd.Timestamp | None = None,
    ret_from_call_by_index: dict[int, float | None] | None = None,
    mode: str = "context",
    width: int = 1040,
    height: int = 440,
    legend: str = "",
    chart_id: str = "chart",
) -> str:
    if bars.empty:
        return "<p><em>No bar data to plot.</em></p>"

    ts_all = pd.to_datetime(bars["ts_utc"], utc=True)
    closes_all = pd.to_numeric(bars["close"], errors="coerce")
    ok = closes_all.notna()
    ts_all = ts_all[ok].reset_index(drop=True)
    closes_all = closes_all[ok].reset_index(drop=True)
    if len(ts_all) < 2:
        return "<p><em>Insufficient bars to plot.</em></p>"

    in_view = (ts_all >= view_start) & (ts_all <= view_end)
    ts = ts_all[in_view].reset_index(drop=True)
    closes = closes_all[in_view].reset_index(drop=True)
    if len(ts) < 2:
        return "<p><em>Insufficient bars in this window.</em></p>"

    t0 = int(view_start.value)
    t1 = int(view_end.value)
    span = max(t1 - t0, 1)
    raw_min = float(closes.min())
    raw_max = float(closes.max())
    # Pad slightly, then snap axis to nice round ticks so gridlines are even.
    pad = max(raw_max - raw_min, 1e-9) * 0.04
    tick_prices = _nice_price_ticks(raw_min - pad, raw_max + pad, target=5)
    y_min = float(tick_prices[0])
    y_max = float(tick_prices[-1])
    if y_max <= y_min:
        y_max = y_min + 1.0
        tick_prices = [y_min, y_max]
    y_span = y_max - y_min

    pad_l, pad_r, pad_t, pad_b = 72, 24, 36, 64
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def x_of(tval: int) -> float:
        return pad_l + plot_w * ((tval - t0) / span)

    def y_of(price: float) -> float:
        return pad_t + plot_h * (1.0 - (price - y_min) / y_span)

    # Event timing is shown only via Report / Call / Call-end dashed lines (no phase bands).

    points = " ".join(
        f"{x_of(int(t.value)):.2f},{y_of(float(p)):.2f}" for t, p in zip(ts, closes)
    )

    ordered = sorted(aligned, key=lambda u: (u.utterance_utc, u.index))
    light_ticks = []
    # One SVG layer per horizon; JS toggles visibility with the view buttons.
    layer_parts: dict[str, list[str]] = {h: [] for h in HORIZONS}
    any_selected = set()
    for h in HORIZONS:
        any_selected |= set((nums_by_horizon.get(h) or {}).keys())

    for u in ordered:
        ut = pd.Timestamp(u.utterance_utc)
        if ut.tzinfo is None:
            ut = ut.tz_localize("UTC")
        else:
            ut = ut.tz_convert("UTC")
        if ut.value < t0 or ut.value > t1:
            continue
        x = x_of(int(ut.value))
        et_clock = _fmt_et_clock(ut, with_seconds=False)
        snippet = " ".join((u.text or "").split())[:120]

        # Context chart only: light utterance ticks. Call chart uses even minute grid instead.
        if mode == "context":
            tick_title = html.escape(f"· · {u.speaker} · {et_clock} · {snippet}")
            light_ticks.append(
                f'<line x1="{x:.2f}" y1="{pad_t}" x2="{x:.2f}" y2="{pad_t + plot_h}" '
                f'stroke="#cbd5e1" stroke-width="1" opacity="0.45">'
                f"<title>{tick_title}</title></line>"
            )

        if u.index not in any_selected:
            continue

        ret_from_call = (ret_from_call_by_index or {}).get(u.index)
        fallback_close = u.bar_close
        if fallback_close is None:
            fallback_close = _nearest_close(ts, closes, ut)
        placement = resolve_highlight_placement(
            bars,
            call_at=call_at,
            utterance_utc=ut,
            ret_from_call_start=ret_from_call,
            fallback_close=fallback_close,
        )
        # Stem meets the blue line on the defining 1m bar vertex.
        place_ts = placement.bar_ts
        if place_ts.tzinfo is None:
            place_ts = place_ts.tz_localize("UTC")
        else:
            place_ts = place_ts.tz_convert("UTC")
        utt_clock = _fmt_et_clock(ut, with_seconds=True)
        tape_clock = _fmt_et_clock(place_ts, with_seconds=False)
        pct_label = (
            f"{placement.matched_pct:+.1f}% from call start"
            if placement.matched_pct is not None
            else "% from call start unavailable"
        )

        for h in HORIZONS:
            hi_num = (nums_by_horizon.get(h) or {}).get(u.index)
            if hi_num is None:
                continue
            minutes = HORIZON_MINUTES[h]
            title = html.escape(
                f"#{hi_num} · ret_{h} · {u.speaker} · uttered {utt_clock} · "
                f"tape @ {tape_clock} · {pct_label} · {snippet}"
            )
            end_title = html.escape(
                f"#{hi_num} · ret_{h} end (+{minutes}m later) · {u.speaker}"
            )
            c0, c1, _ts0, ts1 = forward_return_anchors(
                bars, place_ts.to_pydatetime(), minutes
            )
            price = placement.bar_close
            if price is None or not math.isfinite(float(price)):
                price = c0
            if price is None or not math.isfinite(float(price)):
                price = fallback_close
            if price is None or not math.isfinite(float(price)):
                continue
            x = x_of(int(place_ts.value))
            y = y_of(float(price))
            # Number bubble floats off the path; intersection is the bar vertex.
            stem_top = max(pad_t + 8, y - 36)

            move_seg = ""
            if c0 is not None and c1 is not None and ts1 is not None:
                end_t = pd.Timestamp(ts1)
                if end_t.tzinfo is None:
                    end_t = end_t.tz_localize("UTC")
                else:
                    end_t = end_t.tz_convert("UTC")
                x_end = x_of(int(end_t.value))
                x_end = min(max(x_end, pad_l), width - pad_r)
                y_end = y_of(float(c1))
                move_seg = (
                    f'<line class="hi-seg" x1="{x:.2f}" y1="{y:.2f}" x2="{x_end:.2f}" y2="{y_end:.2f}" '
                    f'stroke="#c45c26" stroke-width="2" opacity="0.75"/>'
                    f'<circle class="hi-end" cx="{x_end:.2f}" cy="{y_end:.2f}" r="3.5" fill="#c45c26" opacity="0.85">'
                    f"<title>{end_title}</title></circle>"
                )

            # Clickable marker group (multi-select syncs with table via data-utt-index).
            layer_parts[h].append(
                f'<g class="hi-mark" data-utt-index="{u.index}" data-horizon="{h}" '
                f'style="cursor:pointer">'
                f"{move_seg}"
                f'<circle class="hi-anchor" cx="{x:.2f}" cy="{y:.2f}" r="3.5" '
                f'fill="#c45c26" stroke="#fff" stroke-width="1">'
                f"<title>{title}</title></circle>"
                f'<line class="hi-stem" x1="{x:.2f}" y1="{y:.2f}" x2="{x:.2f}" y2="{stem_top:.2f}" '
                f'stroke="#c45c26" stroke-width="1.5" opacity="0.9"/>'
                f'<circle class="hi-hit" cx="{x:.2f}" cy="{stem_top:.2f}" r="14" fill="transparent"/>'
                f'<circle class="hi-badge" cx="{x:.2f}" cy="{stem_top:.2f}" r="10" fill="#c45c26" stroke="#fff" stroke-width="1.5">'
                f"<title>{title}</title></circle>"
                f'<text class="hi-num" x="{x:.2f}" y="{stem_top + 3.5:.2f}" text-anchor="middle" '
                f'font-size="9" font-weight="700" fill="#fff" pointer-events="none">{hi_num}</text>'
                f"</g>"
            )

    highlight_layers = []
    for h in HORIZONS:
        display = "inline" if h == "1m" else "none"
        highlight_layers.append(
            f'<g class="horizon-layer" data-horizon="{h}" data-chart="{html.escape(chart_id)}" '
            f'style="display:{display}">{"".join(layer_parts[h])}</g>'
        )
    highlight_markers = highlight_layers

    def vline(iso: str | None, color: str, label: str) -> str:
        tv = _parse_ts(iso)
        if tv is None:
            return ""
        if tv.value < t0 or tv.value > t1:
            return ""
        x = x_of(int(tv.value))
        return (
            f'<line x1="{x:.2f}" y1="{pad_t}" x2="{x:.2f}" y2="{pad_t + plot_h}" '
            f'stroke="{color}" stroke-width="2" stroke-dasharray="6 4"/>'
            f'<text x="{x:.2f}" y="{pad_t - 10}" fill="{color}" font-size="11" '
            f'font-weight="600" text-anchor="middle">{html.escape(label)}</text>'
        )

    # Background grid
    minute_grid = []
    y_ticks = []
    if mode == "call":
        # Only even per-minute vertical lines as background (no horizontal price grid,
        # no uneven utterance ticks). Price labels remain on the Y axis.
        minute = pd.Timestamp(view_start).floor("min")
        end_ts = pd.Timestamp(view_end)
        while minute <= end_ts:
            x = x_of(int(minute.value))
            if pad_l <= x <= width - pad_r:
                minute_grid.append(
                    f'<line x1="{x:.2f}" y1="{pad_t}" x2="{x:.2f}" y2="{pad_t + plot_h}" '
                    f'stroke="#e2e8f0" stroke-width="1"/>'
                )
            minute = minute + pd.Timedelta(minutes=1)
        for price in tick_prices:
            y = y_of(price)
            label = f"{price:.2f}".rstrip("0").rstrip(".") if abs(price) >= 1 else f"{price:.2f}"
            y_ticks.append(
                f'<text x="{pad_l - 10}" y="{y + 4:.2f}" text-anchor="end" '
                f'font-size="11" fill="#555">{label}</text>'
            )
    else:
        for price in tick_prices:
            y = y_of(price)
            label = f"{price:.2f}".rstrip("0").rstrip(".") if abs(price) >= 1 else f"{price:.2f}"
            y_ticks.append(
                f'<line x1="{pad_l}" y1="{y:.2f}" x2="{width - pad_r}" y2="{y:.2f}" '
                f'stroke="#e2e8f0"/>'
                f'<text x="{pad_l - 10}" y="{y + 4:.2f}" text-anchor="end" '
                f'font-size="11" fill="#555">{label}</text>'
            )

    x_ticks = []
    if mode == "call":
        # Label every 5 minutes on the axis (grid itself is every 1 minute).
        minute = pd.Timestamp(view_start).floor("min")
        end_ts = pd.Timestamp(view_end)
        while minute <= end_ts:
            if int(minute.minute) % 5 == 0:
                x = x_of(int(minute.value))
                label = html.escape(_fmt_et_tick(minute))
                x_ticks.append(
                    f'<line x1="{x:.2f}" y1="{pad_t + plot_h}" x2="{x:.2f}" '
                    f'y2="{pad_t + plot_h + 6}" stroke="#94a3b8"/>'
                    f'<text x="{x:.2f}" y="{pad_t + plot_h + 20}" text-anchor="middle" '
                    f'font-size="11" fill="#555">{label}</text>'
                )
            minute = minute + pd.Timedelta(minutes=1)
    else:
        n_ticks = 6
        for i in range(n_ticks):
            frac = i / (n_ticks - 1)
            tval = t0 + int(span * frac)
            ts_tick = pd.Timestamp(tval, tz="UTC")
            x = x_of(tval)
            label = html.escape(_fmt_et_tick(ts_tick))
            x_ticks.append(
                f'<line x1="{x:.2f}" y1="{pad_t + plot_h}" x2="{x:.2f}" '
                f'y2="{pad_t + plot_h + 6}" stroke="#94a3b8"/>'
                f'<text x="{x:.2f}" y="{pad_t + plot_h + 20}" text-anchor="middle" '
                f'font-size="11" fill="#555">{label}</text>'
            )

    vlines = []
    if mode == "context":
        vlines.append(vline(report_at_iso, "#6b7280", "Report"))
        vlines.append(vline(call_at_iso, "#111827", "Call"))
        vlines.append(vline(call_end_iso, "#047857", "Call end"))
    else:
        vlines.append(vline(call_at_iso, "#111827", "Call start"))
        vlines.append(vline(qa_start_iso, "#7c3aed", "Q&A"))
        vlines.append(vline(call_end_iso, "#047857", "Call end"))

    if mode == "call":
        legend_text = legend or (
            "1-minute grid · stem on defining 1m bar · segment = N-min move"
        )
    else:
        legend_text = legend or (
            "Light ticks = utterances · stem on defining 1m bar · segment = N-min move"
        )
    y_title_y = pad_t + plot_h / 2
    return f"""
<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px;background:#fff;border:1px solid #e6e8eb;border-radius:6px;">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/>
  {''.join(minute_grid)}
  {''.join(y_ticks)}
  {''.join(x_ticks)}
  <polyline fill="none" stroke="#1f4b99" stroke-width="2.25" points="{points}"/>
  {''.join(light_ticks)}
  {''.join(highlight_markers)}
  {''.join(vlines)}
  <text transform="translate(16,{y_title_y}) rotate(-90)" text-anchor="middle"
        font-size="12" font-weight="600" fill="#334155">Price (USD)</text>
  <text x="{pad_l + plot_w / 2:.2f}" y="{height - 14}" text-anchor="middle"
        font-size="12" font-weight="600" fill="#334155">Time (ET)</text>
  <text x="{pad_l}" y="{height - 32}" font-size="11" fill="#64748b">{html.escape(legend_text)}</text>
</svg>
"""


def _ret_cell(value: float | None) -> str:
    text = _fmt_pct(value)
    if value is None or (isinstance(value, float) and value != value):
        return f"<td class='ret-null'>{text}</td>"
    cls = "ret-pos" if value > 0 else "ret-neg" if value < 0 else "ret-zero"
    return f"<td class='{cls}'>{text}</td>"


def _fmt_dpx(x: float | None) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return "—"
    return f"${float(x):+.2f}"


def _dpx_cell(value: float | None) -> str:
    text = _fmt_dpx(value)
    if value is None or (isinstance(value, float) and value != value):
        return f"<td class='col-dpx ret-null'>{text}</td>"
    cls = "ret-pos" if value > 0 else "ret-neg" if value < 0 else "ret-zero"
    return f"<td class='col-dpx {cls}'>{text}</td>"


def _num_cell(value: float | None, *, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "<td class='ret-null'>—</td>"
    return f"<td class='ret-zero'>{float(value):.{digits}f}</td>"


def _vol_cell(value: float | None) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "<td class='ret-null'>—</td>"
    return f"<td class='ret-zero'>{float(value):,.0f}</td>"


def _filter_script() -> str:
    return """
<script>
(function () {
  const table = document.getElementById('highlight-table');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const speaker = document.getElementById('filter-speaker');
  const section = document.getElementById('filter-section');
  const ret1 = document.getElementById('filter-ret1');
  const ret3 = document.getElementById('filter-ret3');
  const ret5 = document.getElementById('filter-ret5');
  const timeFrom = document.getElementById('filter-time-from');
  const timeTo = document.getElementById('filter-time-to');
  const countEl = document.getElementById('filter-count');
  const resetBtn = document.getElementById('filter-reset');
  const clearSelBtn = document.getElementById('clear-hi-selection');
  const hiCount = document.getElementById('stat-hi-count');
  let activeHorizon = '1m';
  const selected = new Set(); // utterance indices (strings); empty = no focus dimming

  function normTime(v) {
    if (!v) return '';
    const m = String(v).trim().match(/^(\\d{1,2}):(\\d{2})$/);
    if (!m) return '';
    const hh = Math.min(23, Math.max(0, parseInt(m[1], 10)));
    const mm = Math.min(59, Math.max(0, parseInt(m[2], 10)));
    return String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
  }

  function syncFocus() {
    const focusing = selected.size > 0;
    document.querySelectorAll('.hi-mark').forEach(function (g) {
      const idx = String(g.getAttribute('data-utt-index') || '');
      const on = selected.has(idx);
      g.classList.toggle('dim', focusing && !on);
      g.classList.toggle('focus', focusing && on);
    });
    Array.from(tbody.querySelectorAll('tr[data-hi]')).forEach(function (row) {
      const idx = String(row.dataset.uttIndex || '');
      const on = selected.has(idx);
      row.classList.toggle('row-selected', on);
      row.classList.toggle(
        'row-dim',
        focusing && row.dataset.horizon === activeHorizon && !on
      );
    });
    if (clearSelBtn) {
      clearSelBtn.style.display = focusing ? '' : 'none';
      clearSelBtn.textContent = focusing
        ? ('Clear selection (' + selected.size + ')')
        : 'Clear selection';
    }
  }

  function toggleUtt(idx) {
    idx = String(idx);
    if (!idx) return;
    if (selected.has(idx)) selected.delete(idx);
    else selected.add(idx);
    syncFocus();
  }

  function closeDpxMenu() {
    const list = document.getElementById('dpx-menu-list');
    const btn = document.getElementById('dpx-menu-btn');
    if (list) list.hidden = true;
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  function setHorizon(h) {
    activeHorizon = h;
    document.querySelectorAll('.view-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-horizon') === h);
    });
    document.querySelectorAll('.horizon-layer').forEach(function (g) {
      g.style.display = g.getAttribute('data-horizon') === h ? 'inline' : 'none';
    });
    const dpxBtn = document.getElementById('dpx-menu-btn');
    if (dpxBtn) dpxBtn.textContent = 'Δ ' + h + ' ▾';
    document.querySelectorAll('#dpx-menu-list [data-horizon]').forEach(function (opt) {
      opt.classList.toggle('active', opt.getAttribute('data-horizon') === h);
    });
    closeDpxMenu();
    apply();
    syncFocus();
  }

  function apply() {
    const rows = Array.from(tbody.querySelectorAll('tr[data-hi]'));
    const sp = speaker.value;
    const sec = section ? section.value : '';
    const d1 = ret1.value;
    const d3 = ret3 ? ret3.value : '';
    const d5 = ret5.value;
    const from = normTime(timeFrom.value);
    const to = normTime(timeTo.value);
    let shown = 0;
    let inView = 0;
    rows.forEach(function (row) {
      const inHorizon = row.dataset.horizon === activeHorizon;
      let ok = inHorizon;
      if (ok && sp && row.dataset.speaker !== sp) ok = false;
      if (ok && sec && row.dataset.section !== sec) ok = false;
      if (ok && d1 && row.dataset.ret1 !== d1) ok = false;
      if (ok && d3 && row.dataset.ret3 !== d3) ok = false;
      if (ok && d5 && row.dataset.ret5 !== d5) ok = false;
      const t = row.dataset.timeEt || '';
      if (ok && from && t < from) ok = false;
      if (ok && to && t > to) ok = false;
      row.style.display = ok ? '' : 'none';
      if (inHorizon) inView += 1;
      if (ok) shown += 1;
    });
    if (countEl) countEl.textContent = shown + ' / ' + inView + ' shown';
    if (hiCount) hiCount.textContent = String(inView);
    syncFocus();
  }

  document.querySelectorAll('.view-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      setHorizon(btn.getAttribute('data-horizon') || '1m');
    });
  });

  (function wireDpxMenu() {
    const wrap = document.getElementById('col-dpx');
    const btn = document.getElementById('dpx-menu-btn');
    const list = document.getElementById('dpx-menu-list');
    if (!wrap || !btn || !list) return;
    btn.addEventListener('click', function (ev) {
      ev.stopPropagation();
      const open = list.hidden;
      list.hidden = !open;
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    list.querySelectorAll('[data-horizon]').forEach(function (opt) {
      opt.addEventListener('click', function (ev) {
        ev.stopPropagation();
        setHorizon(opt.getAttribute('data-horizon') || '1m');
      });
    });
    document.addEventListener('click', function (ev) {
      if (!wrap.contains(ev.target)) closeDpxMenu();
    });
  })();

  document.querySelectorAll('.hi-mark').forEach(function (g) {
    g.addEventListener('click', function (ev) {
      ev.stopPropagation();
      toggleUtt(g.getAttribute('data-utt-index'));
    });
  });

  Array.from(tbody.querySelectorAll('tr[data-hi]')).forEach(function (row) {
    row.addEventListener('click', function (ev) {
      // Allow expanding snippets without toggling selection.
      if (ev.target.closest('details') || ev.target.closest('a')) return;
      toggleUtt(row.dataset.uttIndex);
    });
  });

  if (clearSelBtn) {
    clearSelBtn.addEventListener('click', function () {
      selected.clear();
      syncFocus();
    });
  }

  [speaker, section, ret1, ret3, ret5, timeFrom, timeTo].forEach(function (el) {
    if (el) el.addEventListener('change', apply);
    if (el) el.addEventListener('input', apply);
  });
  if (resetBtn) {
    resetBtn.addEventListener('click', function () {
      speaker.value = '';
      if (section) section.value = '';
      ret1.value = '';
      if (ret3) ret3.value = '';
      ret5.value = '';
      timeFrom.value = '';
      timeTo.value = '';
      apply();
    });
  }
  setHorizon('1m');
})();
</script>
"""


def build_html_report(
    *,
    ticker: str,
    quarter: str,
    bars: pd.DataFrame,
    aligned: list[AlignedUtterance],
    reactions: list[ReactionRow],
    summary: dict[str, Any],
    diagnostics: dict[str, Any],
) -> str:
    report_at = diagnostics.get("report_at")
    call_at = diagnostics.get("call_at")
    call_end = diagnostics.get("call_end_utc")

    report_ts = _parse_ts(report_at)
    call_ts = _parse_ts(call_at)
    call_end_ts = _parse_ts(call_end)

    by_horizon = (
        diagnostics.get("highlights_by_horizon")
        or (diagnostics.get("highlights") or {}).get("highlights_by_horizon")
        or {}
    )
    if not by_horizon:
        # Fallback: treat current .highlight flags as the 1m view only.
        sel = {u.index for u in aligned if u.highlight}
        by_horizon = {
            "1m": {"selected_indices": sorted(sel)},
            "3m": {"selected_indices": []},
            "5m": {"selected_indices": []},
        }
    nums_by_horizon = numbers_by_horizon(aligned, by_horizon)
    ordered = sorted(aligned, key=lambda u: (u.utterance_utc, u.index))
    by_index = {r.index: r for r in reactions}
    ret_from_call_by_index = {
        r.index: r.ret_from_call_start for r in reactions
    }
    n_hi_default = len(nums_by_horizon.get("1m") or {})

    context_start, context_end = compute_focus_window(
        bars, report_at=report_ts, call_at=call_ts, call_end=call_end_ts
    )
    svg_context = _svg_timeline(
        bars,
        aligned,
        view_start=context_start,
        view_end=context_end,
        nums_by_horizon=nums_by_horizon,
        report_at_iso=report_at,
        call_at_iso=call_at,
        call_end_iso=call_end,
        call_at=call_ts,
        ret_from_call_by_index=ret_from_call_by_index,
        mode="context",
        chart_id="context",
        legend="Light ticks = utterances · stem on defining 1m bar · segment = N-min move",
    )

    qa_start = diagnostics.get("qa_start_utc") or summary.get("qa_start_utc")
    call_window = compute_call_window(bars, call_at=call_ts, call_end=call_end_ts)
    if call_window is not None:
        svg_call = _svg_timeline(
            bars,
            aligned,
            view_start=call_window[0],
            view_end=call_window[1],
            nums_by_horizon=nums_by_horizon,
            call_at_iso=call_at,
            call_end_iso=call_end,
            qa_start_iso=qa_start,
            call_at=call_ts,
            ret_from_call_by_index=ret_from_call_by_index,
            mode="call",
            chart_id="call",
            legend="1-minute grid · Q&A split · stem on defining 1m bar · segment = N-min move",
        )
    else:
        svg_call = "<p class='muted'><em>Call-duration chart unavailable (missing call anchors or bars).</em></p>"

    speakers_set: set[str] = set()
    table_rows: list[str] = []
    for h in HORIZONS:
        nums = nums_by_horizon.get(h) or {}
        for u in ordered:
            if u.index not in nums:
                continue
            num = nums[u.index]
            r = by_index.get(u.index)
            ut = pd.Timestamp(u.utterance_utc)
            if ut.tzinfo is None:
                ut = ut.tz_localize("UTC")
            et_display = _fmt_et_clock(ut, with_seconds=True)
            et_filter = _fmt_et_clock(ut, with_seconds=False)
            time_key = et_filter if et_filter != "—" else ""
            speaker_raw = u.speaker or (r.speaker if r else "")
            if speaker_raw.strip():
                speakers_set.add(speaker_raw.strip())
            speaker = html.escape(speaker_raw)
            trigger = (
                r.full_text if r and r.full_text else " ".join((u.text or "").split())
            )
            preview = trigger_preview(trigger)
            mono_html = (
                r.monologue_html
                if r and r.monologue_html
                else f'<p class="mono-para trigger"><mark>{html.escape(trigger)}</mark></p>'
            )
            ret_1m = r.ret_1m if r else None
            ret_3m = r.ret_3m if r else None
            ret_5m = r.ret_5m if r else None
            if h == "1m":
                dpx_view = r.dpx_1m if r else None
            elif h == "3m":
                dpx_view = r.dpx_3m if r else None
            else:
                dpx_view = r.dpx_5m if r else None
            section = (r.section if r else "remarks") or "remarks"
            d1 = _ret_direction(ret_1m)
            d3 = _ret_direction(ret_3m)
            d5 = _ret_direction(ret_5m)
            display = "" if h == "1m" else "none"
            table_rows.append(
                "<tr "
                f"data-hi='1' "
                f"data-horizon='{h}' "
                f"data-utt-index='{u.index}' "
                f"style='display:{display};' "
                f"data-speaker='{html.escape(speaker_raw, quote=True)}' "
                f"data-section='{html.escape(section, quote=True)}' "
                f"data-ret1='{d1}' "
                f"data-ret3='{d3}' "
                f"data-ret5='{d5}' "
                f"data-time-et='{time_key}'>"
                f"<td class='num'>#{num}</td>"
                f"<td>{html.escape(et_display)}</td>"
                f"<td>{html.escape(section)}</td>"
                f"<td>{speaker}</td>"
                f"{_ret_cell(ret_1m)}"
                f"{_ret_cell(ret_3m)}"
                f"{_ret_cell(ret_5m)}"
                f"{_dpx_cell(dpx_view)}"
                f"{_num_cell(r.z_ret_1m if r else None)}"
                f"{_vol_cell(r.volume_1m if r else None)}"
                f"{_ret_cell(r.ret_from_call_start if r else None)}"
                f"{_ret_cell(r.ret_to_call_end if r else None)}"
                "<td class='snippet'>"
                f"<details><summary>{html.escape(preview)}</summary>"
                f"<div class='full-quote'>{mono_html}</div></details>"
                "</td>"
                "</tr>"
            )

    speaker_options = "".join(
        f'<option value="{html.escape(s)}">{html.escape(s)}</option>'
        for s in sorted(speakers_set)
    )

    join_health = diagnostics.get("join_health") or {}
    match_rate = join_health.get("match_rate", diagnostics.get("match_rate"))
    match_pct = "—" if match_rate is None else f"{100.0 * float(match_rate):.1f}%"
    n_total = len(ordered)
    badge = str(diagnostics.get("sync_badge") or "suspect")
    badge_cls = {
        "trusted": "badge-trusted",
        "fragile": "badge-fragile",
        "suspect": "badge-suspect",
    }.get(badge, "badge-suspect")
    hi_diag = diagnostics.get("highlights") or {}
    exploratory = bool(
        diagnostics.get("highlights_exploratory")
        if diagnostics.get("highlights_exploratory") is not None
        else hi_diag.get("highlights_exploratory", badge != "trusted")
    )
    trust_label = "exploratory" if exploratory else "trusted C1"
    floor_bits = []
    for h in HORIZONS:
        hd = by_horizon.get(h) or {}
        fv = hd.get("floor_value")
        fx = "—" if fv is None else f"${float(fv):.2f}"
        rx = "yes" if hd.get("highlights_relaxed") else "no"
        floor_bits.append(f"{h} floor≈{fx} (relaxed={rx})")
    floors_txt = "; ".join(floor_bits)
    j30 = (diagnostics.get("lag_sweep") or {}).get("min_jaccard_pm30")
    j30_txt = "—" if j30 is None else f"{float(j30):.2f}"

    rules_blurb = (
        "Highlights answer: what made the market react (coincidentally)? "
        "Three independent C1 views select Top-12 paragraphs by absolute "
        "N-minute price change (|Δprice_1m|, |Δprice_3m|, or |Δprice_5m|), "
        "not percent — so a drawdown does not inflate later moves — keeping "
        "only those at/above that view’s "
        f"75th-percentile score ({floors_txt}). "
        "Scoring is paragraph-level (a long monologue can yield multiple hits); "
        "expand a row for the full same-speaker monologue with the trigger paragraph marked. "
        "Each highlight’s stem meets the price line on the defining 1m bar "
        "(last close at/before speech = % from call start and Ret Nm start); "
        "table Time is when they spoke; tooltips also show tape @ HH:MM. "
        "The number bubble floats off the path. "
        "The orange segment is the measured N-minute move. "
        f"Trust gate: {trust_label} "
        "(trusted only when sync is not suspect and lag-sweep Jaccard ±30s ≥ 0.5)."
    )
    caveats = (
        "Coincident reaction only — not causal. After-hours liquidity can distort "
        "minute moves. The print may already be in the tape before speech begins. "
        "Treat fragile/suspect sync badges as exploratory. "
        "Operator soft filter is OFF by default."
    )
    window_note = (
        f"Window: {int(PRE_REPORT_PAD.total_seconds() // 60)}m before report → "
        f"{int(POST_CALL_PAD.total_seconds() // 60)}m after call end (ET)"
    )

    empty_body = '<tr><td colspan="13">No highlights</td></tr>'
    body = "".join(table_rows) if table_rows else empty_body

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(ticker)} {html.escape(quarter)} — Ticker Reaction</title>
  <style>
    body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 24px; color: #1a1a1a; background: #f7f8fa; }}
    main {{ max-width: 1280px; margin: 0 auto; background: #fff; padding: 28px 32px; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
    h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
    h2 {{ margin-top: 28px; }}
    .sub {{ color: #555; margin-bottom: 20px; }}
    .stats {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }}
    .stat {{ background: #f3f5f8; border-radius: 8px; padding: 10px 14px; min-width: 140px; }}
    .stat b {{ display: block; font-size: 1.1rem; margin-top: 4px; }}
    .caveat {{ background: #fff8e8; border-left: 4px solid #e0a800; padding: 10px 14px; margin: 18px 0; font-size: 0.92rem; }}
    .rules {{ background: #f0f9ff; border-left: 4px solid #0284c7; padding: 10px 14px; margin: 18px 0; font-size: 0.92rem; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-weight: 700; font-size: 0.85rem; text-transform: uppercase; }}
    .badge-trusted {{ background: #d1fae5; color: #065f46; }}
    .badge-fragile {{ background: #fef3c7; color: #92400e; }}
    .badge-suspect {{ background: #fee2e2; color: #991b1b; }}
    .view-toggle {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 8px; }}
    .view-btn {{ padding: 8px 14px; border-radius: 8px; border: 1px solid #cbd5e1; background: #fff; cursor: pointer; font: inherit; font-weight: 600; color: #334155; }}
    .view-btn:hover {{ background: #f1f5f9; }}
    .view-btn.active {{ background: #c45c26; border-color: #c45c26; color: #fff; }}
    .filters {{ display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: end; margin: 12px 0 16px; padding: 12px 14px; background: #f8fafc; border: 1px solid #e6e8eb; border-radius: 8px; }}
    .filters label {{ display: flex; flex-direction: column; gap: 4px; font-size: 0.78rem; color: #475569; font-weight: 600; }}
    .filters select, .filters input {{ font: inherit; font-weight: 400; color: #111; padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 6px; min-width: 120px; background: #fff; }}
    .filters button {{ padding: 7px 12px; border-radius: 6px; border: 1px solid #cbd5e1; background: #fff; cursor: pointer; font: inherit; }}
    .filters button:hover {{ background: #f1f5f9; }}
    #filter-count {{ font-size: 0.85rem; color: #64748b; margin-left: auto; align-self: center; }}
    #clear-hi-selection {{ display: none; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; }}
    th, td {{ border-bottom: 1px solid #e6e8eb; padding: 8px 6px; text-align: left; vertical-align: top; }}
    th {{ color: #444; font-weight: 600; }}
    td.num {{ font-weight: 700; color: #c45c26; white-space: nowrap; }}
    tr[data-hi] {{ cursor: pointer; }}
    tr[data-hi]:hover {{ background: #fff7ed; }}
    tr[data-hi].row-selected {{ background: #ffedd5; outline: 2px solid #c45c26; outline-offset: -2px; }}
    tr[data-hi].row-dim {{ opacity: 0.35; }}
    .hi-mark.dim .hi-seg, .hi-mark.dim .hi-stem {{ stroke: #94a3b8 !important; opacity: 0.35 !important; }}
    .hi-mark.dim .hi-end, .hi-mark.dim .hi-badge {{ fill: #94a3b8 !important; stroke: #e2e8f0 !important; opacity: 0.4 !important; }}
    .hi-mark.dim .hi-num {{ fill: #fff !important; }}
    .hi-mark.focus .hi-badge {{ stroke: #111827; stroke-width: 2.5; }}
    .hi-mark.focus .hi-seg {{ stroke-width: 2.75; opacity: 1 !important; }}
    td.snippet details summary {{ cursor: pointer; list-style: none; }}
    td.snippet details summary::-webkit-details-marker {{ display: none; }}
    td.snippet details summary::after {{ content: " ▾ expand"; color: #64748b; font-size: 0.8rem; white-space: nowrap; }}
    td.snippet details[open] summary::after {{ content: " ▴ collapse"; }}
    td.snippet .full-quote {{ margin: 8px 0 0; padding: 10px 12px; background: #f8fafc; border-left: 3px solid #c45c26; border-radius: 4px; line-height: 1.45; }}
    td.snippet .mono-para {{ margin: 0 0 8px; }}
    td.snippet .mono-para:last-child {{ margin-bottom: 0; }}
    td.snippet .mono-para.trigger mark {{ background: #fde68a; color: inherit; padding: 0 2px; }}
    .ret-pos {{ color: #047857; font-variant-numeric: tabular-nums; }}
    .ret-neg {{ color: #b91c1c; font-variant-numeric: tabular-nums; }}
    .ret-zero, .ret-null {{ color: #64748b; font-variant-numeric: tabular-nums; }}
    th.col-dpx, td.col-dpx {{
      font-weight: 700;
      border-left: 2px solid #94a3b8;
      border-right: 2px solid #94a3b8;
      background: #fff7ed;
      white-space: nowrap;
      text-align: center;
    }}
    th.col-dpx {{ position: relative; vertical-align: middle; padding: 4px 6px; }}
    .dpx-menu {{ position: relative; display: inline-block; }}
    .dpx-menu-btn {{
      font: inherit; font-weight: 700; color: #9a3412; background: transparent;
      border: 1px solid transparent; border-radius: 6px; padding: 4px 8px; cursor: pointer;
    }}
    .dpx-menu-btn:hover, .dpx-menu-btn[aria-expanded="true"] {{
      background: #ffedd5; border-color: #fdba74;
    }}
    .dpx-menu-list {{
      position: absolute; z-index: 20; top: calc(100% + 4px); left: 50%; transform: translateX(-50%);
      min-width: 7rem; background: #fff; border: 1px solid #cbd5e1; border-radius: 8px;
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.12); padding: 4px; display: flex; flex-direction: column; gap: 2px;
    }}
    .dpx-menu-list[hidden] {{ display: none; }}
    .dpx-menu-list button {{
      font: inherit; font-weight: 600; text-align: left; border: 0; background: transparent;
      padding: 7px 10px; border-radius: 6px; cursor: pointer; color: #334155;
    }}
    .dpx-menu-list button:hover {{ background: #f1f5f9; }}
    .dpx-menu-list button.active {{ background: #c45c26; color: #fff; }}
    .muted {{ color: #666; font-size: 0.9rem; }}
  </style>
</head>
<body>
<main>
  <h1>{html.escape(ticker)} {html.escape(quarter)} — Call / Tape Reaction</h1>
  <p class="sub">Tape-first join: Bloomberg 1-minute bars × Quartr timed paragraphs.
    Sync status: <span class="badge {badge_cls}">{html.escape(badge)}</span>
    · highlights: <strong>{html.escape(trust_label)}</strong>
    · lag-sweep Jaccard ±30s: {html.escape(j30_txt)}
  </p>

  <div class="stats">
    <div class="stat">Match rate<b>{match_pct}</b></div>
    <div class="stat">Utterances<b>{n_total}</b></div>
    <div class="stat">Highlights (active view)<b id="stat-hi-count">{n_hi_default}</b></div>
    <div class="stat">Report → call<b>{_fmt_pct(summary.get("cum_return_report_to_call"))}</b></div>
    <div class="stat">Call → end<b>{_fmt_pct(summary.get("cum_return_call_to_end"))}</b></div>
  </div>

  <div class="rules">{html.escape(rules_blurb)}</div>
  <div class="caveat">{html.escape(caveats)}</div>

  <div class="view-toggle" id="horizon-views" role="group" aria-label="Highlight horizon">
    <button type="button" class="view-btn active" data-horizon="1m">Ret 1m</button>
    <button type="button" class="view-btn" data-horizon="3m">Ret 3m</button>
    <button type="button" class="view-btn" data-horizon="5m">Ret 5m</button>
  </div>
  <p class="muted">Switching the view changes table rows and chart badges for that horizon’s C1 Top-K.</p>

  <h2>Price around report &amp; call</h2>
  <p class="muted">{html.escape(window_note)}. Badges numbered 1…K chronologically within the active view.</p>
  {svg_context}

  <h2>Price during the call</h2>
  <p class="muted">Zoomed to call start → call end. Purple <b>Q&amp;A</b> line marks remarks → Q&amp;A split. Click badges (multi-select) to focus them on the chart and in the table; others grey out. Same for table row clicks.</p>
  {svg_call}

  <h2>Highlighted utterances</h2>
  <p class="muted">Click a row to select/deselect (multi-select). Preview = trigger paragraph; expand for the full monologue. Full CSV: Output/Tables.</p>

  <div class="filters" id="highlight-filters">
    <label>Speaker
      <select id="filter-speaker">
        <option value="">All</option>
        {speaker_options}
      </select>
    </label>
    <label>Section
      <select id="filter-section">
        <option value="">All</option>
        <option value="remarks">remarks</option>
        <option value="qa">qa</option>
      </select>
    </label>
    <label>Ret 1m
      <select id="filter-ret1">
        <option value="">All</option>
        <option value="up">Up</option>
        <option value="down">Down</option>
        <option value="flat">Flat</option>
        <option value="na">N/A</option>
      </select>
    </label>
    <label>Ret 3m
      <select id="filter-ret3">
        <option value="">All</option>
        <option value="up">Up</option>
        <option value="down">Down</option>
        <option value="flat">Flat</option>
        <option value="na">N/A</option>
      </select>
    </label>
    <label>Ret 5m
      <select id="filter-ret5">
        <option value="">All</option>
        <option value="up">Up</option>
        <option value="down">Down</option>
        <option value="flat">Flat</option>
        <option value="na">N/A</option>
      </select>
    </label>
    <label>Time from (ET, HH:MM)
      <input type="text" id="filter-time-from" inputmode="numeric" placeholder="17:00" pattern="^\\d{{1,2}}:\\d{{2}}$" maxlength="5" autocomplete="off"/>
    </label>
    <label>Time to (ET, HH:MM)
      <input type="text" id="filter-time-to" inputmode="numeric" placeholder="17:50" pattern="^\\d{{1,2}}:\\d{{2}}$" maxlength="5" autocomplete="off"/>
    </label>
    <button type="button" id="filter-reset">Reset filters</button>
    <button type="button" id="clear-hi-selection">Clear selection</button>
    <span id="filter-count"></span>
  </div>

  <table id="highlight-table">
    <thead>
      <tr>
        <th>#</th><th>Time (ET)</th><th>Section</th><th>Speaker</th>
        <th>Ret 1m</th><th>Ret 3m</th><th>Ret 5m</th>
        <th class="col-dpx" id="col-dpx" title="Selection score for this view — click to switch horizon">
          <div class="dpx-menu">
            <button type="button" class="dpx-menu-btn" id="dpx-menu-btn" aria-haspopup="listbox" aria-expanded="false">Δ 1m ▾</button>
            <div class="dpx-menu-list" id="dpx-menu-list" hidden role="listbox">
              <button type="button" role="option" data-horizon="1m" class="active">Δ 1m</button>
              <button type="button" role="option" data-horizon="3m">Δ 3m</button>
              <button type="button" role="option" data-horizon="5m">Δ 5m</button>
            </div>
          </div>
        </th>
        <th>z Ret 1m</th><th>Vol 1m</th>
        <th>From call start</th><th>To call end</th><th>Snippet</th>
      </tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</main>
{_filter_script()}
</body>
</html>
"""


def write_outputs(
    *,
    output_root: Path,
    slug: str,
    ticker: str,
    quarter: str,
    bars: pd.DataFrame,
    aligned: list[AlignedUtterance],
    reactions: list[ReactionRow],
    summary: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Path]:
    html_path = reports_html_path(output_root, slug)
    csv_path = reactions_csv_path(output_root, slug)
    diag_path = diagnostics_json_path(output_root, slug)

    html_path.write_text(
        build_html_report(
            ticker=ticker,
            quarter=quarter,
            bars=bars,
            aligned=aligned,
            reactions=reactions,
            summary=summary,
            diagnostics=diagnostics,
        ),
        encoding="utf-8",
    )
    reactions_to_frame(reactions).to_csv(csv_path, index=False)
    diag_path.write_text(json.dumps(diagnostics, indent=2, default=str), encoding="utf-8")

    return {
        "report": html_path,
        "table": csv_path,
        "diagnostics": diag_path,
    }
