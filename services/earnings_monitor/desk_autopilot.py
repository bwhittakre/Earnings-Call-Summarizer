"""Run the claims-desk autopilot for one ticker after a novelty_view write or onboard.

Wraps ``scripts._desk_autopilot.run_for_ticker``.  Never raises — failures
are caught, logged, and returned as ``{"status": "error"}``.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)


def run_autopilot_for_ticker(
    *,
    repo_root: Path | str,
    ticker: str,
    fiscal_period: str,
    budget_usd: float = 1.0,
    api_key: str | None = None,
) -> dict:
    """Run the autopilot pipeline for *ticker* and return a status dict.

    Respects the ``DESK_AUTOPILOT=0`` kill switch (checked inside
    ``run_for_ticker``; returns ``{"status": "skipped", "reason": "kill_switch"}``
    when the env var is set).

    Returns a dict with at least a ``"status"`` key:
      - ``"ok"``: autopilot ran successfully
      - ``"skipped"``: gold ticker or kill switch
      - ``"error"``: exception caught
    """
    want = str(ticker).strip().upper()

    # Kill-switch checked here too so callers get a clean status dict.
    if os.getenv("DESK_AUTOPILOT", "1") == "0":
        return {"status": "skipped", "reason": "kill_switch", "ticker": want}

    root = Path(repo_root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from scripts._desk_autopilot import run_for_ticker  # type: ignore[import]
        from scripts._desk_catalog_overlay import load_overlay  # type: ignore[import]
        from scripts._desk_retrieval import GOLD_TICKERS  # type: ignore[import]
        from scripts._desk_trees_v2_catalogs import OPS_TREES  # type: ignore[import]
        from scripts._desk_trees_v2_hc_catalogs import HC_TREES  # type: ignore[import]
    except ImportError as exc:
        LOG.warning("desk autopilot import failed for %s: %s", want, exc)
        return {"status": "error", "reason": "import_error", "detail": str(exc)}

    if want in GOLD_TICKERS:
        return {"status": "skipped", "reason": "gold_ticker", "ticker": want}

    overlays = {
        "ops": load_overlay("ops"),
        "hc": load_overlay("hc"),
    }
    hand_typed_by_book = {
        "ops": list(OPS_TREES),
        "hc": list(HC_TREES),
    }

    effective_api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
    client = None
    if effective_api_key:
        try:
            from src.llm.anthropic_client import AnthropicClient  # type: ignore[import]
            client = AnthropicClient(
                api_key=effective_api_key,
                model="claude-sonnet-4-5",
                max_retries=1,
            )
        except Exception as exc:
            LOG.warning("autopilot: could not build LLM client for %s: %s", want, exc)

    import uuid
    run_id = str(uuid.uuid4())

    try:
        stats = run_for_ticker(
            want,
            budget_usd=budget_usd,
            dry_run=False,
            client=client,
            plan_only=(client is None),
            overlays=overlays,
            hand_typed_by_book=hand_typed_by_book,
            run_id=run_id,
            api_key=effective_api_key,
        )
        stats["status"] = "ok"
        return stats
    except Exception as exc:
        LOG.exception("desk autopilot failed for %s %s", want, fiscal_period)
        return {"status": "error", "reason": str(exc), "ticker": want}
