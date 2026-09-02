"""Retrieval-first terminal scoring: normaliser, sentence index, Tier 0-3 ladder, budget gate.

Fixture-only. No network, no reads of ``Structured Narrative/transcripts_index`` or ``data/`` —
every index is built in memory (either by hand in the schema ``build_index`` writes, or by running
``build_index`` on a synthetic transcript string).
"""
from __future__ import annotations

import pytest

from scripts._desk_retrieval import (
    COOCCUR_WINDOW,
    ELIGIBLE_ROLES,
    GENERIC_THRESHOLD,
    MatchBlock,
    derive_aliases,
    infer_generic,
    is_numeric_anchor,
    match_block_for,
    retrieve,
)
from scripts._desk_terminal_candidates import (
    MODEL,
    TRIAGE_MODEL,
    Budget,
    clock_passed,
    est_tokens,
    est_usd,
    excerpt_in_evidence,
    score_tree,
    window_status,
)
from scripts._desk_transcript_index import (
    UNLABELED_SPEAKER,
    build_index,
    classify_roles,
    is_unlabeled,
    normalize_text,
    parse_transcript,
)
from scripts._desk_trees_v2 import normalize_match

TICKER = "ACME"
SEED_FP = "FY2017-Q1"
CLOCK = "FY2017-Q2"
# clock_window(seed+1 .. clock+2) for the seed/clock above
WINDOW = ["FY2017-Q2", "FY2017-Q3", "FY2017-Q4"]


# ── fixture builders ─────────────────────────────────────────────────────────

def make_index(period: str, turns: list[tuple[str, str, list[str]]], qa_start: int | None = None) -> dict:
    """Hand-built index in the schema ``build_index`` writes.

    ``turns`` = [(speaker, role, [sentence, ...]), ...]; turns at position >= ``qa_start`` are ``qa``.
    """
    qa_start = len(turns) if qa_start is None else qa_start
    out_turns = []
    for i, (speaker, role, sentences) in enumerate(turns):
        out_turns.append(
            {
                "idx": i,
                "speaker": speaker,
                "role": role,
                "section": "prepared" if i < qa_start else "qa",
                "sentences": [{"sid": sid, "text": s, "norm": normalize_text(s)} for sid, s in enumerate(sentences)],
            }
        )
    return {
        "index_version": 3,
        "ticker": TICKER,
        "fiscal_period": period,
        "participants": {spk: role for spk, role, _ in turns},
        "unlabeled": False,
        "qa_start_turn": qa_start,
        "n_turns": len(out_turns),
        "n_sentences": sum(len(t["sentences"]) for t in out_turns),
        "turns": out_turns,
    }


def mgmt_index(period: str, *sentence_lists: list[str]) -> dict:
    """One management turn per sentence list."""
    return make_index(period, [(f"Exec {i}", "management", sents) for i, sents in enumerate(sentence_lists)])


def make_tree(
    anchors,
    *,
    context=(),
    exclude=(),
    generic=None,
    seed_fp: str = SEED_FP,
    clock: str | None = CLOCK,
    excerpt: str = "",
    kind: str = "promise",
    tree_id: str = "acme-t1",
) -> dict:
    """Catalog-shaped tree dict (match block run through ``normalize_match``)."""
    return {
        "tree_id": tree_id,
        "ticker": TICKER,
        "kind": kind,
        "title": "synthetic tree",
        "objects": list(anchors),
        "seed": {"fiscal_period": seed_fp, "clock": clock, "excerpt": excerpt},
        "match": normalize_match({"anchors": list(anchors), "context": list(context), "exclude": list(exclude), "generic": generic}),
    }


class _NoClient:
    """Sentinel client: any attribute access means the scorer tried to talk to an LLM."""

    def __getattr__(self, name: str):  # pragma: no cover - only fires on a regression
        raise AssertionError(f"LLM client must not be used in these tests (accessed {name!r})")


SYNTHETIC_TRANSCRIPT = """\
Operator: Good day, and welcome to the Acme first quarter earnings call. At this time, I would like to turn the conference over to Jane Smith, Head of Investor Relations. Please go ahead.
Jane Smith: Thank you. On the call today are John Doe, CEO, and Mary Roe, CFO. I will now turn the call over to John.
John Doe: Thanks Jane. Revenue grew 10% this quarter. We are investing in Europe. Our Widget platform is scaling well.
Mary Roe: Thank you John. Gross margin was 40%. Operating margin expanded. Back to you, Operator.
Operator: We will now begin the question-and-answer session. Our first question comes from Bob Jones with Big Bank. Please go ahead.
Bob Jones: Thanks for taking my question. Can you talk about the Zephyr platform? What drove margin?
Mary Roe: Sure. Margin was driven by mix.
Operator: Our next question comes from Alice Quant with Fund Co. Please go ahead.
Alice Quant: Hi. How is the Zephyr platform trending in Europe?
John Doe: Europe is strong.
"""


