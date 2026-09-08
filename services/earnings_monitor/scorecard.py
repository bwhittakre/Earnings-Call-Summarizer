"""Rebuild the claims-desk call scorecard sidecar (and canvas) after a post_call.

Called automatically by ``service.py`` after the desk autopilot completes.
Never raises — failures are caught, logged, and returned as ``{"status": "error"}``.

Also writes a markdown Post-Call Brief to ``data/briefs/{TICKER}_{PERIOD}.md``
for each ticker/period that has a scorecard entry, so SAM can read it without
opening the dashboard.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)


def rebuild_scorecard(
    *,
    repo_root: Path | str,
    rebuild_canvas: bool = True,
) -> dict:
    """Rebuild ``data/desk_call_scorecard_v1.json`` (and optionally the canvas).

    Returns a dict with at least a ``"status"`` key:
      - ``"ok"``: rebuilt successfully
      - ``"error"``: exception caught (pipeline continues regardless)
    """
    root = Path(repo_root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from scripts._desk_call_scorecard import build_scorecard  # type: ignore[import]

        scorecard = build_scorecard()

        out_path = root / "data" / "desk_call_scorecard_v1.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        import json
        out_path.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")

        LOG.info(
            "scorecard: rebuilt %s (%d entries)",
            out_path.name,
            scorecard["n_entries"],
        )

        result: dict = {
            "status": "ok",
            "n_entries": scorecard["n_entries"],
            "path": str(out_path),
        }

    except Exception as exc:
        LOG.exception("scorecard rebuild failed")
        return {"status": "error", "reason": str(exc)}

    # ── Canvas regeneration (optional, best-effort) ──────────────────────────
    if rebuild_canvas:
        try:
            _rebuild_canvas(root)
            result["canvas"] = "ok"
        except Exception as exc:
            LOG.warning("scorecard canvas rebuild failed: %s", exc)
            result["canvas"] = f"error: {exc}"

    # ── Post-Call Briefs (best-effort, per ticker with a scored entry) ────────
    try:
        briefs_written = _write_briefs(root)
        result["briefs_written"] = briefs_written
    except Exception as exc:
        LOG.warning("brief auto-write failed: %s", exc)
        result["briefs_written"] = f"error: {exc}"

    return result


def _write_briefs(root: Path) -> int:
    """Write (or refresh) markdown briefs for every (ticker, period) in the scorecard.

    Writes to ``data/briefs/{TICKER}_{PERIOD}.md``.  Returns the number of files written.
    Does NOT raise — caller already handles exceptions.
    """
    import json

    sc_path = root / "data" / "desk_call_scorecard_v1.json"
    if not sc_path.is_file():
        return 0

    # Import here so the heavy module is only loaded when scorecard is being rebuilt.
    # Adjust sys.path so the import works regardless of cwd.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from services.earnings_monitor.dashboard.claims_brief import (  # type: ignore[import]
        generate_brief_markdown,
        load_brief_data,
    )

    entries = json.loads(sc_path.read_text(encoding="utf-8")).get("entries") or []
    briefs_dir = root / "data" / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for entry in entries:
        ticker = str(entry.get("ticker") or "").upper()
        period = str(entry.get("fiscal_period") or "")
        if not ticker or not period:
            continue
        try:
            brief = load_brief_data(ticker, period)
            if brief is None:
                continue
            md = generate_brief_markdown(brief)
            safe_period = period.replace("-", "")
            out = briefs_dir / f"{ticker}_{safe_period}_brief.md"
            out.write_text(md, encoding="utf-8")
            written += 1
        except Exception as exc:
            LOG.debug("brief write skipped %s %s: %s", ticker, period, exc)

    LOG.info("scorecard: wrote %d briefs to %s", written, briefs_dir)
    return written


def _rebuild_canvas(root: Path) -> None:
    """Regenerate the call-scorecard canvas TSX with the latest embedded data."""
    import json

    scorecard_path = root / "data" / "desk_call_scorecard_v1.json"
    if not scorecard_path.exists():
        raise FileNotFoundError(scorecard_path)

    entries = json.loads(scorecard_path.read_text("utf-8"))["entries"]
    compact = json.dumps(entries, separators=(",", ":")).replace("`", "\\`")

    # Locate the canvas generator and run it, or write inline if not present.
    gen_script = root / "scripts" / "_gen_scorecard_canvas.py"
    if gen_script.exists():
        import subprocess, sys as _sys
        subprocess.run(
            [_sys.executable, str(gen_script)],
            check=True,
            capture_output=True,
        )
        return

    # Fallback: write the canvas directly (same template as the generator).
    import os
    # Derive the canvases directory from the known Cursor projects path.
    project_slug = "c-Users-BobbyWhittaker-OneDrive-Cassius-Capital-Desktop-Earnings-Call-Summarizer"
    cursor_canvases = (
        Path(os.path.expanduser("~"))
        / ".cursor"
        / "projects"
        / project_slug
        / "canvases"
    )
    if not cursor_canvases.exists():
        LOG.warning("scorecard: canvas dir not found at %s, skipping", cursor_canvases)
        return

    canvas_path = cursor_canvases / "call-scorecard.canvas.tsx"
    if not canvas_path.exists():
        LOG.warning("scorecard: existing canvas not found at %s, skipping", canvas_path)
        return

    # Patch only the embedded data block — everything else stays unchanged.
    old_text = canvas_path.read_text("utf-8")
    import re
    patched = re.sub(
        r"(const RAW_ENTRIES: Entry\[\] = JSON\.parse\(`)[^`]*(`\);)",
        rf"\g<1>{compact}\g<2>",
        old_text,
        count=1,
    )
    if patched == old_text:
        LOG.warning("scorecard: could not locate RAW_ENTRIES block in canvas — skipped patch")
        return

    canvas_path.write_text(patched, encoding="utf-8")
    LOG.info("scorecard: patched canvas at %s", canvas_path)
