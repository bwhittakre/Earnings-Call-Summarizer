"""Sector presets embedded into Rank IC / consolidated HTML reports."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence


def _default_sectors_dir(repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root) / "config" / "sectors"
    here = Path(__file__).resolve().parent
    return here.parent / "config" / "sectors"


def load_sector_presets(
    universe: Sequence[str],
    *,
    sectors_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, list[str]]:
    """Load ``config/sectors/*.txt`` presets intersected with *universe*.

    Only tickers present in *universe* are kept (order preserved from each
    sector file). Empty / comment-only files are omitted. Hidden stems
    (starting with ``.``) are skipped. Includes ``quartr_*`` lists when present.
    """
    directory = Path(sectors_dir) if sectors_dir else _default_sectors_dir(repo_root)
    available = {
        str(ticker).strip().upper()
        for ticker in universe
        if str(ticker).strip()
    }
    presets: dict[str, list[str]] = {}
    if not directory.is_dir():
        return presets
    for path in sorted(directory.glob("*.txt")):
        stem = path.stem
        if stem.startswith("."):
            continue
        ordered: list[str] = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key = line.upper()
            if key not in available or key in ordered:
                continue
            ordered.append(key)
        if ordered:
            presets[stem] = ordered
    return presets