@pytest.fixture
def transcript_index() -> dict:
    return build_index(TICKER, "FY2017-Q2", SYNTHETIC_TRANSCRIPT)


# ── 1. normaliser ────────────────────────────────────────────────────────────

def test_normalize_currency_scale_forms_converge() -> None:
    assert normalize_text("$20 billion") == "$20 billion"
    assert normalize_text("20 billion dollars") == "$20 billion"
    assert normalize_text("$20B") == "$20 billion"
    assert normalize_text("$20 billion") == normalize_text("20 billion dollars") == normalize_text("$20B")
    assert normalize_text("1,250 million") == "$1250 million"


def test_normalize_numeric_percent() -> None:
    assert normalize_text("20 percent") == "20%"
    assert normalize_text("20%") == "20%"
    assert normalize_text("20 percent") == normalize_text("20%")
    assert normalize_text("3.5 percent") == "3.5%"


@pytest.mark.xfail(strict=True, reason="normalize_text has no word-number folding: 'twenty percent' stays as-is")
def test_normalize_word_number_percent() -> None:
    assert normalize_text("twenty percent") == "20%"


def test_normalize_percentage_points_not_folded() -> None:
    assert "%" not in normalize_text("20 percentage points")
    assert "%" not in normalize_text("20 percent points")
    assert normalize_text("20 percent") == "20%"
    assert normalize_text("a 20 percentage move") == "a 20% move"


def test_normalize_hyphen_collapse_and_case_ascii_fold() -> None:
    assert normalize_text("Co-op") == "coop"
    assert normalize_text("co-op") == normalize_text("Co-Op") == "coop"
    assert normalize_text("Café RÉSUMÉ naïve") == "cafe resume naive"
    # unicode dashes / quotes are folded before anything else
    assert normalize_text("Co\u2011op") == "coop"
    assert normalize_text("\u201cQuoted\u201d") == "quoted"


def test_normalize_plural_strip_and_punctuation() -> None:
    assert normalize_text("Customers, partners; and margins!") == "customer partner and margin"
    # single trailing s only; "business" keeps its final s
    assert normalize_text("business") == "business"
    assert normalize_text("  spaced   out  ") == "spaced out"


def test_normalize_plural_of_s_ending_word() -> None:
    assert normalize_text("businesses") == normalize_text("business")
    assert normalize_text("processes") == normalize_text("process")
    assert normalize_text("losses") == normalize_text("loss")


# ── 2. generic inference ─────────────────────────────────────────────────────

def _dense_indexes(hits_per_quarter: int, quarters: int = 3) -> dict[str, dict]:
    out = {}
    for n in range(quarters):
        period = f"FY2017-Q{n + 1}"
        sents = [f"Margin point {k} was discussed." for k in range(hits_per_quarter)]
        out[period] = mgmt_index(period, sents)
    return out


def test_infer_generic_dense_anchor_is_generic() -> None:
    indexes = _dense_indexes(3)
    stats = infer_generic("margin", indexes)
    assert stats["quarters"] == 3
    assert stats["hits"] == 9
    assert stats["hits_per_quarter"] == 3.0 > GENERIC_THRESHOLD
    assert stats["generic"] is True


def test_infer_generic_threshold_is_strict() -> None:
    indexes = _dense_indexes(2)
    stats = infer_generic("margin", indexes)
    assert stats["hits_per_quarter"] == GENERIC_THRESHOLD == 2.0
    assert stats["generic"] is False


def test_infer_generic_rare_anchor_is_specific() -> None:
    indexes = _dense_indexes(3)
    indexes["FY2017-Q2"]["turns"][0]["sentences"].append(
        {"sid": 99, "text": "Zephyr launched.", "norm": normalize_text("Zephyr launched.")}
    )
    stats = infer_generic("Zephyr", indexes)
    assert stats["hits"] == 1
    assert stats["generic"] is False


def test_is_numeric_anchor_is_quantity_only() -> None:
    # pure quantities: number / currency / percent plus scale or connector words
    for anchor in ("45%", "$20 billion", "$150 to $160 million", "150 million", "1.5x", "10 percentage points",
                   "75 basis points", "about 25%", "2 billion"):
        assert is_numeric_anchor(anchor) is True, anchor
    # product codes, years-with-nouns and counted things are NAMES: their genericness is inferred
    for anchor in ("S600", "VX-445", "KTE-X19", "ZUMA-2", "AMG 510", "400G", "2019 guidance", "day 2",
                   "1 million patients", "aflibercept 8 mg", "Zephyr", ""):
        assert is_numeric_anchor(anchor) is False, anchor


