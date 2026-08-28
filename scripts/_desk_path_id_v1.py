"""Join Path ID name-paths to novelty_view excerpts. Lab desk artifact.

Refuse unless Path ID generated_at matches the locked stamp.
Does not rewrite path_id_v1.json. Does not read transcripts_raw.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

LOCKED_GENERATED_AT = "2026-08-17T17:28:40+00:00"
DIMENSION = "competitive_position"
SPLIT = "asof-path-id-17aug-book-v1"
CASE_STUDY_ID = "desk_path_id_v1"


def assert_locked_stamp(generated_at: object) -> None:
    stamp = str(generated_at or "")
    if stamp != LOCKED_GENERATED_AT:
        raise SystemExit(
            f"desk_path_id_v1 refuses stamp {stamp!r}; locked {LOCKED_GENERATED_AT!r}"
        )


def fiscal_period_for(
    ticker: str,
    calendar_period: str,
    panel_rows: Sequence[Mapping[str, object]],
) -> str | None:
    """Map (ticker, calendar period) → fiscal_period from feature_panel rows."""
    want_t = str(ticker or "").upper()
    want_p = str(calendar_period or "")
    if not want_t or not want_p:
        return None
    for row in panel_rows:
        if str(row.get("ticker") or "").upper() != want_t:
            continue
        if str(row.get("period_end_calendar_quarter") or "") != want_p:
            continue
        fiscal = str(row.get("fiscal_period") or "").strip()
        if fiscal:
            return fiscal
    return None


def fiscal_map_from_rows(
    panel_rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for row in panel_rows:
        ticker = str(row.get("ticker") or "").upper()
        calendar = str(row.get("period_end_calendar_quarter") or "")
        fiscal = str(row.get("fiscal_period") or "").strip()
        if ticker and calendar and fiscal and (ticker, calendar) not in out:
            out[(ticker, calendar)] = fiscal
    return out


def load_feature_panel_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for raw in reader:
            rows.append(
                {
                    "ticker": str(raw.get("ticker") or ""),
                    "fiscal_period": str(raw.get("fiscal_period") or ""),
                    "period_end_calendar_quarter": str(
                        raw.get("period_end_calendar_quarter") or ""
                    ),
                }
            )
        return rows


def quarter_for_fiscal(
    novelty_view: Mapping[str, object] | None,
    fiscal_period: str,
) -> dict | None:
    if not novelty_view or not fiscal_period:
        return None
    quarters = novelty_view.get("quarters")
    if isinstance(quarters, dict):
        found = quarters.get(fiscal_period)
        return found if isinstance(found, dict) else None
    if isinstance(quarters, list):
        for item in quarters:
            if (
                isinstance(item, dict)
                and str(item.get("fiscal_period") or "") == fiscal_period
            ):
                return item
    return None


def _usable_excerpt(evidence: Mapping[str, object]) -> bool:
    if not evidence.get("verified"):
        return False
    return bool(str(evidence.get("excerpt") or "").strip())


def pick_excerpt(
    quarter: Mapping[str, object] | None,
    dimension: str = DIMENSION,
) -> dict[str, object]:
    """First verified verbatim, else first verified composite, else missing."""
    empty: dict[str, object] = {
        "claim": None,
        "excerpt": None,
        "excerpt_status": "missing",
        "novelty_magnitude": None,
        "rationale": None,
    }
    if not quarter:
        return empty
    block = None
    for novelty in quarter.get("novelties") or []:
        if isinstance(novelty, dict) and novelty.get("dimension") == dimension:
            block = novelty
            break
    if block is None:
        return empty
    first_verbatim = None
    first_composite = None
    for evidence in block.get("evidence") or []:
        if not isinstance(evidence, dict) or not _usable_excerpt(evidence):
            continue
        status = str(evidence.get("status") or "")
        if status == "verbatim" and first_verbatim is None:
            first_verbatim = evidence
        elif status == "composite" and first_composite is None:
            first_composite = evidence
    chosen = first_verbatim or first_composite
    if chosen is None:
        return {
            "claim": None,
            "excerpt": None,
            "excerpt_status": "missing",
            "novelty_magnitude": block.get("novelty_magnitude"),
            "rationale": block.get("rationale"),
        }
    return {
        "claim": chosen.get("claim"),
        "excerpt": chosen.get("excerpt"),
        "excerpt_status": str(chosen.get("status") or "missing"),
        "novelty_magnitude": block.get("novelty_magnitude"),
        "rationale": block.get("rationale"),
    }


def coverage_bucket(fiscal_period: str | None, excerpt_status: str) -> str:
    if not fiscal_period:
        return "missing_fiscal"
    if excerpt_status == "missing":
        return "missing_excerpt"
    return "joined"


def citation_source(
    ticker: str,
    fiscal_period: str | None,
    excerpt_status: str,
) -> str | None:
    if not fiscal_period:
        return None
    pointer = f"{ticker} {fiscal_period} novelty_view {DIMENSION}"
    if excerpt_status != "missing":
        return f"{pointer} {excerpt_status}"
    return pointer


def join_name_path(
    name_path: Mapping[str, object],
    fiscal_period: str | None,
    excerpt: Mapping[str, object],
) -> dict[str, object]:
    ticker = str(name_path.get("ticker") or "").upper()
    status = str(excerpt.get("excerpt_status") or "missing")
    claim = excerpt.get("claim") if fiscal_period else None
    text = excerpt.get("excerpt") if fiscal_period else None
    if status == "missing":
        claim = None
        text = None
    return {
        "period": str(name_path.get("period") or ""),
        "ticker": ticker,
        "fiscal_period": fiscal_period,
        "predicted": name_path.get("predicted"),
        "realized": name_path.get("realized"),
        "hit": name_path.get("hit"),
        "novelty_magnitude": excerpt.get("novelty_magnitude") if fiscal_period else None,
        "claim": claim,
        "excerpt": text,
        "excerpt_status": status if fiscal_period else "missing",
        "source": citation_source(ticker, fiscal_period, status),
        "rationale": excerpt.get("rationale") if fiscal_period else None,
    }


def build_desk_payload(
    path_id: Mapping[str, object],
    name_paths: Sequence[Mapping[str, object]],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    counts = {"joined": 0, "missing_fiscal": 0, "missing_excerpt": 0}
    for row in rows:
        bucket = coverage_bucket(
            str(row.get("fiscal_period") or "") or None,
            str(row.get("excerpt_status") or "missing"),
        )
        counts[bucket] += 1
    return {
        "case_study_id": CASE_STUDY_ID,
        "generated_at": path_id.get("generated_at"),
        "split": SPLIT,
        "sleeve": "software_cloud",
        "dimension": DIMENSION,
        "signal": "narrative_novelty",
        "path_id_case_study_pass": bool(path_id.get("case_study_pass")),
        "coverage": counts,
        "name_path_count": len(name_paths),
        "rows": list(rows),
    }


def load_novelty_view(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def main() -> None:
    sys.path.insert(0, str(ROOT))
    history = ROOT / "Structured Narrative" / "output"
    path_id_path = history / "cross_company" / "json" / "path_id_v1.json"
    path_id = json.loads(path_id_path.read_text(encoding="utf-8"))
    assert_locked_stamp(path_id.get("generated_at"))
    name_paths = list(path_id.get("name_paths") or [])
    fiscal_cache: dict[str, dict[tuple[str, str], str]] = {}
    novelty_cache: dict[str, dict | None] = {}
    rows: list[dict[str, object]] = []
    for name_path in name_paths:
        ticker = str(name_path.get("ticker") or "").upper()
        period = str(name_path.get("period") or "")
        if ticker not in fiscal_cache:
            panel_path = history / ticker / "csv" / "feature_panel.csv"
            fiscal_cache[ticker] = fiscal_map_from_rows(
                load_feature_panel_rows(panel_path)
            )
        fiscal = fiscal_cache[ticker].get((ticker, period))
        if ticker not in novelty_cache:
            novelty_cache[ticker] = load_novelty_view(
                history / ticker / "json" / "novelty_view.json"
            )
        excerpt = pick_excerpt(quarter_for_fiscal(novelty_cache[ticker], fiscal or ""))
        rows.append(join_name_path(name_path, fiscal, excerpt))
    payload = build_desk_payload(path_id, name_paths, rows)
    out = history / "cross_company" / "json" / "desk_path_id_v1.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "case_study_id": CASE_STUDY_ID,
                "generated_at": payload["generated_at"],
                "split": SPLIT,
                "coverage": payload["coverage"],
                "name_path_count": payload["name_path_count"],
                "wrote": str(out),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
