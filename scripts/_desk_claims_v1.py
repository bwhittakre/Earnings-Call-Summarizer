"""Claims desk v1: typed cite + follow-up resolver for the 15-row pilot.

One object: type, clock, state, cite, follow-up cite.
Does not reuse desk v1 first-verbatim as the resolver.
Does not read transcripts_raw. Does not retune Path ID.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_path_id_v1 import (  # noqa: E402
    LOCKED_GENERATED_AT,
    SPLIT,
    _usable_excerpt,
    quarter_for_fiscal,
)

CASE_STUDY_ID = "desk_claims_v1"
DIMENSION = "competitive_position"
CLAIM_TYPES = (
    "printed_fact",
    "completed_announcement",
    "forward_clock",
    "pending_close",
)
PROMISE_TYPES = ("forward_clock", "pending_close")
STATES = ("open", "kept", "slipped", "subject-changed")
DELIVERY_STATES = ("delivered", "missed", "unresolved", "not-a-promise")

BEATS: tuple[dict[str, object], ...] = (
    {
        "beat_id": "aep-bookings",
        "title": "Adobe Experience Platform book of business",
        "tickers": ("ADBE",),
        "objects": ("Adobe Experience Platform", "Experience Platform", "Real-time CDP"),
    },
    {
        "beat_id": "flex",
        "title": "Autodesk Flex",
        "tickers": ("ADSK",),
        "objects": ("Flex",),
    },
    {
        "beat_id": "slack-connect",
        "title": "Slack Connect",
        "tickers": ("CRM",),
        "objects": ("Slack Connect", "Slack"),
    },
    {
        "beat_id": "cloud-paks",
        "title": "IBM Cloud Paks",
        "tickers": ("IBM",),
        "objects": ("Cloud Paks",),
    },
    {
        "beat_id": "lightbox",
        "title": "Intuit Lightbox",
        "tickers": ("INTU",),
        "objects": ("Lightbox",),
    },
    {
        "beat_id": "windows-365",
        "title": "Windows 365 Cloud PC",
        "tickers": ("MSFT",),
        "objects": ("Windows 365", "Cloud PC"),
    },
    {
        "beat_id": "oci",
        "title": "OCI mix / multicloud",
        "tickers": ("ORCL",),
        "objects": ("OCI",),
    },
    {
        "beat_id": "foundation-model-cloud",
        "title": "Foundation-model cloud (OpenAI / watsonx)",
        "tickers": ("MSFT", "IBM", "ORCL", "ADBE"),
        "objects": ("Azure OpenAI", "OpenAI", "watsonx"),
    },
    {
        "beat_id": "firefly-indemnity",
        "title": "Firefly content indemnification",
        "tickers": ("ADBE",),
        "objects": ("indemnification",),
    },
    {
        "beat_id": "pending-close",
        "title": "Pending close",
        "tickers": ("CRM", "ADSK"),
        "objects": ("Informatica", "digital twin"),
    },
    {
        "beat_id": "amd-cluster",
        "title": "Oracle AMD cluster",
        "tickers": ("ORCL",),
        "objects": ("AMD", "MI355X"),
    },
)

# Hand-labels for the 15 Phase 2 pilot keys. Object tokens come from the cite.
CATALOG: tuple[dict[str, object], ...] = (
    {
        "ticker": "ADBE",
        "period": "2021-Q2",
        "claim_type": "printed_fact",
        "objects": ("Adobe Experience Platform", "Experience Platform", "Real-time CDP"),
        "clock_due_next": False,
        "beat_id": "aep-bookings",
        "origin": "pilot",
    },
    {
        "ticker": "ADSK",
        "period": "2021-Q2",
        "claim_type": "forward_clock",
        "objects": ("Flex",),
        "clock_due_next": True,
        "beat_id": "flex",
        "origin": "pilot",
        "delivery": "delivered",
        "delivery_basis": (
            "Next-quarter cite treats Flex as live business "
            "('we're seeing with Flex' / 'Flex business coming in'), "
            "not merely a restated launch date."
        ),
        "coverage_summary": (
            "Next quarter treated Flex as live usage mix — net new, "
            "occasional, and advanced-product buyers — not a restated "
            "launch date."
        ),
    },
    {
        "ticker": "CRM",
        "period": "2021-Q2",
        "claim_type": "printed_fact",
        "objects": ("Slack Connect", "Slack"),
        "clock_due_next": False,
        "beat_id": "slack-connect",
        "origin": "pilot",
        "coverage_summary": (
            "Next quarter restated Slack Connect adoption at 176% "
            "year-over-year and described retailers using it as a "
            "Cyber Week command center."
        ),
    },
    {
        "ticker": "IBM",
        "period": "2021-Q2",
        "claim_type": "printed_fact",
        "objects": ("Cloud Paks",),
        "clock_due_next": False,
        "beat_id": "cloud-paks",
        "origin": "pilot",
    },
    {
        "ticker": "INTU",
        "period": "2021-Q2",
        "claim_type": "printed_fact",
        "objects": ("Lightbox",),
        "clock_due_next": False,
        "beat_id": "lightbox",
        "origin": "pilot",
        "coverage_summary": (
            "Next quarter stayed on Lightbox and framed partner trust as "
            "room for further credit-card and loan penetration."
        ),
    },
    {
        "ticker": "MSFT",
        "period": "2021-Q2",
        "claim_type": "completed_announcement",
        "objects": ("Windows 365", "Cloud PC"),
        "clock_due_next": False,
        "beat_id": "windows-365",
        "origin": "pilot",
    },
    {
        "ticker": "ORCL",
        "period": "2021-Q2",
        "claim_type": "printed_fact",
        "objects": ("OCI",),
        "clock_due_next": False,
        "beat_id": "oci",
        "origin": "pilot",
    },
    {
        "ticker": "MSFT",
        "period": "2022-Q4",
        "claim_type": "completed_announcement",
        "objects": ("OpenAI",),
        "clock_due_next": False,
        "beat_id": "foundation-model-cloud",
        "origin": "pilot",
        "coverage_summary": (
            "Next quarter followed the exclusive OpenAI cloud announcement "
            "with Azure OpenAI Service at 2,500 customers, up 10x."
        ),
    },
    {
        "ticker": "MSFT",
        "period": "2023-Q1",
        "claim_type": "printed_fact",
        "objects": ("Azure OpenAI", "OpenAI"),
        "clock_due_next": False,
        "beat_id": "foundation-model-cloud",
        "origin": "pilot",
    },
    {
        "ticker": "ADBE",
        "period": "2023-Q2",
        "claim_type": "completed_announcement",
        "objects": ("indemnification",),
        "clock_due_next": False,
        "beat_id": "firefly-indemnity",
        "origin": "pilot",
    },
    {
        "ticker": "IBM",
        "period": "2023-Q2",
        "claim_type": "completed_announcement",
        "objects": ("watsonx",),
        "clock_due_next": False,
        "beat_id": "foundation-model-cloud",
        "origin": "pilot",
    },
    {
        "ticker": "ADSK",
        "period": "2023-Q3",
        "claim_type": "forward_clock",
        "objects": ("Flex",),
        "clock_due_next": False,
        "beat_id": "flex",
        "origin": "pilot",
        "delivery": "unresolved",
        "delivery_basis": (
            "Clock is fiscal '25/'26. Next quarter is silent on Flex; "
            "silence before the clock is not a miss."
        ),
    },
    {
        "ticker": "CRM",
        "period": "2025-Q1",
        "claim_type": "pending_close",
        "objects": ("Informatica",),
        "clock_due_next": False,
        "beat_id": "pending-close",
        "origin": "pilot",
        "delivery": "unresolved",
        "delivery_basis": (
            "Pending Informatica close. No next-quarter cite that the "
            "deal closed or died."
        ),
    },
    {
        "ticker": "ORCL",
        "period": "2025-Q1",
        "claim_type": "printed_fact",
        "objects": ("AMD", "MI355X"),
        "clock_due_next": False,
        "beat_id": "amd-cluster",
        "origin": "pilot",
    },
    {
        "ticker": "ADSK",
        "period": "2026-Q1",
        "claim_type": "pending_close",
        "objects": ("digital twin", "40 billion"),
        "clock_due_next": False,
        "beat_id": "pending-close",
        "origin": "pilot",
        "delivery": "unresolved",
        "delivery_basis": (
            "No next quarter in the locked book, so the TAM/digital-twin "
            "clock cannot be scored."
        ),
    },
)

# Backfill kept rows are not in CATALOG. Hand-written from those cites only.
COVERAGE_SUMMARIES: dict[tuple[str, str], str] = {
    ("CRM", "2021-Q3"): (
        "Next quarter reported Slack Q4 revenue of $312 million, ahead of "
        "$285 million guidance, as the first standalone Slack print."
    ),
    ("CRM", "2024-Q3"): (
        "Next quarter kept Slack in the story via a DOGE/government "
        "coordination cite, not a restated Foundations launch."
    ),
    ("IBM", "2023-Q4"): (
        "Next quarter raised the watsonx and generative-AI book of business "
        "to greater than $1 billion with sequential growth."
    ),
    ("ORCL", "2024-Q2"): (
        "Next quarter added AWS alongside Azure and Google as clouds "
        "offering OCI."
    ),
    ("ORCL", "2024-Q4"): (
        "Next quarter covered OpenAI, with xAI and Meta, as models on a new "
        "Oracle AI Data Platform for existing database customers."
    ),
}


def assert_locked_stamp(generated_at: object) -> None:
    stamp = str(generated_at or "")
    if stamp != LOCKED_GENERATED_AT:
        raise SystemExit(
            f"desk_claims_v1 refuses stamp {stamp!r}; locked {LOCKED_GENERATED_AT!r}"
        )


def next_fiscal_period(fiscal_period: str) -> str | None:
    text = str(fiscal_period or "").strip().upper()
    match = re.fullmatch(r"FY(\d{4})-Q([1-4])", text)
    if not match:
        return None
    year, quarter = int(match.group(1)), int(match.group(2))
    if quarter == 4:
        return f"FY{year + 1}-Q1"
    return f"FY{year}-Q{quarter + 1}"


def excerpt_mentions_object(excerpt: str, token: str) -> bool:
    text = str(excerpt or "")
    needle = str(token or "").strip()
    if not text or not needle:
        return False
    parts = [re.escape(part) for part in needle.split() if part]
    if not parts:
        return False
    pattern = r"\b" + r"\s+".join(parts) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def evidence_hits_objects(
    excerpt: str,
    objects: Sequence[str],
) -> bool:
    return any(excerpt_mentions_object(excerpt, token) for token in objects)


def beat_by_id(beat_id: str) -> dict[str, object]:
    for beat in BEATS:
        if beat["beat_id"] == beat_id:
            return beat
    raise KeyError(beat_id)


def beat_for_excerpt(ticker: str, excerpt: str) -> dict[str, object] | None:
    """Longest object token among beats that allow this ticker."""
    want = str(ticker or "").upper()
    best: dict[str, object] | None = None
    best_len = -1
    for beat in BEATS:
        allowed = {str(item).upper() for item in (beat.get("tickers") or ())}
        if want not in allowed:
            continue
        for token in beat.get("objects") or ():
            if excerpt_mentions_object(excerpt, str(token)) and len(str(token)) > best_len:
                best = beat
                best_len = len(str(token))
    return best


def collect_backfill(
    desk_rows: Sequence[Mapping[str, object]],
    pilot_keys: set[tuple[str, str]],
) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in desk_rows:
        ticker = str(row.get("ticker") or "").upper()
        period = str(row.get("period") or "")
        key = (ticker, period)
        if not ticker or not period or key in pilot_keys or key in seen:
            continue
        excerpt = str(row.get("excerpt") or "")
        if not excerpt.strip():
            continue
        beat = beat_for_excerpt(ticker, excerpt)
        if beat is None:
            continue
        seen.add(key)
        found.append(
            {
                "ticker": ticker,
                "period": period,
                "claim_type": "printed_fact",
                "objects": tuple(str(item) for item in (beat.get("objects") or ())),
                "clock_due_next": False,
                "beat_id": str(beat["beat_id"]),
                "origin": "backfill",
            }
        )
    found.sort(key=lambda item: (str(item["ticker"]), str(item["period"])))
    return found


def group_beats(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    grouped: list[dict[str, object]] = []
    for beat in BEATS:
        members = [
            row for row in rows if str(row.get("beat_id") or "") == beat["beat_id"]
        ]
        if not members:
            continue
        states = {name: 0 for name in STATES}
        deliveries = {name: 0 for name in DELIVERY_STATES}
        for row in members:
            states[str(row.get("state") or "open")] += 1
            deliveries[str(row.get("delivery") or "not-a-promise")] += 1
        grouped.append(
            {
                "beat_id": beat["beat_id"],
                "title": beat["title"],
                "n_rows": len(members),
                "tickers": sorted({str(row.get("ticker") or "") for row in members}),
                "states": states,
                "deliveries": deliveries,
                "keys": [
                    f"{row.get('ticker')} {row.get('period')}" for row in members
                ],
            }
        )
    return grouped


def all_verified_evidence(quarter: Mapping[str, object] | None) -> list[dict[str, object]]:
    if not quarter:
        return []
    found: list[dict[str, object]] = []
    for novelty in quarter.get("novelties") or []:
        if not isinstance(novelty, dict):
            continue
        dimension = str(novelty.get("dimension") or "")
        for evidence in novelty.get("evidence") or []:
            if not isinstance(evidence, dict) or not _usable_excerpt(evidence):
                continue
            found.append(
                {
                    "dimension": dimension,
                    "claim": evidence.get("claim"),
                    "excerpt": evidence.get("excerpt"),
                    "status": str(evidence.get("status") or ""),
                    "verified": True,
                }
            )
    return found


def first_object_hit(
    evidence_rows: Sequence[Mapping[str, object]],
    objects: Sequence[str],
) -> dict[str, object] | None:
    for row in evidence_rows:
        if evidence_hits_objects(str(row.get("excerpt") or ""), objects):
            return dict(row)
    return None


def next_existing_quarter(
    novelty_view: Mapping[str, object] | None,
    fiscal_period: str,
) -> tuple[str | None, dict | None]:
    current = next_fiscal_period(fiscal_period)
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        quarter = quarter_for_fiscal(novelty_view, current)
        if quarter:
            return current, quarter
        current = next_fiscal_period(current)
    return None, None


def resolve_delivery(
    *,
    claim_type: str,
    hand_label: str | None,
    hand_basis: str | None,
) -> tuple[str, str | None]:
    """Whether a dated promise came true. Independent of kept/slipped.

    Printed facts and completed announcements are not promises.
    A due-clock silence is slipped, not automatically missed.
    Delivery is hand-labeled from seed + follow-up cites only.
    """
    if claim_type not in CLAIM_TYPES:
        raise ValueError(f"unknown claim_type {claim_type!r}")
    if claim_type not in PROMISE_TYPES:
        return "not-a-promise", None
    label = str(hand_label or "unresolved").strip() or "unresolved"
    if label not in DELIVERY_STATES or label == "not-a-promise":
        raise ValueError(f"invalid delivery {label!r} for {claim_type}")
    basis = str(hand_basis or "").strip() or None
    return label, basis


def resolve_state(
    *,
    claim_type: str,
    clock_due_next: bool,
    next_exists: bool,
    matched: bool,
) -> str:
    if claim_type not in CLAIM_TYPES:
        raise ValueError(f"unknown claim_type {claim_type!r}")
    if not next_exists:
        return "open"
    if matched:
        return "kept"
    if claim_type == "forward_clock" and clock_due_next:
        return "slipped"
    if claim_type in ("forward_clock", "pending_close"):
        return "open"
    return "subject-changed"


def needs_coverage_summary(state: str, delivery: str) -> bool:
    return state == "kept" or delivery == "delivered"


def coverage_for(
    catalog_row: Mapping[str, object],
    ticker: str,
    period: str,
) -> str | None:
    from_catalog = str(catalog_row.get("coverage_summary") or "").strip()
    if from_catalog:
        return from_catalog
    return COVERAGE_SUMMARIES.get((ticker, period))


def deliver_rate_counts(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    delivered = sum(1 for row in rows if row.get("delivery") == "delivered")
    missed = sum(1 for row in rows if row.get("delivery") == "missed")
    scoreable = delivered + missed
    return {
        "delivered": delivered,
        "missed": missed,
        "n_scoreable": scoreable,
        "deliver_rate": (delivered / scoreable) if scoreable else None,
    }


def build_deliver_rates(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_ticker = []
    for ticker in sorted({str(row.get("ticker") or "") for row in rows if row.get("ticker")}):
        counts = deliver_rate_counts(
            [row for row in rows if str(row.get("ticker") or "") == ticker]
        )
        counts["ticker"] = ticker
        by_ticker.append(counts)
    return {"book": deliver_rate_counts(rows), "by_ticker": by_ticker}


def follow_up_citation(
    ticker: str,
    next_fiscal: str | None,
    hit: Mapping[str, object] | None,
) -> str | None:
    if not next_fiscal:
        return None
    dimension = str((hit or {}).get("dimension") or DIMENSION)
    status = str((hit or {}).get("status") or "missing")
    pointer = f"{ticker} {next_fiscal} novelty_view {dimension}"
    if hit is None:
        return pointer
    return f"{pointer} {status}"


def resolve_claim(
    catalog_row: Mapping[str, object],
    desk_row: Mapping[str, object],
    novelty_view: Mapping[str, object] | None,
) -> dict[str, object]:
    ticker = str(catalog_row.get("ticker") or "").upper()
    period = str(catalog_row.get("period") or desk_row.get("period") or "")
    fiscal = str(desk_row.get("fiscal_period") or "")
    claim_type = str(catalog_row.get("claim_type") or "")
    objects = tuple(str(item) for item in (catalog_row.get("objects") or ()))
    clock_due_next = bool(catalog_row.get("clock_due_next"))
    next_fiscal, next_quarter = next_existing_quarter(novelty_view, fiscal)
    hit = first_object_hit(all_verified_evidence(next_quarter), objects)
    state = resolve_state(
        claim_type=claim_type,
        clock_due_next=clock_due_next,
        next_exists=next_fiscal is not None,
        matched=hit is not None,
    )
    delivery, delivery_basis = resolve_delivery(
        claim_type=claim_type,
        hand_label=str(catalog_row.get("delivery") or "") or None,
        hand_basis=str(catalog_row.get("delivery_basis") or "") or None,
    )
    return {
        "ticker": ticker,
        "period": period,
        "fiscal_period": fiscal,
        "claim_type": claim_type,
        "objects": list(objects),
        "clock_due_next": clock_due_next,
        "excerpt": desk_row.get("excerpt"),
        "citation": desk_row.get("source"),
        "next_fiscal_period": next_fiscal,
        "follow_up_excerpt": None if hit is None else hit.get("excerpt"),
        "follow_up_status": None if hit is None else hit.get("status"),
        "follow_up_dimension": None if hit is None else hit.get("dimension"),
        "follow_up_citation": follow_up_citation(ticker, next_fiscal, hit),
        "state": state,
        "delivery": delivery,
        "delivery_basis": delivery_basis,
        "coverage_summary": coverage_for(catalog_row, ticker, period),
        "path_hit": desk_row.get("hit"),
        "beat_id": str(catalog_row.get("beat_id") or ""),
        "origin": str(catalog_row.get("origin") or "pilot"),
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _novelty_path(ticker: str) -> Path:
    return (
        ROOT
        / "Structured Narrative"
        / "output"
        / ticker
        / "json"
        / "novelty_view.json"
    )


def build_claims_desk(
    desk_payload: Mapping[str, object],
    novelty_by_ticker: Mapping[str, Mapping[str, object] | None],
) -> dict[str, object]:
    assert_locked_stamp(desk_payload.get("generated_at"))
    by_key = {
        (str(row.get("ticker") or ""), str(row.get("period") or "")): row
        for row in (desk_payload.get("rows") or [])
        if isinstance(row, dict)
    }
    rows: list[dict[str, object]] = []
    catalog_items = list(CATALOG) + collect_backfill(
        [row for row in (desk_payload.get("rows") or []) if isinstance(row, dict)],
        {(str(item["ticker"]), str(item["period"])) for item in CATALOG},
    )
    for item in catalog_items:
        key = (str(item["ticker"]), str(item["period"]))
        desk_row = by_key.get(key)
        if desk_row is None:
            raise SystemExit(f"desk row missing for {key}")
        ticker = str(item["ticker"])
        rows.append(resolve_claim(item, desk_row, novelty_by_ticker.get(ticker)))
    for row in rows:
        if needs_coverage_summary(str(row["state"]), str(row["delivery"])) and not row.get(
            "coverage_summary"
        ):
            raise SystemExit(
                f"coverage_summary missing for {row.get('ticker')} {row.get('period')}"
            )
    counts = {name: 0 for name in STATES}
    delivery_counts = {name: 0 for name in DELIVERY_STATES}
    for row in rows:
        counts[str(row["state"])] += 1
        delivery_counts[str(row["delivery"])] += 1
    beats = group_beats(rows)
    return {
        "generated_at": LOCKED_GENERATED_AT,
        "case_study_id": CASE_STUDY_ID,
        "split": SPLIT,
        "caption": (
            "Claims desk v1. State is a follow-up cite on the same object, "
            "not a Path ID hit/miss. Delivery is whether a dated promise "
            "came true — hand-labeled from seed + follow-up cites, not "
            "inferred from kept. Flex launch must be kept and delivered. "
            "Backfill is same-beat desk cites only, not the remaining 125."
        ),
        "n_rows": len(rows),
        "n_pilot": sum(1 for row in rows if row.get("origin") == "pilot"),
        "n_backfill": sum(1 for row in rows if row.get("origin") == "backfill"),
        "counts": counts,
        "delivery_counts": delivery_counts,
        "deliver_rates": build_deliver_rates(rows),
        "beats": beats,
        "rows": rows,
    }


def main() -> int:
    desk_path = (
        ROOT
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_path_id_v1.json"
    )
    desk_payload = _load_json(desk_path)
    novelty_by_ticker: dict[str, dict | None] = {}
    tickers = {str(item["ticker"]) for item in CATALOG}
    for row in desk_payload.get("rows") or []:
        if isinstance(row, dict) and row.get("ticker"):
            tickers.add(str(row["ticker"]))
    for ticker in sorted(tickers):
        path = _novelty_path(ticker)
        novelty_by_ticker[ticker] = _load_json(path) if path.is_file() else None
    payload = build_claims_desk(desk_payload, novelty_by_ticker)
    out = (
        ROOT
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_claims_v1.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(out)
    print("counts", payload["counts"])
    flex = next(
        row
        for row in payload["rows"]
        if row["ticker"] == "ADSK" and row["period"] == "2021-Q2"
    )
    if flex["state"] != "kept" or flex["delivery"] != "delivered":
        raise SystemExit(
            f"Flex bar failed: state={flex['state']!r} delivery={flex['delivery']!r}"
        )
    print("flex_bar kept delivered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