def test_infer_generic_product_code_uses_density_not_digits() -> None:
    """A rare product code with a digit is specific (it used to be forced generic by the digit)."""
    indexes = _dense_indexes(3)
    indexes["FY2017-Q2"]["turns"][0]["sentences"].append(
        {"sid": 99, "text": "The S600 shipped to Seagate.", "norm": normalize_text("The S600 shipped to Seagate.")}
    )
    stats = infer_generic("S600", indexes)
    assert stats["hits"] == 1 and stats["generic"] is False


def test_infer_generic_many_matches_single_and_is_cached() -> None:
    from scripts._desk_retrieval import _GENERIC_CACHE, infer_generic_many

    indexes = _dense_indexes(3)
    indexes["FY2017-Q2"]["turns"][0]["sentences"].append(
        {"sid": 99, "text": "Zephyr launched.", "norm": normalize_text("Zephyr launched.")}
    )
    many = infer_generic_many(["margin", "Zephyr", "$20 billion"], indexes)
    assert many["margin"] == infer_generic("margin", indexes)
    assert many["Zephyr"] == infer_generic("Zephyr", indexes)
    assert many["$20 billion"]["generic"] is True and many["$20 billion"]["hits"] == 0
    # a second call with the same content is served from the memo; changed content is not
    before = len(_GENERIC_CACHE)
    assert infer_generic_many(["margin", "Zephyr"], indexes) == {k: many[k] for k in ("margin", "Zephyr")}
    assert len(_GENERIC_CACHE) == before
    denser = _dense_indexes(5)
    assert infer_generic("margin", denser)["hits_per_quarter"] == 5.0


def test_infer_generic_numeric_anchor_always_generic() -> None:
    assert is_numeric_anchor("$20 billion") is True
    assert is_numeric_anchor("Zephyr") is False
    stats = infer_generic("$20 billion", _dense_indexes(1))
    assert stats["hits"] == 0
    assert stats["generic"] is True


def test_infer_generic_counts_only_eligible_speakers() -> None:
    period = "FY2017-Q1"
    sents = [f"Analyst margin question {k}?" for k in range(5)]
    indexes = {period: make_index(period, [("Bob Jones", "analyst", sents), ("Operator", "operator", sents)])}
    assert infer_generic("margin", indexes)["hits"] == 0
    assert infer_generic("margin", indexes)["generic"] is False


def test_infer_generic_exclude_blanks_phrase() -> None:
    period = "FY2017-Q1"
    indexes = {period: mgmt_index(period, ["Gross margin was 40%.", "Gross margin rose.", "Gross margin fell."])}
    assert infer_generic("margin", indexes)["hits"] == 3
    assert infer_generic("margin", indexes, exclude=["gross margin"])["hits"] == 0


def test_infer_generic_no_indexes() -> None:
    stats = infer_generic("margin", {})
    assert stats == {"hits": 0, "quarters": 0, "hits_per_quarter": 0.0, "generic": False}


# ── aliases / match block ────────────────────────────────────────────────────

def test_derive_aliases() -> None:
    assert derive_aliases("Health Care") == ["health care", "healthcare"]
    assert derive_aliases("World Conference on Lung Cancer") == ["world conference on lung cancer", "wclc"]
    assert derive_aliases("Co-op") == ["coop"]
    assert derive_aliases("$20 billion") == ["$20 billion"]
    assert derive_aliases("  ") == []


def test_match_block_for_falls_back_to_objects() -> None:
    tree = {"objects": ["Widget", "Widget", " "], "match": None}
    block = match_block_for(tree)
    assert block == MatchBlock(anchors=("Widget",))
    assert block.generic is None
    tree = make_tree(["Widget"], context=["Europe"], exclude=["gross margin"], generic=True)
    block = match_block_for(tree)
    assert block.anchors == ("Widget",)
    assert block.context == ("Europe",)
    assert block.exclude == ("gross margin",)
    assert block.generic is True
    # a match block with context but no anchors takes anchors from objects
    tree = {"objects": ["Widget"], "match": {"anchors": [], "context": ["Europe"]}}
    assert match_block_for(tree) == MatchBlock(anchors=("Widget",), context=("Europe",))


# ── 3. +-3 sentence co-occurrence ────────────────────────────────────────────

FILLER = ["Demand was solid.", "Pricing held.", "Costs were flat."]


def _cooccur_index(gap: int) -> dict:
    """One management turn: anchor sentence at sid 0, 'Europe' sentence ``gap`` sentences later."""
    sents = ["Margin was stable this quarter."] + FILLER[: gap - 1] + ["Europe was the standout region."]
    assert sents.index("Europe was the standout region.") == gap
    return mgmt_index("FY2017-Q2", sents)


def test_generic_anchor_context_within_window_hits() -> None:
    assert COOCCUR_WINDOW == 3
    indexes = {"FY2017-Q2": _cooccur_index(COOCCUR_WINDOW)}
    res = retrieve(make_tree(["margin"], context=["Europe"], generic=True), indexes)
    assert res.tier == 0
    assert res.generic_map == {"margin": True}
    assert len(res.excerpts) == 1
    ex = res.excerpts[0]
    assert ex["sid"] == 0
    assert ex["specific_anchor"] is False
    assert set(ex["matched_terms"]) == {"europe", "margin"}
    assert res.window == WINDOW
    assert res.window_indexed == ["FY2017-Q2"]


