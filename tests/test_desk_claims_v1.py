"""Fixture tests for claims desk v1. Does not load live novelty_view."""
from __future__ import annotations

import json

from scripts._desk_claims_v1 import (
    CASE_STUDY_ID,
    LOCKED_GENERATED_AT,
    all_verified_evidence,
    beat_for_excerpt,
    build_deliver_rates,
    collect_backfill,
    deliver_rate_counts,
    excerpt_mentions_object,
    first_object_hit,
    group_beats,
    needs_coverage_summary,
    next_fiscal_period,
    resolve_claim,
    resolve_delivery,
    resolve_state,
)
from scripts._desk_path_id_v1 import pick_excerpt
from services.earnings_monitor.dashboard.rank_ic_lab import load_desk_claims_v1


def _flex_next_quarter() -> dict:
    return {
        "fiscal_period": "FY2022-Q3",
        "novelties": [
            {
                "dimension": "competitive_position",
                "evidence": [
                    {
                        "claim": "Flex launched",
                        "excerpt": (
                            "One of the things we're seeing with Flex is "
                            "exactly what we expected to see."
                        ),
                        "verified": True,
                        "status": "composite",
                    },
                    {
                        "claim": "Fusion 360 MAU",
                        "excerpt": (
                            "we ended the third quarter with 1 million "
                            "monthly active users"
                        ),
                        "verified": True,
                        "status": "verbatim",
                    },
                ],
            }
        ],
    }


def _catalog_flex() -> dict:
    return {
        "ticker": "ADSK",
        "period": "2021-Q2",
        "claim_type": "forward_clock",
        "objects": ("Flex",),
        "clock_due_next": True,
        "delivery": "delivered",
        "delivery_basis": "Next-quarter cite treats Flex as live business.",
        "coverage_summary": (
            "Next quarter treated Flex as live usage mix — net new, "
            "occasional, and advanced-product buyers — not a restated "
            "launch date."
        ),
    }


def _desk_flex() -> dict:
    return {
        "ticker": "ADSK",
        "period": "2021-Q2",
        "fiscal_period": "FY2022-Q2",
        "excerpt": "At the end of September, we will launch ... Flex.",
        "source": "ADSK FY2022-Q2 novelty_view competitive_position verbatim",
        "hit": False,
    }


def test_next_fiscal_wraps_q4() -> None:
    assert next_fiscal_period("FY2022-Q4") == "FY2023-Q1"
    assert next_fiscal_period("FY2022-Q2") == "FY2022-Q3"


def test_flex_word_boundary_does_not_match_flexible() -> None:
    assert excerpt_mentions_object("Flex consumption model launched", "Flex")
    assert not excerpt_mentions_object("a more flexible purchase option", "Flex")


def test_flex_bar_kept_on_buried_composite() -> None:
    novelty = {"quarters": [_flex_next_quarter()]}
    resolved = resolve_claim(_catalog_flex(), _desk_flex(), novelty)
    assert resolved["state"] == "kept"
    assert resolved["delivery"] == "delivered"
    assert resolved["coverage_summary"]
    assert resolved["path_hit"] is False
    assert "Flex" in str(resolved["follow_up_excerpt"])
    assert resolved["follow_up_status"] == "composite"
    picked = pick_excerpt(_flex_next_quarter())
    assert "monthly active users" in str(picked["excerpt"])
    assert picked["excerpt_status"] == "verbatim"


