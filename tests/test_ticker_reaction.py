"""Synthetic tests for offline ticker-reaction scaffold."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SN = REPO_ROOT / "Structured Narrative"
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from ticker_reaction.align import (  # noqa: E402
    align_utterances,
    utterance_wall_clock,
)
from ticker_reaction.highlights import (  # noqa: E402
    apply_highlights,
    apply_horizon_highlights,
    highlight_sequence_numbers,
    select_all_horizon_highlights,
    select_c1_indices,
    select_c1_indices_for_horizon,
)
from ticker_reaction.load_bars import load_bars  # noqa: E402
from ticker_reaction.load_transcript import (  # noqa: E402
    EventAnchors,
    Paragraph,
    TimedTranscript,
    load_anchors,
    load_transcript,
)
from ticker_reaction.paths import (  # noqa: E402
    diagnostics_json_path,
    event_slug,
    reactions_csv_path,
    reports_html_path,
)
from ticker_reaction.pipeline import run_ticker_reaction  # noqa: E402
from ticker_reaction.reactions import (  # noqa: E402
    ReactionRow,
    _forward_return,
    build_reaction_rows,
    cumulative_return,
    forward_return_anchors,
    resolve_highlight_placement,
)
from ticker_reaction.report import (  # noqa: E402
    CALL_CHART_POST_PAD,
    POST_CALL_PAD,
    PRE_REPORT_PAD,
    build_html_report,
    compute_call_window,
    compute_focus_window,
)
from ticker_reaction.sectioning import detect_qa_start_sec  # noqa: E402
from ticker_reaction.speech_turns import (  # noqa: E402
    build_speech_turns,
    monologue_html,
)
from ticker_reaction.sync import (  # noqa: E402
    build_sync_diagnostics,
    highlights_exploratory,
    join_health,
    lag_sensitivity_sweep,
    sync_badge,
    sync_contract,
)


class TestTickerReaction(unittest.TestCase):
    def test_event_slug_and_typed_paths(self) -> None:
        slug = event_slug("amzn", "fy2026-q2")
        self.assertEqual(slug, "AMZN_FY2026-Q2")
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Output"
            html = reports_html_path(root, slug)
            csv = reactions_csv_path(root, slug)
            diag = diagnostics_json_path(root, slug)
            self.assertTrue(html.parent.is_dir())
            self.assertEqual(html.name, "ticker_reaction.html")
            self.assertIn("Reports", str(html))
            self.assertIn("Tables", str(csv))
            self.assertIn("Diagnostics", str(diag))

    def test_utterance_wall_clock(self) -> None:
        call_at = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)
        got = utterance_wall_clock(call_at, 90.0)
        self.assertEqual(got, datetime(2026, 7, 30, 21, 1, 30, tzinfo=timezone.utc))

    def test_load_bars_et_naive_and_sort(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.xlsx"
            rows = [
                {"Date": "2026-07-30 17:02:00", "Open": 10.2, "High": 10.3, "Low": 10.1, "Close": 10.25, "Volume": 100},
                {"Date": "2026-07-30 17:01:00", "Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.05, "Volume": 200},
                {"Date": "2026-07-30 17:00:00", "Open": 9.8, "High": 10.0, "Low": 9.7, "Close": 9.95, "Volume": 300},
            ]
            pd.DataFrame(rows).to_excel(path, index=False)
            bars = load_bars(path)
            self.assertEqual(len(bars), 3)
            self.assertTrue(bars.attrs.get("sorted_from_reverse"))
            self.assertEqual(bars.attrs.get("assumed_tz"), "America/New_York")
            first = bars["ts_utc"].iloc[0]
            self.assertEqual(first, pd.Timestamp("2026-07-30 21:00:00+00:00"))
            self.assertTrue(bars["ts_utc"].is_monotonic_increasing)

    def test_focus_window_pads_and_clamps(self) -> None:
        bars = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(
                    [
                        "2026-07-30T19:00:00Z",
                        "2026-07-30T19:45:00Z",
                        "2026-07-30T20:00:00Z",
                        "2026-07-30T21:00:00Z",
                        "2026-07-30T21:50:00Z",
                        "2026-07-30T22:30:00Z",
                    ],
                    utc=True,
                ),
                "close": [1, 2, 3, 4, 5, 6],
            }
        )
        report = pd.Timestamp("2026-07-30T20:00:00Z")
        call = pd.Timestamp("2026-07-30T21:00:00Z")
        call_end = pd.Timestamp("2026-07-30T21:50:00Z")
        start, end = compute_focus_window(
            bars, report_at=report, call_at=call, call_end=call_end
        )
        self.assertEqual(start, report - PRE_REPORT_PAD)
        self.assertEqual(end, call_end + POST_CALL_PAD)

    def test_call_window_pads_five_minutes_past_end(self) -> None:
        bars = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(
                    [
                        "2026-07-30T21:00:00Z",
                        "2026-07-30T21:50:00Z",
                        "2026-07-30T21:55:00Z",
                        "2026-07-30T22:10:00Z",
                    ],
                    utc=True,
                ),
                "close": [1, 2, 3, 4],
            }
        )
        call = pd.Timestamp("2026-07-30T21:00:00Z")
        call_end = pd.Timestamp("2026-07-30T21:50:00Z")
        start, end = compute_call_window(bars, call_at=call, call_end=call_end)
        self.assertEqual(start, call)
        self.assertEqual(end, call_end + CALL_CHART_POST_PAD)
        self.assertEqual(CALL_CHART_POST_PAD, timedelta(minutes=5))

    def test_forward_return_3m(self) -> None:
        bars = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(
                    [f"2026-07-30T21:{m:02d}:00Z" for m in range(0, 8)],
                    utc=True,
                ),
                "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0],
                "volume": [10] * 8,
            }
        )
        t = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)
        ret_3m, _, dpx_3m = _forward_return(bars, t, 3)
        # Start close at 21:00 (=100), end close at 21:03 (=103)
        self.assertAlmostEqual(ret_3m, 0.03)
        self.assertAlmostEqual(dpx_3m, 3.0)

    def test_c1_selects_largest_moves_not_length(self) -> None:
        rows = [
            ReactionRow(
                0, "", 0, 1, "A", None, "x" * 500, False, True, None, None,
                0.001, 0.001, 0.001, 10, dpx_1m=0.10, dpx_3m=0.10, dpx_5m=0.10,
            ),
            ReactionRow(
                1, "", 1, 2, "B", None, "short", False, True, None, None,
                -0.05, -0.04, -0.02, 100, dpx_1m=-5.0, dpx_3m=-4.0, dpx_5m=-2.0,
            ),
            ReactionRow(
                2, "", 2, 3, "C", None, "y" * 400, False, True, None, None,
                0.002, 0.001, 0.0, 11, dpx_1m=0.20, dpx_3m=0.10, dpx_5m=0.0,
            ),
            ReactionRow(
                3, "", 3, 4, "D", None, "z", False, True, None, None,
                0.04, 0.035, 0.03, 90, dpx_1m=4.0, dpx_3m=3.5, dpx_5m=3.0,
            ),
        ]
        selected, diag = select_c1_indices(rows, top_k=2, percentile_floor=50, min_clear=1)
        self.assertIn(1, selected)
        self.assertIn(3, selected)
        self.assertNotIn(0, selected)
        self.assertEqual(diag["rule"], "C1_topK_abs_dpx_floor_1m_temporal_gap")
        self.assertEqual(diag["min_gap_sec"], 30.0)
        self.assertEqual(diag["score_unit"], "price_points")

    def test_c1_prefers_larger_dollar_move_over_larger_pct(self) -> None:
        """Equal-ish setup where % would pick the trough rebound; |Δprice| picks $ size."""
        rows = [
            # $10 on $100 = +10% (would win on %)
            ReactionRow(
                0, "", 0, 1, "A", None, "low base", False, True, None, 100.0,
                0.10, 0.10, 0.10, 10, dpx_1m=10.0, dpx_3m=10.0, dpx_5m=10.0,
            ),
            # $12 on $200 = +6% (wins on |Δprice|)
            ReactionRow(
                1, "", 1, 2, "B", None, "high base", False, True, None, 200.0,
                0.06, 0.06, 0.06, 10, dpx_1m=12.0, dpx_3m=12.0, dpx_5m=12.0,
            ),
        ]
        selected, _ = select_c1_indices(rows, top_k=1, percentile_floor=0, min_clear=1)
        self.assertEqual(selected, {1})

    def test_speech_turns_group_same_speaker(self) -> None:
        paras = [
            Paragraph(0, 0.0, 10.0, "CEO", "CEO", "Part one of the monologue."),
            Paragraph(1, 10.0, 20.0, "CEO", "CEO", "Part two continues."),
            Paragraph(2, 20.0, 30.0, "CFO", "CFO", "Different speaker."),
            Paragraph(3, 30.0, 40.0, "CEO", "CEO", "CEO again after break."),
        ]
        tr = TimedTranscript(1, 1, paras, 0.0, 40.0, {})
        turns, index_to_turn = build_speech_turns(tr)
        self.assertEqual(len(turns), 3)
        self.assertEqual(index_to_turn[0], index_to_turn[1])
        self.assertNotEqual(index_to_turn[1], index_to_turn[2])
        self.assertEqual(turns[0].full_text, "Part one of the monologue. Part two continues.")
        marked = monologue_html(turns[0], trigger_index=1)
        self.assertIn("<mark>", marked)
        self.assertIn("Part two continues.", marked)
        self.assertIn("Part one of the monologue.", marked)

    def test_horizon_c1_sets_can_differ(self) -> None:
        rows = [
            ReactionRow(
                0, "", 0, 1, "A", None, "a", False, True, None, None,
                0.10, 0.01, 0.01, 10, dpx_1m=10.0, dpx_3m=1.0, dpx_5m=1.0,
            ),
            ReactionRow(
                1, "", 1, 2, "B", None, "b", False, True, None, None,
                0.01, 0.10, 0.01, 10, dpx_1m=1.0, dpx_3m=10.0, dpx_5m=1.0,
            ),
            ReactionRow(
                2, "", 2, 3, "C", None, "c", False, True, None, None,
                0.01, 0.01, 0.10, 10, dpx_1m=1.0, dpx_3m=1.0, dpx_5m=10.0,
            ),
            ReactionRow(
                3, "", 3, 4, "D", None, "d", False, True, None, None,
                0.02, 0.02, 0.02, 10, dpx_1m=2.0, dpx_3m=2.0, dpx_5m=2.0,
            ),
        ]
        by_h = select_all_horizon_highlights(
            rows, top_k=1, percentile_floor=0, min_clear=1
        )
        self.assertEqual(by_h["1m"]["selected_indices"], [0])
        self.assertEqual(by_h["3m"]["selected_indices"], [1])
        self.assertEqual(by_h["5m"]["selected_indices"], [2])
        sel_3m, diag_3m = select_c1_indices_for_horizon(
            rows, "3m", top_k=1, percentile_floor=0, min_clear=1
        )
        self.assertEqual(sel_3m, {1})
        self.assertEqual(diag_3m["horizon"], "3m")

    def test_section_qa_detection(self) -> None:
        paras = [
            Paragraph(0, 0.0, 10.0, "CEO", "CEO", "Opening remarks about AWS growth."),
            Paragraph(1, 20.0, 30.0, "CFO", "CFO", "Financial results were strong."),
            Paragraph(2, 40.0, 50.0, "Operator", None, "We will now open the call for questions."),
            Paragraph(3, 60.0, 70.0, "Analyst", None, "Thanks for taking my question on CapEx."),
        ]
        tr = TimedTranscript(1, 1, paras, 0.0, 70.0, {})
        qa = detect_qa_start_sec(tr)
        self.assertEqual(qa, 40.0)

    def test_section_qa_ignores_call_start_agenda(self) -> None:
        """Operator intro mentioning future Q&A must not pin the marker at t=0."""
        paras = [
            Paragraph(
                0,
                0.06,
                26.0,
                "Operator",
                None,
                "Welcome. At this time all participants are in a listen-only mode. "
                "After the presentation, we will conduct a question-and-answer session.",
            ),
            Paragraph(1, 26.0, 80.0, "IR", "Investor Relations", "Hello and welcome."),
            Paragraph(2, 80.0, 200.0, "CEO", "CEO", "Prepared remarks about growth."),
            Paragraph(
                3,
                1718.0,
                1750.0,
                "Operator",
                None,
                "At this time, we will now open the call up for questions.",
            ),
            Paragraph(
                4,
                1760.0,
                1780.0,
                "Analyst",
                None,
                "Thanks for taking my question on CapEx.",
            ),
        ]
        tr = TimedTranscript(1, 1, paras, 0.0, 1780.0, {})
        qa = detect_qa_start_sec(tr)
        self.assertEqual(qa, 1718.0)

    def test_join_health_and_sync_badge(self) -> None:
        call_at = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)
        call_end = call_at + timedelta(seconds=10)
        aligned = align_utterances(
            TimedTranscript(
                1,
                1,
                [Paragraph(0, 0.0, 10.0, "A", None, "hello world " * 5)],
                0.0,
                10.0,
                {},
            ),
            EventAnchors("AMZN", "FY2026-Q2", 1, call_at, call_at - timedelta(hours=1), {}),
            pd.DataFrame(
                {
                    "ts_utc": pd.to_datetime(["2026-07-30T21:00:00Z"], utc=True),
                    "close": [100.0],
                    "volume": [1],
                }
            ),
        )
        health = join_health(aligned)
        self.assertEqual(health["matched_count"], 1)
        self.assertEqual(sync_badge(sync_suspect=False, timing_fragile=True), "fragile")
        self.assertEqual(sync_badge(sync_suspect=True, timing_fragile=False), "suspect")
        self.assertEqual(sync_badge(sync_suspect=False, timing_fragile=False), "trusted")
        contract = sync_contract(
            EventAnchors("AMZN", "FY2026-Q2", 1, call_at, call_at - timedelta(hours=1), {}),
            call_end=call_end,
        )
        self.assertEqual(contract["call_end"], call_end.isoformat())
        self.assertIn("bars_tz_assumed", contract)
        self.assertFalse(
            highlights_exploratory(sync_suspect=False, min_jaccard_pm30=0.8)
        )
        self.assertTrue(
            highlights_exploratory(sync_suspect=False, min_jaccard_pm30=0.4)
        )
        self.assertTrue(
            highlights_exploratory(sync_suspect=True, min_jaccard_pm30=0.9)
        )

    def test_lag_sweep_runs(self) -> None:
        call_at = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)
        bars = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(
                    [f"2026-07-30T21:{m:02d}:00Z" for m in range(0, 20)],
                    utc=True,
                ),
                "close": [100 + i * 0.1 for i in range(20)],
                "volume": [10] * 20,
            }
        )
        anchors = EventAnchors("AMZN", "FY2026-Q2", 1, call_at, None, {})
        paras = [
            Paragraph(i, float(i * 60), float(i * 60 + 10), "S", None, f"line {i}")
            for i in range(5)
        ]
        tr = TimedTranscript(1, 1, paras, 0.0, 250.0, {})
        aligned = align_utterances(tr, anchors, bars)

        def select(pairs):
            from ticker_reaction.reactions import scores_at_times

            tmp = scores_at_times(bars, pairs)
            sel, _ = select_c1_indices(tmp, top_k=3, min_clear=1, percentile_floor=0)
            return sel

        sweep = lag_sensitivity_sweep(
            aligned_base=aligned, bars=bars, score_and_select=select
        )
        self.assertIn("0", sweep["per_lag"])
        self.assertIn("min_jaccard_pm30", sweep)

    def test_report_html_c1_and_sync(self) -> None:
        call_at = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)
        report_at = call_at - timedelta(hours=1)
        bars = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(
                    [f"2026-07-30T{h:02d}:{m:02d}:00Z" for h in (19, 20, 21, 22) for m in (0, 15, 30, 45)],
                    utc=True,
                ),
                "close": [100 + i for i in range(16)],
                "volume": [1000 + 10 * i for i in range(16)],
            }
        )
        paragraphs = [
            Paragraph(0, 0.0, 10.0, "A", "CEO", "short one"),
            Paragraph(1, 60.0, 80.0, "B", "CEO", "this is a longer paragraph about AWS " * 4),
            Paragraph(2, 120.0, 140.0, "Operator", None, "We will now open the call for questions."),
            Paragraph(3, 180.0, 200.0, "Analyst", None, "Thanks for taking my question."),
        ]
        transcript = TimedTranscript(1, 1, paragraphs, 0.0, 200.0, {})
        anchors = EventAnchors("AMZN", "FY2026-Q2", 1, call_at, report_at, {})
        aligned = align_utterances(transcript, anchors, bars)
        reactions = build_reaction_rows(
            aligned, bars, anchors=anchors, transcript=transcript
        )
        # Force a clear C1 winner on 1m; different winner geometry for 5m
        reactions[1] = ReactionRow(
            **{
                **reactions[1].__dict__,
                "ret_1m": -0.08,
                "ret_3m": -0.01,
                "ret_5m": -0.01,
                "dpx_1m": -8.0,
                "dpx_3m": -1.0,
                "dpx_5m": -1.0,
            }
        )
        reactions[0] = ReactionRow(
            **{
                **reactions[0].__dict__,
                "ret_1m": 0.0,
                "ret_3m": 0.0,
                "ret_5m": -0.09,
                "dpx_1m": 0.0,
                "dpx_3m": 0.0,
                "dpx_5m": -9.0,
            }
        )
        by_h = select_all_horizon_highlights(
            reactions, top_k=2, min_clear=1, percentile_floor=50
        )
        aligned, reactions = apply_horizon_highlights(aligned, reactions, by_h)
        self.assertTrue(any(u.highlight for u in aligned))
        nums = highlight_sequence_numbers(aligned)
        self.assertEqual(min(nums.values()), 1)

        html = build_html_report(
            ticker="AMZN",
            quarter="FY2026-Q2",
            bars=bars,
            aligned=aligned,
            reactions=reactions,
            summary={
                "cum_return_report_to_call": 0.01,
                "cum_return_call_to_end": 0.02,
                "qa_start_utc": (call_at + timedelta(seconds=120)).isoformat(),
            },
            diagnostics={
                "report_at": report_at.isoformat(),
                "call_at": call_at.isoformat(),
                "call_end_utc": (call_at + timedelta(seconds=200)).isoformat(),
                "qa_start_utc": (call_at + timedelta(seconds=120)).isoformat(),
                "match_rate": 1.0,
                "paragraph_count": 4,
                "bar_count": len(bars),
                "sync_badge": "trusted",
                "join_health": {"match_rate": 1.0},
                "lag_sweep": {"min_jaccard_pm30": 0.8, "timing_fragile": False},
                "highlights_by_horizon": by_h,
                "highlights": {
                    **by_h["1m"],
                    "highlights_by_horizon": by_h,
                    "highlights_relaxed": False,
                },
            },
        )
        self.assertIn("Price (USD)", html)
        self.assertIn("sync", html.lower())
        self.assertIn("C1", html)
        self.assertIn("z Ret 1m", html)
        self.assertIn('id="col-dpx"', html)
        self.assertIn("dpx-menu-btn", html)
        self.assertIn("dpx-menu-list", html)
        self.assertIn("Δ 1m", html)
        self.assertIn('class="col-dpx', html)
        self.assertRegex(html, r"\$[+-]\d+\.\d{2}")
        self.assertIn("Ret 3m", html)
        self.assertIn("filter-ret3", html)
        self.assertIn("filter-section", html)
        self.assertIn("Q&amp;A", html)
        self.assertNotIn("Top-quartile length", html)
        self.assertIn('data-horizon="1m"', html)
        self.assertIn('data-horizon="5m"', html)
        self.assertIn("view-btn", html)
        self.assertIn("horizon-layer", html)
        self.assertIn("hi-mark", html)
        self.assertIn("data-utt-index=", html)
        self.assertIn("clear-hi-selection", html)
        self.assertIn("mono-para trigger", html)
        self.assertIn("<mark>", html)
        # Time column shows HH:MM:SS; filter attribute/inputs stay HH:MM.
        self.assertRegex(html, r"<td>\d{2}:\d{2}:\d{2}</td>")
        self.assertRegex(html, r"data-time-et=['\"]\d{2}:\d{2}['\"]")
        self.assertIn("Time from (ET, HH:MM)", html)
        self.assertIn('id="filter-time-from"', html)
        self.assertIn('placeholder="17:00"', html)
        self.assertTrue(any(r.ret_3m is not None for r in reactions))
        self.assertIn("stem on defining 1m bar", html)

    def test_badge_uses_return_window_start_not_nearest_close(self) -> None:
        """Stem / % from call use defining bar (last at/before speech)."""
        call_at = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)
        bars = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(
                    [
                        "2026-07-30T21:00:00Z",
                        "2026-07-30T21:19:00Z",
                        "2026-07-30T21:20:00Z",
                        "2026-07-30T21:21:00Z",
                    ],
                    utc=True,
                ),
                "close": [254.3, 235.5, 257.2, 257.0],
                "volume": [10, 90_000, 60_000, 10],
            }
        )
        t = datetime(2026, 7, 30, 21, 19, 43, tzinfo=timezone.utc)
        paragraphs = [
            Paragraph(0, 19 * 60 + 43, 19 * 60 + 50, "CEO", "CEO", "Alexa+ and Leo plunge"),
        ]
        transcript = TimedTranscript(1, 1, paragraphs, 0.0, 1200.0, {})
        anchors = EventAnchors("AMZN", "FY2026-Q2", 1, call_at, None, {})
        aligned = align_utterances(transcript, anchors, bars)
        reactions = build_reaction_rows(
            aligned, bars, anchors=anchors, transcript=transcript
        )
        # Defining bar 21:19 close 235.5 — not mid-minute interpolation.
        expected_ret = 235.5 / 254.3 - 1.0
        self.assertAlmostEqual(reactions[0].ret_from_call_start or 0.0, expected_ret, places=5)
        self.assertAlmostEqual(reactions[0].ret_1m or 0.0, 257.2 / 235.5 - 1.0, places=5)
        place = resolve_highlight_placement(
            bars,
            call_at=call_at,
            utterance_utc=t,
            ret_from_call_start=reactions[0].ret_from_call_start,
            fallback_close=257.2,
        )
        self.assertEqual(place.match_kind, "defining_bar")
        self.assertEqual(place.utterance_utc, pd.Timestamp(t))
        self.assertEqual(place.bar_ts, pd.Timestamp("2026-07-30T21:19:00Z"))
        self.assertAlmostEqual(place.bar_close, 235.5, places=5)
        self.assertEqual(place.matched_pct, -7.4)

        aligned[0] = replace(aligned[0], highlight=True)
        html = build_html_report(
            ticker="AMZN",
            quarter="FY2026-Q2",
            bars=bars,
            aligned=aligned,
            reactions=reactions,
            summary={},
            diagnostics={
                "call_at": call_at.isoformat(),
                "call_end_utc": (call_at + timedelta(minutes=25)).isoformat(),
                "sync_badge": "trusted",
                "join_health": {"match_rate": 1.0},
                "lag_sweep": {"min_jaccard_pm30": 1.0, "timing_fragile": False},
                "highlights": {"highlights_relaxed": False, "rule": "C1"},
            },
        )
        self.assertIn("hi-anchor", html)
        self.assertIn("17:19:43", html)
        self.assertIn("tape @ 17:19", html)
        self.assertIn("from call start", html)
        self.assertIn("+1m later", html)

    def test_pipeline_writes_typed_output(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars_path = root / "bars.xlsx"
            rows = []
            for h, m, px in [
                (15, 45, 88.0),
                (16, 0, 90.0),
                (16, 30, 92.0),
                (16, 59, 95.0),
                (17, 0, 100.0),
                (17, 1, 101.0),
                (17, 5, 103.0),
                (17, 20, 104.0),
            ]:
                rows.append(
                    {
                        "Date": f"2026-07-30 {h:02d}:{m:02d}:00",
                        "Close": px,
                        "Volume": 50 + m,
                    }
                )
            pd.DataFrame(rows).to_excel(bars_path, index=False)

            anchors = {
                "ticker": "AMZN",
                "fiscal_period": "FY2026-Q2",
                "eventId": 1,
                "call_at": "2026-07-30T21:00:00.000Z",
                "report_at": "2026-07-30T20:00:00.000Z",
            }
            transcript = {
                "eventId": 1,
                "documentId": 1,
                "paragraph_count": 2,
                "first_start_sec": 0.0,
                "last_end_sec": 120.0,
                "paragraphs": [
                    {
                        "start": 0.0,
                        "end": 30.0,
                        "speaker": "CEO",
                        "speakerRole": "CEO",
                        "text": "Strong quarter " * 20,
                        "url": None,
                    },
                    {
                        "start": 60.0,
                        "end": 90.0,
                        "speaker": "Operator",
                        "speakerRole": None,
                        "text": "We will now open the call for questions.",
                        "url": None,
                    },
                ],
            }
            anchors_path = root / "anchors.json"
            transcript_path = root / "transcript.json"
            anchors_path.write_text(json.dumps(anchors), encoding="utf-8")
            transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

            out_root = root / "Output"
            result = run_ticker_reaction(
                bars_path=bars_path,
                transcript_path=transcript_path,
                anchors_path=anchors_path,
                output_root=out_root,
            )
            self.assertTrue(Path(result["paths"]["report"]).is_file())
            diag = json.loads(Path(result["paths"]["diagnostics"]).read_text(encoding="utf-8"))
            self.assertIn("sync_badge", diag)
            self.assertIn("highlights", diag)
            self.assertIn("highlights_by_horizon", diag)
            self.assertIn("1m", diag["highlights_by_horizon"])
            self.assertIn("3m", diag["highlights_by_horizon"])
            self.assertIn("5m", diag["highlights_by_horizon"])
            self.assertIn("lag_sweep", diag)
            self.assertIn("highlights_exploratory", diag)
            self.assertIn("call_end", diag["sync_contract"])
            report_html = Path(result["paths"]["report"]).read_text(encoding="utf-8")
            self.assertIn("Price (USD)", report_html)
            self.assertIn("z Ret 1m", report_html)
            self.assertIn('id="col-dpx"', report_html)
            self.assertIn("dpx-menu-btn", report_html)
            self.assertIn("Δ 1m", report_html)
            self.assertIn("Ret 3m", report_html)
            self.assertIn("view-btn", report_html)
            self.assertIn("sync", report_html.lower())
            self.assertRegex(report_html, r"td\.snippet details summary::after")
            csv_text = Path(result["paths"]["table"]).read_text(encoding="utf-8")
            self.assertIn("ret_3m", csv_text)
            self.assertIn("highlight_1m", csv_text)
            self.assertIn("speech_turn_id", csv_text)
            self.assertIn("monologue_text", csv_text)


class TestHighlightSpacing(unittest.TestCase):
    """Half-horizon temporal spacing + Ret 1m same-bar uniqueness."""

    @staticmethod
    def _row(
        idx: int,
        utt: str,
        *,
        ret_1m: float = 0.01,
        ret_3m: float = 0.01,
        ret_5m: float = 0.01,
        dpx_1m: float | None = None,
        dpx_3m: float | None = None,
        dpx_5m: float | None = None,
        bar_ts: str | None = None,
        ret_from_call: float | None = None,
        bar_close: float | None = None,
    ) -> ReactionRow:
        # Default dpx = ret so synthetic ranking tests keep their relative order.
        return ReactionRow(
            index=idx,
            utterance_utc=utt,
            start_sec=0.0,
            end_sec=1.0,
            speaker="X",
            speaker_role=None,
            snippet="s",
            highlight=False,
            bar_matched=True,
            bar_ts_utc=bar_ts,
            bar_close=bar_close,
            ret_1m=ret_1m,
            ret_3m=ret_3m,
            ret_5m=ret_5m,
            volume_1m=100.0,
            dpx_1m=ret_1m if dpx_1m is None else dpx_1m,
            dpx_3m=ret_3m if dpx_3m is None else dpx_3m,
            dpx_5m=ret_5m if dpx_5m is None else dpx_5m,
            ret_from_call_start=ret_from_call,
        )

    def test_5m_cluster_keeps_one(self) -> None:
        # Four hits 20s apart — all within 150s of the strongest.
        rows = [
            self._row(0, "2026-07-30T21:10:00Z", ret_5m=0.08),
            self._row(1, "2026-07-30T21:10:20Z", ret_5m=0.09),  # strongest
            self._row(2, "2026-07-30T21:10:40Z", ret_5m=0.07),
            self._row(3, "2026-07-30T21:11:00Z", ret_5m=0.06),
            self._row(4, "2026-07-30T21:20:00Z", ret_5m=0.05),  # far
        ]
        sel, diag = select_c1_indices_for_horizon(
            rows, "5m", top_k=12, percentile_floor=0, min_clear=1
        )
        self.assertEqual(diag["min_gap_sec"], 150.0)
        self.assertIn(1, sel)
        self.assertIn(4, sel)
        self.assertEqual(sel & {0, 2, 3}, set())
        self.assertGreaterEqual(
            diag["n_suppressed_spacing"] + diag["n_suppressed_same_spot"], 3
        )

    def test_1m_denser_than_5m_on_same_cluster(self) -> None:
        rows = [
            self._row(0, "2026-07-30T21:10:00Z", ret_1m=0.08, ret_5m=0.08),
            self._row(1, "2026-07-30T21:10:20Z", ret_1m=0.09, ret_5m=0.09),
            self._row(2, "2026-07-30T21:10:40Z", ret_1m=0.07, ret_5m=0.07),
            self._row(3, "2026-07-30T21:11:00Z", ret_1m=0.06, ret_5m=0.06),
        ]
        sel_1m, _ = select_c1_indices_for_horizon(
            rows, "1m", top_k=12, percentile_floor=0, min_clear=1
        )
        sel_5m, _ = select_c1_indices_for_horizon(
            rows, "5m", top_k=12, percentile_floor=0, min_clear=1
        )
        self.assertGreater(len(sel_1m), len(sel_5m))
        self.assertEqual(len(sel_5m), 1)

    def test_5m_keeps_pair_beyond_gap(self) -> None:
        rows = [
            self._row(0, "2026-07-30T21:10:00Z", ret_5m=0.10),
            self._row(1, "2026-07-30T21:12:40Z", ret_5m=0.09),  # 160s later
        ]
        sel, _ = select_c1_indices_for_horizon(
            rows, "5m", top_k=12, percentile_floor=0, min_clear=1
        )
        self.assertEqual(sel, {0, 1})

    def test_weaker_neighbor_within_gap_suppressed(self) -> None:
        rows = [
            self._row(0, "2026-07-30T21:10:00Z", ret_3m=0.10),
            self._row(1, "2026-07-30T21:11:00Z", ret_3m=0.05),  # 60s < 90s
        ]
        sel, diag = select_c1_indices_for_horizon(
            rows, "3m", top_k=12, percentile_floor=0, min_clear=1
        )
        self.assertEqual(sel, {0})
        self.assertEqual(diag["min_gap_sec"], 90.0)
        self.assertEqual(diag["n_suppressed_spacing"], 1)

    def test_1m_same_spot_rejects_shared_bar(self) -> None:
        # >30s apart so time-gap alone would keep both; same defining bar → one.
        call_at = pd.Timestamp("2026-07-30T21:00:00Z")
        bars = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(
                    [
                        "2026-07-30T21:00:00Z",
                        "2026-07-30T21:10:00Z",
                        "2026-07-30T21:11:00Z",
                    ],
                    utc=True,
                ),
                "close": [100.0, 101.0, 102.0],
                "volume": [10.0, 20.0, 30.0],
            }
        )
        # Both join to 21:10 defining bar; stronger |ret_1m| wins.
        rows = [
            self._row(
                0,
                "2026-07-30T21:10:10Z",
                ret_1m=0.04,
                ret_from_call=0.01,
                bar_ts="2026-07-30T21:10:00Z",
                bar_close=101.0,
            ),
            self._row(
                1,
                "2026-07-30T21:10:50Z",
                ret_1m=0.08,
                ret_from_call=0.01,
                bar_ts="2026-07-30T21:10:00Z",
                bar_close=101.0,
            ),
        ]
        sel, diag = select_c1_indices_for_horizon(
            rows,
            "1m",
            top_k=12,
            percentile_floor=0,
            min_clear=1,
            bars=bars,
            call_at=call_at,
        )
        self.assertEqual(sel, {1})
        self.assertGreaterEqual(diag["n_suppressed_same_spot"], 1)

    def test_3m_same_defining_bar_keeps_strongest(self) -> None:
        # Far enough for the 90s gap, but same defining bar_ts → one winner.
        rows = [
            self._row(
                0,
                "2026-07-30T21:10:10Z",
                ret_3m=0.04,
                bar_ts="2026-07-30T21:10:00Z",
            ),
            self._row(
                1,
                "2026-07-30T21:12:00Z",
                ret_3m=0.08,
                bar_ts="2026-07-30T21:10:00Z",
            ),
        ]
        sel, diag = select_c1_indices_for_horizon(
            rows, "3m", top_k=12, percentile_floor=0, min_clear=1
        )
        self.assertEqual(sel, {1})
        self.assertGreaterEqual(diag["n_suppressed_same_spot"], 1)


class TestHighlightPlacement(unittest.TestCase):
    """Discrete defining-bar placement (last close at/before speech)."""

    @staticmethod
    def _minute_bars(call_at: str, closes: list[float]) -> tuple[pd.DataFrame, pd.Timestamp]:
        t0 = pd.Timestamp(call_at)
        rows = [
            {
                "ts_utc": t0 + pd.Timedelta(minutes=i),
                "close": closes[i],
                "volume": 100.0,
            }
            for i in range(len(closes))
        ]
        return pd.DataFrame(rows), t0

    def test_snaps_to_last_bar_at_or_before(self) -> None:
        bars, call_at = self._minute_bars(
            "2026-07-30T21:00:00Z",
            [100.0, 100.0, 90.0, 110.0],
        )
        # Midway 21:02 → 21:03: defining bar is 21:02 close 90 (−10% from call).
        utt = call_at + pd.Timedelta(minutes=2, seconds=30)
        place = resolve_highlight_placement(
            bars,
            call_at=call_at,
            utterance_utc=utt,
            ret_from_call_start=None,
        )
        self.assertEqual(place.match_kind, "defining_bar")
        self.assertEqual(place.utterance_utc, utt)
        self.assertEqual(place.bar_ts, call_at + pd.Timedelta(minutes=2))
        self.assertAlmostEqual(place.bar_close, 90.0)
        self.assertEqual(place.matched_pct, -10.0)

    def test_fallback_when_empty_bars(self) -> None:
        bars = pd.DataFrame({"ts_utc": [], "close": [], "volume": []})
        utt = pd.Timestamp("2026-07-30T21:01:15Z")
        place = resolve_highlight_placement(
            bars,
            call_at=None,
            utterance_utc=utt,
            ret_from_call_start=None,
            fallback_close=99.5,
        )
        self.assertEqual(place.match_kind, "fallback")
        self.assertAlmostEqual(place.bar_close, 99.5)


if __name__ == "__main__":
    unittest.main()