def test_generic_anchor_context_outside_window_misses() -> None:
    indexes = {"FY2017-Q2": _cooccur_index(COOCCUR_WINDOW + 1)}
    res = retrieve(make_tree(["margin"], context=["Europe"], generic=True), indexes)
    assert res.tier is None
    assert res.excerpts == []
    assert "no excerpt at any free tier" in res.notes


def test_generic_anchor_context_in_other_turn_misses() -> None:
    indexes = {
        "FY2017-Q2": mgmt_index(
            "FY2017-Q2", ["Margin was stable this quarter."], ["Europe was the standout region."]
        )
    }
    res = retrieve(make_tree(["margin"], context=["Europe"], generic=True), indexes)
    assert res.tier is None
    assert res.excerpts == []


def test_specific_anchor_needs_no_context() -> None:
    indexes = {"FY2017-Q2": _cooccur_index(COOCCUR_WINDOW + 1)}
    res = retrieve(make_tree(["margin"], context=["Europe"], generic=False), indexes)
    assert res.tier == 0
    assert res.excerpts[0]["specific_anchor"] is True


def test_tier2_seed_nouns_resolve_generic_anchor() -> None:
    """No catalog context: the co-occurrence set is empty at tiers 0-1 and gains the seed nouns at tier 2."""
    indexes = {"FY2017-Q2": _cooccur_index(COOCCUR_WINDOW)}
    tree = make_tree(["margin"], generic=True, excerpt="Management expects Europe to lead.")
    res = retrieve(tree, indexes)
    assert res.tier == 2
    assert "europe" in res.excerpts[0]["matched_terms"]
    # the same tree with the noun 4 sentences away resolves nowhere
    far = retrieve(tree, {"FY2017-Q2": _cooccur_index(COOCCUR_WINDOW + 1)})
    assert far.tier is None


def test_tier1_alias_hit() -> None:
    indexes = {"FY2017-Q2": mgmt_index("FY2017-Q2", ["Healthcare revenue grew 5%."])}
    res = retrieve(make_tree(["Health Care"], generic=False), indexes)
    assert res.tier == 1
    assert res.alias_snapshot == {"Health Care": ["health care", "healthcare"]}
    assert res.excerpts[0]["matched_terms"] == ["healthcare"]


def test_exclude_blanks_anchor_phrase() -> None:
    indexes = {"FY2017-Q2": mgmt_index("FY2017-Q2", ["Gross margin was 40%.", "Operating margin expanded."])}
    res = retrieve(make_tree(["margin"], exclude=["gross margin"], generic=False), indexes)
    assert res.tier == 0
    assert [e["sid"] for e in res.excerpts] == [1]


def test_tier3_widens_past_clock_window() -> None:
    # seed FY2016-Q4, clock FY2017-Q1 -> window FY2017-Q1..Q3; only FY2017-Q4 is indexed
    tree = make_tree(["Widget"], generic=False, seed_fp="FY2016-Q4", clock="FY2017-Q1")
    indexes = {"FY2017-Q4": mgmt_index("FY2017-Q4", ["Widget shipped."])}
    res = retrieve(tree, indexes)
    assert res.window == ["FY2017-Q1", "FY2017-Q2", "FY2017-Q3"]
    assert res.window_indexed == []
    assert res.tier == 3
    assert res.quarters_searched == ["FY2017-Q4"]
    assert "clock window has no indexed transcripts" in res.notes
    # now_fiscal caps the post-seed quarters
    capped = retrieve(tree, indexes, now_fiscal="FY2017-Q3")
    assert capped.tier is None
    assert "no post-seed indexed quarters" in capped.notes


def test_no_clock_tree_starts_at_tier3() -> None:
    tree = make_tree(["Widget"], generic=False, clock=None, kind="goal")
    indexes = {"FY2017-Q2": mgmt_index("FY2017-Q2", ["Widget shipped."])}
    res = retrieve(tree, indexes)
    assert res.window == []
    assert res.tier == 3
    assert "no clock: tiers 0-2 skipped" in res.notes


def test_retrieve_ignores_pre_seed_quarters() -> None:
    tree = make_tree(["Widget"], generic=False)
    indexes = {"FY2016-Q4": mgmt_index("FY2016-Q4", ["Widget shipped."]), SEED_FP: mgmt_index(SEED_FP, ["Widget shipped."])}
    res = retrieve(tree, indexes)
    assert res.tier is None
    assert res.post_seed_quarters == []