def test_clocked_not_due_stays_open_when_silent() -> None:
    catalog = {
        "ticker": "ADSK",
        "period": "2023-Q3",
        "claim_type": "forward_clock",
        "objects": ("Flex",),
        "clock_due_next": False,
    }
    desk = {
        "ticker": "ADSK",
        "period": "2023-Q3",
        "fiscal_period": "FY2024-Q3",
        "excerpt": "Assuming the launch proceeds in fiscal '25 and '26",
        "source": "ADSK FY2024-Q3 novelty_view competitive_position verbatim",
        "hit": False,
    }
    novelty = {
        "quarters": [
            {
                "fiscal_period": "FY2024-Q4",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "claim": "Payapps",
                                "excerpt": "Payapps is a new acquisition.",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    resolved = resolve_claim(catalog, desk, novelty)
    assert resolved["state"] == "open"
    assert resolved["delivery"] == "unresolved"
    assert resolved["follow_up_excerpt"] is None


def test_due_clock_silent_is_slipped() -> None:
    novelty = {
        "quarters": [
            {
                "fiscal_period": "FY2022-Q3",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "claim": "Fusion",
                                "excerpt": "1 million monthly active users",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    catalog = dict(_catalog_flex())
    catalog.pop("delivery", None)
    catalog.pop("delivery_basis", None)
    resolved = resolve_claim(catalog, _desk_flex(), novelty)
    assert resolved["state"] == "slipped"
    assert resolved["delivery"] == "unresolved"


def test_no_next_quarter_is_open() -> None:
    catalog = {
        "ticker": "ADSK",
        "period": "2026-Q1",
        "claim_type": "pending_close",
        "objects": ("digital twin",),
        "clock_due_next": False,
    }
    desk = {
        "ticker": "ADSK",
        "period": "2026-Q1",
        "fiscal_period": "FY2027-Q1",
        "excerpt": "unlock a $40 billion TAM",
        "source": "ADSK FY2027-Q1 novelty_view competitive_position verbatim",
        "hit": False,
    }
    resolved = resolve_claim(catalog, desk, {"quarters": []})
    assert resolved["state"] == "open"
    assert resolved["delivery"] == "unresolved"
    assert resolved["next_fiscal_period"] is None


def test_printed_fact_silent_is_subject_changed() -> None:
    catalog = {
        "ticker": "ADBE",
        "period": "2021-Q2",
        "claim_type": "printed_fact",
        "objects": ("Adobe Experience Platform",),
        "clock_due_next": False,
    }
    desk = {
        "ticker": "ADBE",
        "period": "2021-Q2",
        "fiscal_period": "FY2021-Q2",
        "excerpt": "blew past the $100 million book of business",
        "source": "ADBE FY2021-Q2 novelty_view competitive_position verbatim",
        "hit": True,
    }
    novelty = {
        "quarters": [
            {
                "fiscal_period": "FY2021-Q3",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "claim": "frame.io",
                                "excerpt": "the frame.io acquisition closed.",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    resolved = resolve_claim(catalog, desk, novelty)
    assert resolved["state"] == "subject-changed"
    assert resolved["delivery"] == "not-a-promise"


def test_openai_kept_on_same_object() -> None:
    catalog = {
        "ticker": "MSFT",
        "period": "2022-Q4",
        "claim_type": "completed_announcement",
        "objects": ("OpenAI",),
        "clock_due_next": False,
    }
    desk = {
        "ticker": "MSFT",
        "period": "2022-Q4",
        "fiscal_period": "FY2023-Q2",
        "excerpt": "exclusive cloud provider",
        "source": "MSFT FY2023-Q2 novelty_view competitive_position verbatim",
        "hit": False,
    }
    novelty = {
        "quarters": [
            {
                "fiscal_period": "FY2023-Q3",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "claim": "10x",
                                "excerpt": "2,500 Azure OpenAI Service customers, up 10x",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    resolved = resolve_claim(catalog, desk, novelty)
    assert resolved["state"] == "kept"
    assert resolved["delivery"] == "not-a-promise"
    assert "OpenAI" in str(resolved["follow_up_excerpt"])


def test_first_object_hit_is_not_first_verbatim() -> None:
    rows = all_verified_evidence(_flex_next_quarter())
    hit = first_object_hit(rows, ("Flex",))
    assert hit is not None
    assert hit["status"] == "composite"


def test_resolve_state_table() -> None:
    assert resolve_state(
        claim_type="pending_close",
        clock_due_next=False,
        next_exists=False,
        matched=False,
    ) == "open"
    assert resolve_state(
        claim_type="forward_clock",
        clock_due_next=True,
        next_exists=True,
        matched=True,
    ) == "kept"
    assert resolve_delivery(
        claim_type="printed_fact",
        hand_label="delivered",
        hand_basis="ignored",
    ) == ("not-a-promise", None)
    assert resolve_delivery(
        claim_type="forward_clock",
        hand_label=None,
        hand_basis=None,
    ) == ("unresolved", None)


def test_crm_flex_is_not_autodesk_flex() -> None:
    assert beat_for_excerpt("CRM", "we are using Flex credits to monetize") is None
    beat = beat_for_excerpt("ADSK", "we will launch Flex end of September")
    assert beat is not None
    assert beat["beat_id"] == "flex"


def test_ibm_indemnity_is_not_firefly() -> None:
    assert (
        beat_for_excerpt("IBM", "For models that are IBM produced, we will give you indemnification")
        is None
    )
    beat = beat_for_excerpt("ADBE", "indemnification for the content that's being created")
    assert beat is not None
    assert beat["beat_id"] == "firefly-indemnity"


def test_orcl_openai_joins_foundation_model_beat() -> None:
    beat = beat_for_excerpt("ORCL", "Our major AI customers include OpenAI, xAI, NVIDIA")
    assert beat is not None
    assert beat["beat_id"] == "foundation-model-cloud"


def test_collect_backfill_skips_pilot_and_false_friends() -> None:
    rows = collect_backfill(
        [
            {"ticker": "ADSK", "period": "2021-Q2", "excerpt": "we will launch Flex"},
            {"ticker": "INTU", "period": "2022-Q2", "excerpt": "Lightbox at an all-time high"},
            {"ticker": "CRM", "period": "2025-Q4", "excerpt": "monetize with Flex credits"},
            {"ticker": "IBM", "period": "2023-Q3", "excerpt": "we will give you indemnification"},
        ],
        {("ADSK", "2021-Q2")},
    )
    keys = {(row["ticker"], row["period"]) for row in rows}
    assert keys == {("INTU", "2022-Q2")}
    assert rows[0]["origin"] == "backfill"
    assert rows[0]["beat_id"] == "lightbox"


def test_group_beats_rolls_up_states() -> None:
    grouped = group_beats(
        [
            {"beat_id": "flex", "ticker": "ADSK", "period": "2021-Q2", "state": "kept"},
            {"beat_id": "flex", "ticker": "ADSK", "period": "2023-Q3", "state": "open"},
        ]
    )
    flex = next(item for item in grouped if item["beat_id"] == "flex")
    assert flex["n_rows"] == 2
    assert flex["states"]["kept"] == 1
    assert flex["states"]["open"] == 1


def test_load_desk_claims_v1_stamp_guard(tmp_path) -> None:
    root = tmp_path / "cross_company"
    (root / "json").mkdir(parents=True)
    path = root / "json" / "desk_claims_v1.json"
    path.write_text(
        json.dumps({"generated_at": "2026-01-01T00:00:00+00:00", "rows": []}),
        encoding="utf-8",
    )
    assert load_desk_claims_v1(str(root)) is None
    path.write_text(
        json.dumps(
            {
                "generated_at": LOCKED_GENERATED_AT,
                "case_study_id": CASE_STUDY_ID,
                "rows": [{"ticker": "ADSK", "state": "kept"}],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_desk_claims_v1(str(root))
    assert loaded is not None
    assert loaded["rows"][0]["state"] == "kept"


def test_deliver_rate_excludes_unresolved() -> None:
    counts = deliver_rate_counts(
        [
            {"delivery": "delivered"},
            {"delivery": "unresolved"},
            {"delivery": "not-a-promise"},
            {"delivery": "missed"},
        ]
    )
    assert counts["delivered"] == 1
    assert counts["missed"] == 1
    assert counts["n_scoreable"] == 2
    assert counts["deliver_rate"] == 0.5
    empty = deliver_rate_counts([{"delivery": "unresolved"}])
    assert empty["n_scoreable"] == 0
    assert empty["deliver_rate"] is None


def test_build_deliver_rates_by_ticker() -> None:
    payload = build_deliver_rates(
        [
            {"ticker": "ADSK", "delivery": "delivered"},
            {"ticker": "ADSK", "delivery": "unresolved"},
            {"ticker": "CRM", "delivery": "not-a-promise"},
        ]
    )
    assert payload["book"]["n_scoreable"] == 1
    assert payload["book"]["deliver_rate"] == 1.0
    adsk = next(item for item in payload["by_ticker"] if item["ticker"] == "ADSK")
    crm = next(item for item in payload["by_ticker"] if item["ticker"] == "CRM")
    assert adsk["deliver_rate"] == 1.0
    assert crm["deliver_rate"] is None


def test_coverage_required_on_kept_or_delivered() -> None:
    assert needs_coverage_summary("kept", "not-a-promise")
    assert needs_coverage_summary("open", "delivered")
    assert not needs_coverage_summary("open", "unresolved")
