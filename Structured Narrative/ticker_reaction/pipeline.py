"""Orchestrate load -> sync diag -> reactions -> lag sweep -> C1 -> Output."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ticker_reaction.align import align_utterances, alignment_stats, utterance_wall_clock
from ticker_reaction.highlights import (
    apply_horizon_highlights,
    select_all_horizon_highlights,
    select_c1_indices_for_horizon,
)
from ticker_reaction.load_bars import bars_meta, load_bars
from ticker_reaction.load_transcript import load_anchors, load_transcript
from ticker_reaction.paths import event_slug
from ticker_reaction.reactions import (
    build_reaction_rows,
    null_return_counts,
    scores_at_times,
    summary_returns,
)
from ticker_reaction.report import write_outputs
from ticker_reaction.sync import (
    anchor_sanity,
    build_sync_diagnostics,
    join_health,
    lag_sensitivity_sweep,
    sync_contract,
)


def run_ticker_reaction(
    *,
    bars_path: Path,
    transcript_path: Path,
    anchors_path: Path,
    output_root: Path,
    ticker: str | None = None,
    quarter: str | None = None,
    timing_lag_sec: float = 0.0,
) -> dict[str, Any]:
    anchors = load_anchors(anchors_path)
    transcript = load_transcript(transcript_path)
    bars = load_bars(bars_path)

    ticker_u = (ticker or anchors.ticker or "UNK").upper()
    quarter_u = (quarter or anchors.fiscal_period or "UNKNOWN").upper()
    slug = event_slug(ticker_u, quarter_u)

    # load → align → early sync diagnostics (contract + join health + anchors)
    aligned = align_utterances(
        transcript, anchors, bars, timing_lag_sec=timing_lag_sec
    )
    call_end = None
    if transcript.last_end_sec is not None:
        call_end = utterance_wall_clock(anchors.call_at, transcript.last_end_sec)

    early_sync = {
        "sync_contract": sync_contract(
            anchors, call_end=call_end, timing_lag_sec=timing_lag_sec
        ),
        "join_health": join_health(aligned),
        "anchor_sanity": anchor_sanity(transcript, anchors, bars),
    }

    # → reaction metrics
    summary = summary_returns(bars, anchors, transcript)
    reactions = build_reaction_rows(
        aligned,
        bars,
        anchors=anchors,
        transcript=transcript,
        call_end=call_end,
    )

    # → lag sensitivity sweep (primary 1m C1 under clock shifts)
    def _select_from_pairs(pairs: list[tuple[int, datetime]]) -> set[int]:
        tmp = scores_at_times(bars, pairs)
        selected, _ = select_c1_indices_for_horizon(tmp, "1m")
        return selected

    lag_sweep = lag_sensitivity_sweep(
        aligned_base=aligned,
        bars=bars,
        score_and_select=_select_from_pairs,
    )

    # → C1 select for each horizon + finalize sync badge / exploratory gate
    by_horizon = select_all_horizon_highlights(reactions)
    aligned, reactions = apply_horizon_highlights(aligned, reactions, by_horizon)
    highlight_diag = {
        **by_horizon["1m"],
        "highlights_by_horizon": by_horizon,
        "default_view": "1m",
        "operator_soft_filter": False,
    }

    sync_diag = build_sync_diagnostics(
        aligned=aligned,
        anchors=anchors,
        transcript=transcript,
        bars=bars,
        lag_sweep=lag_sweep,
        timing_lag_sec=timing_lag_sec,
        call_end=call_end,
    )
    # Preserve early-sync keys (same content; badge/lag now finalized).
    sync_diag = {**early_sync, **sync_diag}
    highlight_diag = {
        **highlight_diag,
        "highlights_exploratory": sync_diag.get("highlights_exploratory"),
    }

    diagnostics: dict[str, Any] = {
        **bars_meta(bars),
        **alignment_stats(aligned, bars, anchors, transcript),
        **null_return_counts(reactions),
        **summary,
        **sync_diag,
        "highlights": highlight_diag,
        "highlights_by_horizon": by_horizon,
        "ticker": ticker_u,
        "fiscal_period": quarter_u,
        "event_slug": slug,
        "bars_path": str(bars_path),
        "transcript_path": str(transcript_path),
        "anchors_path": str(anchors_path),
        "caveats": [
            "Coincident reaction only; not causal attribution.",
            "Highlights = Top-K per horizon (|ret_1m|/|ret_3m|/|ret_5m|) with percentile floor.",
            "Quotes show full same-speaker monologue; scored unit is the trigger paragraph.",
            "Excel naive timestamps assumed America/New_York.",
            "After-hours liquidity and pre-call print can dominate minute moves.",
            "Do not over-interpret when sync_badge is fragile or suspect.",
            "Operator soft filter OFF by default (pure C1).",
        ],
    }

    paths = write_outputs(
        output_root=output_root,
        slug=slug,
        ticker=ticker_u,
        quarter=quarter_u,
        bars=bars,
        aligned=aligned,
        reactions=reactions,
        summary=summary,
        diagnostics=diagnostics,
    )

    return {
        "slug": slug,
        "ticker": ticker_u,
        "quarter": quarter_u,
        "diagnostics": diagnostics,
        "paths": {k: str(v) for k, v in paths.items()},
    }