def test_retrieve_no_anchors() -> None:
    res = retrieve({"tree_id": "x", "ticker": TICKER, "objects": [], "seed": {"fiscal_period": SEED_FP}}, {})
    assert res.tier is None
    assert res.notes == ["no anchors (empty objects and match)"]


# ── 4. speaker roles ─────────────────────────────────────────────────────────

def test_classify_roles_operator_handoff() -> None:
    turns, hints = parse_transcript(SYNTHETIC_TRANSCRIPT)
    assert [t["speaker"] for t in turns] == [
        "Operator", "Jane Smith", "John Doe", "Mary Roe", "Operator",
        "Bob Jones", "Mary Roe", "Operator", "Alice Quant", "John Doe",
    ]
    assert not is_unlabeled(turns)
    roles, qa_start = classify_roles(turns, hints)
    assert qa_start == 4
    assert roles["Operator"] == "operator"
    assert roles["Jane Smith"] == "ir"
    assert roles["John Doe"] == "management"
    assert roles["Mary Roe"] == "management"
    assert roles["Bob Jones"] == "analyst"
    assert roles["Alice Quant"] == "analyst"


def test_build_index_sections_and_operator_dropped(transcript_index: dict) -> None:
    idx = transcript_index
    assert idx["ticker"] == TICKER and idx["fiscal_period"] == "FY2017-Q2"
    assert idx["qa_start_turn"] == 4
    assert idx["unlabeled"] is False
    by_idx = {t["idx"]: t for t in idx["turns"]}
    assert by_idx[2]["section"] == "prepared" and by_idx[5]["section"] == "qa"
    assert all(t["sentences"] == [] for t in idx["turns"] if t["role"] == "operator")
    sent = by_idx[2]["sentences"][1]
    assert sent == {"sid": 1, "text": "Revenue grew 10% this quarter.", "norm": "revenue grew 10% this quarter"}
    # boilerplate ("turn the call over to") is dropped at sentence level
    assert all("turn the call over" not in s["text"] for t in idx["turns"] for s in t["sentences"])


def test_retrieve_never_returns_analyst_or_ir_sentences(transcript_index: dict) -> None:
    indexes = {"FY2017-Q2": transcript_index}
    assert ELIGIBLE_ROLES == {"management", "unknown"}
    # "Zephyr" is spoken only by analysts -> unretrievable
    res = retrieve(make_tree(["Zephyr"]), indexes)
    assert res.tier is None and res.excerpts == []
    assert res.generic_map == {"Zephyr": False}
    # "CFO" is spoken only by IR -> unretrievable
    res = retrieve(make_tree(["CFO"]), indexes)
    assert res.tier is None and res.excerpts == []
    # "Europe" is spoken by management (prepared + qa) and by an analyst -> only management returned
    res = retrieve(make_tree(["Europe"]), indexes)
    assert res.tier == 0
    assert len(res.excerpts) == 2
    assert {e["role"] for e in res.excerpts} == {"management"}
    assert {e["speaker"] for e in res.excerpts} == {"John Doe"}
    assert {e["section"] for e in res.excerpts} == {"prepared", "qa"}
    assert all(e["role"] in ELIGIBLE_ROLES for e in res.excerpts)


def test_unlabeled_transcript_indexes_as_unknown_and_is_eligible() -> None:
    raw = "Revenue grew 10% this quarter.\n\nWe are investing in Europe.\n\nOur Widget platform is scaling well.\n"
    turns, hints = parse_transcript(raw)
    assert hints == {}
    assert is_unlabeled(turns)
    assert all(t["speaker"] == UNLABELED_SPEAKER for t in turns)
    assert len(turns) == 3  # one paragraph per turn
    idx = build_index(TICKER, "FY2017-Q2", raw)
    assert idx["unlabeled"] is True
    assert idx["participants"] == {UNLABELED_SPEAKER: "unknown"}
    res = retrieve(make_tree(["Widget"]), {"FY2017-Q2": idx})
    assert res.tier == 0
    assert res.excerpts[0]["role"] == "unknown"
    assert res.excerpts[0]["speaker"] == UNLABELED_SPEAKER


# ── 5. budget gate ───────────────────────────────────────────────────────────

def test_budget_zero_cannot_afford() -> None:
    b = Budget(0.0)
    assert b.fallback_allowed_usd == 0.0
    assert b.can_afford(0.01) is False
    assert b.can_afford(0.0) is True


def test_budget_charge_routes_by_tier() -> None:
    b = Budget(fallback_allowed_usd=0.05)
    b.charge(model=TRIAGE_MODEL, tier=4, usd=0.02, input_tokens=10, output_tokens=5, tree_id="t")
    assert b.fallback_spent_usd == pytest.approx(0.02)
    assert b.sonnet_spent_usd == 0.0
    assert b.fallback_remaining_usd == pytest.approx(0.03)
    assert b.can_afford(0.03) is True
    assert b.can_afford(0.0301) is False
    b.charge(model=MODEL, tier=3, usd=0.10, input_tokens=10, output_tokens=5, tree_id="t")
    assert b.sonnet_spent_usd == pytest.approx(0.10)
    assert b.fallback_spent_usd == pytest.approx(0.02)  # metered separately, does not eat the fallback budget
    assert b.fallback_remaining_usd == pytest.approx(0.03)
    assert len(b.calls) == 2 and b.calls[0]["tier"] == 4 and b.calls[1]["tier"] == 3
    d = b.to_dict()
    assert d["n_paid_calls"] == 2
    assert d["total_spent_usd"] == pytest.approx(0.12)


def test_est_tokens_and_usd() -> None:
    assert est_tokens("") == 1
    assert est_tokens("a" * 400) == 100
    assert est_usd(MODEL, 1_000_000, 0) == pytest.approx(3.0)
    assert est_usd(TRIAGE_MODEL, 0, 1_000_000) == pytest.approx(5.0)
    assert est_usd("unknown-model", 1_000_000, 1_000_000) == est_usd(MODEL, 1_000_000, 1_000_000)


def _zero_hit_tree() -> dict:
    return make_tree(["Unobtainium"], generic=False)


def _full_window_indexes() -> dict[str, dict]:
    return {q: mgmt_index(q, ["Revenue grew 10% this quarter."]) for q in WINDOW}


def test_score_tree_zero_hits_default_budget_needs_review_no_client() -> None:
    cand, item = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert item is not None
    assert item["reason"] == "no_evidence_retrieved"
    assert item["clock_window"] == WINDOW
    assert item["transcripts_present"] == 3 and item["transcripts_missing"] == []
    assert item["retrieval_tier"] is None
    assert item["anchors_tried"] == ["Unobtainium"]
    # the window is complete and the clock has passed, so the deterministic expired proposal rides along
    assert cand is not None and cand["proposed_edge"] == "expired"


def test_score_tree_zero_hits_window_gap_is_transcript_missing() -> None:
    indexes = _full_window_indexes()
    del indexes["FY2017-Q3"]
    cand, item = score_tree(_zero_hit_tree(), indexes, {}, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert cand is None
    assert item["reason"] == "transcript_missing"
    assert item["transcripts_missing"] == ["FY2017-Q3"]
    assert "FY2017-Q3" in item["detail"]


def test_score_tree_all_numeric_anchor_zero_hits() -> None:
    tree = make_tree(["$20 billion"])
    cand, item = score_tree(tree, _full_window_indexes(), {}, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert cand is None
    assert item["reason"] == "numeric_target_no_strict_match"
    assert item["generic_inferred"] == {"$20 billion": True}


def test_score_tree_no_clock_zero_hits() -> None:
    tree = make_tree(["Unobtainium"], clock=None, kind="goal")
    cand, item = score_tree(tree, _full_window_indexes(), {}, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert cand is None
    assert item["reason"] == "no_clock_open_goal"
    assert item["clock_window"] == []


def test_score_tree_no_indexes() -> None:
    cand, item = score_tree(_zero_hit_tree(), {}, {}, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert cand is None
    assert item["reason"] == "no_transcripts_indexed"


def test_score_tree_plan_with_evidence_estimates_only() -> None:
    indexes = _full_window_indexes()
    indexes["FY2017-Q3"] = mgmt_index("FY2017-Q3", ["Widget shipped on time."])
    cand, item = score_tree(make_tree(["Widget"]), indexes, {}, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert item is None
    assert cand["plan"] is True
    assert cand["proposed_edge"] is None
    assert cand["n_evidence_excerpts"] == 1
    assert cand["retrieval"]["tier"] == 0
    assert cand["retrieval"]["est_usd"] > 0
    assert cand["retrieval"]["usd"] is None


def test_score_tree_fallback_budget_plan_would_triage_and_reserves_estimate() -> None:
    """A positive fallback budget in plan mode reports the Tier 4 intent without touching the client,
    and books the pre-flight estimate against the fallback line so the plan exhausts where a run would."""
    budget = Budget(fallback_allowed_usd=1.0)
    cand, item = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, budget, _NoClient(), plan_only=True, now_fiscal=None)
    assert item is None
    assert cand["plan"] is True and cand["proposed_edge"] is None
    assert cand["retrieval"]["triage"]["skipped"] == "plan mode"
    assert cand["retrieval"]["triage"]["n_sentences_offered"] == 3
    est = cand["retrieval"]["triage"]["est_usd"]
    assert est > 0
    assert budget.fallback_spent_usd == pytest.approx(est)
    assert budget.calls == [{"tree_id": "acme-t1", "tier": 4, "model": TRIAGE_MODEL, "simulated": True, "usd": pytest.approx(est)}]


def test_score_tree_plan_budget_exhausts_across_trees() -> None:
    """Plan mode simulates spend: a budget that covers exactly one triage refuses the second tree,
    which then falls back to the deterministic expired rider (window complete, clock passed)."""
    first_est = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, Budget(fallback_allowed_usd=1.0), _NoClient(),
                           plan_only=True, now_fiscal=None)[0]["retrieval"]["triage"]["est_usd"]
    budget = Budget(fallback_allowed_usd=first_est * 1.5)
    cand1, item1 = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, budget, _NoClient(), plan_only=True, now_fiscal=None)
    assert item1 is None and cand1["plan"] is True
    cand2, item2 = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, budget, _NoClient(), plan_only=True, now_fiscal=None)
    assert item2["reason"] == "fallback_budget_exhausted"
    assert item2["expired_eligible"] is True
    assert cand2["proposed_edge"] == "expired" and cand2["source"] == "retrieval"
    assert budget.refused_trees == 1


def test_score_tree_fallback_budget_exhausted_is_gated_before_any_call() -> None:
    """Budget too small for even the triage: no call, needs_review, and — because the window is
    complete and the clock passed — the expired rider still rides along for the reviewer."""
    budget = Budget(fallback_allowed_usd=1e-7)
    cand, item = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, budget, _NoClient(), plan_only=False, now_fiscal=None)
    assert item["reason"] == "fallback_budget_exhausted"
    assert item["expired_eligible"] is True
    assert cand is not None and cand["proposed_edge"] == "expired"
    assert "budget exhausted" in cand["reasoning"]
    assert budget.refused_trees == 1
    assert budget.fallback_spent_usd == 0.0 and budget.calls == []


def test_score_tree_fallback_budget_exhausted_window_gap_no_rider() -> None:
    indexes = _full_window_indexes()
    del indexes["FY2017-Q4"]
    budget = Budget(fallback_allowed_usd=1e-7)
    cand, item = score_tree(_zero_hit_tree(), indexes, {}, budget, _NoClient(), plan_only=False, now_fiscal=None)
    # the window gap short-circuits to transcript_missing before any paid line is considered
    assert cand is None and item["reason"] == "transcript_missing"
    assert budget.calls == []


class _TriageOnlyClient:
    """Answers the Haiku triage with the given ids and refuses any further call (the Sonnet gate
    must trip before one is attempted)."""

    def __init__(self, ids: list[int]) -> None:
        self.ids = ids
        self.calls = 0

    def complete_json(self, *a, **k):  # pragma: no cover - interface guard
        raise AssertionError("complete_json must not be used")


def test_sonnet_after_triage_is_budget_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier 5: the triage fits the budget but the Sonnet verdict does not → refused with a reason,
    no Sonnet call, spend limited to the triage."""
    import scripts._desk_terminal_candidates as tc

    calls: list[str] = []

    def fake_call_json(client, *, model, system, user, max_tokens):
        calls.append(model)
        if model == tc.TRIAGE_MODEL:
            return [0], 100, 10
        raise AssertionError("Sonnet must not be called when the fallback budget cannot cover it")

    monkeypatch.setattr(tc, "_call_json", fake_call_json)
    triage_usd = tc.est_usd(tc.TRIAGE_MODEL, 100, 10)  # what the fake triage actually charges
    triage_est = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, Budget(fallback_allowed_usd=1.0), _NoClient(),
                            plan_only=True, now_fiscal=None)[0]["retrieval"]["triage"]["est_usd"]  # what the gate needs
    budget = Budget(fallback_allowed_usd=triage_est * 1.5)  # clears the triage gate; far below a Sonnet verdict (~$0.005)
    cand, item = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, budget, _TriageOnlyClient([0]), plan_only=False, now_fiscal=None)
    assert calls == [tc.TRIAGE_MODEL]
    assert cand is None
    assert item["reason"] == "fallback_budget_exhausted"
    assert "tier-5 Sonnet" in item["detail"]
    assert budget.fallback_trees == 1 and budget.refused_trees == 1
    assert budget.fallback_spent_usd == pytest.approx(triage_usd)


def test_triage_corpus_offers_only_visible_ids() -> None:
    """Every row returned by _triage_corpus must have its line in the corpus Haiku sees."""
    import scripts._desk_terminal_candidates as tc

    sents = [f"Sentence number {n} about widgets and margins for the quarter." for n in range(400)]
    indexes = {q: mgmt_index(q, sents) for q in WINDOW}
    monkeypatch_cap = 5000
    old = tc.TRIAGE_MAX_CHARS
    tc.TRIAGE_MAX_CHARS = monkeypatch_cap
    try:
        rows, corpus = tc._triage_corpus(indexes, WINDOW)
    finally:
        tc.TRIAGE_MAX_CHARS = old
    lines = corpus.split("\n")
    assert len(rows) == len(lines)
    assert all(line.startswith(f"[{row['id']}]") for row, line in zip(rows, lines))
    assert len(corpus) <= monkeypatch_cap + 200


# ── 6. expired guard ─────────────────────────────────────────────────────────

def test_expired_guard_clock_passed_window_complete() -> None:
    cand, item = score_tree(_zero_hit_tree(), _full_window_indexes(), {}, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert item["reason"] == "no_evidence_retrieved"
    assert item["expired_eligible"] is True
    assert cand["proposed_edge"] == "expired"
    assert cand["proposed_fiscal"] == CLOCK
    assert cand["source"] == "retrieval"
    assert cand["n_evidence_excerpts"] == 0
    assert cand["supporting_excerpt"] is None and cand["excerpt_verified"] is None
    assert cand["confidence"] == "medium"
    assert cand["retrieval"]["window_missing"] == []
    assert cand["retrieval"]["quarters_searched"] == WINDOW
    assert '"edge": "expired"' in cand["proposed_node_py"]


def test_expired_guard_window_gap_blocks_expired() -> None:
    indexes = _full_window_indexes()
    del indexes["FY2017-Q4"]
    cand, item = score_tree(_zero_hit_tree(), indexes, {}, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert cand is None
    assert item["reason"] == "transcript_missing"
    assert "expired_eligible" not in item


def test_expired_guard_clock_not_passed_blocks_expired() -> None:
    """Window complete per the manifest (later quarters fetched but not indexed) while nothing indexed
    is later than the clock: zero hits, no expired proposal."""
    indexes = {"FY2017-Q2": mgmt_index("FY2017-Q2", ["Revenue grew 10% this quarter."])}
    manifest = {"tickers": {TICKER: {"periods": {"FY2017-Q3": {"status": "present"}, "FY2017-Q4": {"status": "present"}}}}}
    assert clock_passed(CLOCK, indexes, None) is False
    cand, item = score_tree(_zero_hit_tree(), indexes, manifest, Budget(), _NoClient(), plan_only=True, now_fiscal=None)
    assert cand is None
    assert item["reason"] == "no_evidence_retrieved"
    assert "expired_eligible" not in item
    assert item["transcripts_missing"] == []


def test_clock_passed() -> None:
    indexes = {"FY2017-Q2": {}}
    assert clock_passed(None, indexes, None) is False
    assert clock_passed("garbage", indexes, None) is False
    assert clock_passed("FY2017-Q2", indexes, None) is False  # equal is not passed
    assert clock_passed("FY2017-Q1", indexes, None) is True
    assert clock_passed("FY2017-Q2", indexes, "FY2017-Q3") is True  # now_fiscal can only raise the latest quarter
    assert clock_passed("FY2017-Q2", {}, None) is False


def test_window_status_index_beats_manifest() -> None:
    indexes = {"FY2017-Q2": {}}
    manifest = {"tickers": {TICKER: {"periods": {
        "FY2017-Q2": {"status": "missing"},
        "FY2017-Q3": {"status": "present"},
        "FY2017-Q4": {"status": "no_event"},
    }}}}
    st = window_status(TICKER, WINDOW + ["FY2018-Q1"], indexes, manifest)
    assert st == {"FY2017-Q2": "present", "FY2017-Q3": "present", "FY2017-Q4": "no_event", "FY2018-Q1": "missing"}
    assert window_status(TICKER, WINDOW, {}, {}) == {q: "missing" for q in WINDOW}


# ── 7. excerpt_in_evidence ───────────────────────────────────────────────────

EVIDENCE = [{"text": "We expect \u201cstrong\u201d growth in Europe next year. Margin should expand."}]


def test_excerpt_in_evidence_exact_substring() -> None:
    assert excerpt_in_evidence("growth in Europe next year", EVIDENCE) is True


def test_excerpt_in_evidence_quote_and_whitespace_insensitive() -> None:
    assert excerpt_in_evidence('we   expect "strong"\n growth', EVIDENCE) is True
    assert excerpt_in_evidence("WE EXPECT \u201cSTRONG\u201d GROWTH", EVIDENCE) is True


def test_excerpt_in_evidence_paraphrase_is_false() -> None:
    assert excerpt_in_evidence("Europe growth is expected to be strong", EVIDENCE) is False
    assert excerpt_in_evidence("Margin will expand next year", EVIDENCE) is False


def test_excerpt_in_evidence_short_needle_is_false() -> None:
    assert excerpt_in_evidence("Europe next", EVIDENCE) is False  # 11 chars, even though it is a substring
    assert excerpt_in_evidence("", EVIDENCE) is False
    assert excerpt_in_evidence(None, EVIDENCE) is False
    assert excerpt_in_evidence("growth in Europe next year", []) is False


def test_excerpt_in_evidence_needle_containing_whole_excerpt() -> None:
    needle = "Prefix. " + EVIDENCE[0]["text"] + " Suffix."
    assert excerpt_in_evidence(needle, EVIDENCE) is True
