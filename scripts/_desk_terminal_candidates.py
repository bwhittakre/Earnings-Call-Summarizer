"""Retrieval-first terminal scoring for open ops + HC trees.

For each open tree the evidence base is the raw-transcript index (Structured
Narrative/transcripts_index), searched by the free Tier 0-3 ladder in
scripts/_desk_retrieval.py. Only trees with retrieved evidence are judged by
Claude Sonnet. Trees with zero retrieved sentences never call the LLM unless the
run carries an explicit fallback budget (--fallback-budget-usd), in which case a
budget-gated Haiku triage (Tier 4) points Sonnet (Tier 5) at specific sentences.
Anything unresolved lands in `needs_review` with a reason instead of a verdict.

Outputs data/terminal_score_candidates.json for human review.

Rules:
- Does NOT auto-insert into any catalog.
- Gold book (NVDA) excluded — "No new LLM on the gold run".
- Only processes trees with state == "open".
- Default fallback budget is $0.00; `--plan` makes zero API calls.
- `expired` may only be proposed when the clock has passed and every clock-window
  transcript is present and was searched with zero hits.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from scripts._desk_regimes_builder import (  # noqa: E402
    load_desk_trees_hc_v2,
    load_desk_trees_ops_v2,
)
from scripts._desk_retrieval import (  # noqa: E402
    GOLD_TICKERS,
    LazyTickerIndexes,
    MatchBlock,
    RetrievalResult,
    _eligible_turns,
    is_numeric_anchor,
    match_block_for,
    retrieve,
)
from scripts._desk_transcript_backfill import MANIFEST  # noqa: E402
from scripts._desk_trees_v2 import fiscal_key  # noqa: E402

# ── constants ────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-5"
TRIAGE_MODEL = "claude-haiku-4-5"

OUT = ROOT / "data" / "terminal_score_candidates.json"
# `--plan` never touches OUT: a zero-cost rehearsal must not clobber the last paid run's verdicts.
PLAN_OUT = ROOT / "data" / "terminal_score_plan.json"


def _out_path(plan_only: bool) -> Path:
    return PLAN_OUT if plan_only else OUT

MAX_EVIDENCE_PER_TREE = 20
MAX_EXCERPT_CHARS = 600
TRIAGE_MAX_CHARS = 400_000  # hard cap on the transcript text one Haiku triage may read
SONNET_MAX_OUTPUT = 1024
TRIAGE_MAX_OUTPUT = 512

# USD per million tokens (input, output). Pre-flight estimates use these; actuals use response usage.
PRICES = {
    MODEL: (3.0, 15.0),
    TRIAGE_MODEL: (1.0, 5.0),
}
CHARS_PER_TOKEN = 4

NEEDS_REVIEW_REASONS = (
    "no_evidence_retrieved",
    "numeric_target_no_strict_match",
    "transcript_missing",
    "fallback_budget_exhausted",
    "no_clock_open_goal",
    "no_transcripts_indexed",
    "llm_low_confidence",
    "llm_failed",
    "expired_guard",
)

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are an experienced equity analyst closing out a claims-desk tree.
    A claims-desk tree tracks whether management delivered on a specific
    forward-looking statement. Your job: given the original seed statement
    and subsequent earnings call excerpts spoken by management, propose the
    most appropriate terminal outcome.

    Terminal edge options:
      "delivered"  — promise was clearly fulfilled (use for kind=promise)
      "hit"        — goal was achieved (use for kind=goal)
      "missed"     — explicitly failed to deliver / admitted miss. This includes
                     management acknowledging the thing did not happen (deal
                     terminated, launch cancelled, target withdrawn, guidance cut
                     below the promise). Prefer "missed" over "expired" whenever
                     the evidence speaks to the outcome at all.
      "expired"    — promised timeframe passed and the evidence is silent on the
                     outcome either way (management simply stopped talking about it)
      "none"       — insufficient evidence to close; tree should remain open

    Respond with a JSON object:
    {
      "proposed_edge": "delivered|hit|missed|expired|none",
      "proposed_fiscal": "FY20XX-QX or null",
      "supporting_excerpt": "the single most relevant excerpt, copied verbatim from the evidence",
      "confidence": "high|medium|low",
      "reasoning": "2-3 sentences explaining your conclusion"
    }

    The supporting_excerpt must be a verbatim substring of one evidence excerpt.
    If you are not confident (confidence=low) or cannot find clear evidence,
    set proposed_edge to "none". Never guess at a terminal just to close the tree.
    """
).strip()

TRIAGE_SYSTEM_PROMPT = textwrap.dedent(
    """
    You are a retrieval assistant. You will be given a list of numbered
    sentences from earnings-call transcripts and a set of anchor terms. Return
    ONLY a JSON array of the sentence ids (integers) that refer to any of the
    anchors or clearly describe the same thing in different words. Return []
    if none do. No prose.
    """
).strip()


# ── budget ───────────────────────────────────────────────────────────────────

def est_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def est_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, PRICES[MODEL])
    return input_tokens / 1e6 * pin + output_tokens / 1e6 * pout


@dataclass
class Budget:
    """Run-level fallback budget for Tiers 4-5. Pre-flight gated: a paid call runs only if its
    estimated cost fits in what remains. Sonnet-on-retrieved-evidence is metered but not gated."""

    fallback_allowed_usd: float = 0.0
    fallback_spent_usd: float = 0.0
    sonnet_spent_usd: float = 0.0
    fallback_trees: int = 0
    refused_trees: int = 0
    calls: list[dict] = field(default_factory=list)

    @property
    def fallback_remaining_usd(self) -> float:
        return max(0.0, self.fallback_allowed_usd - self.fallback_spent_usd)

    def can_afford(self, usd: float) -> bool:
        return usd <= self.fallback_remaining_usd + 1e-9

    def charge(self, *, model: str, tier: int, usd: float, input_tokens: int, output_tokens: int, tree_id: str) -> None:
        if tier >= 4:
            self.fallback_spent_usd += usd
        else:
            self.sonnet_spent_usd += usd
        self.calls.append(
            {"tree_id": tree_id, "tier": tier, "model": model, "input_tokens": input_tokens,
             "output_tokens": output_tokens, "usd": round(usd, 6)}
        )

    def reserve(self, *, model: str, tier: int, est_usd: float, tree_id: str) -> None:
        """Plan mode: book the pre-flight estimate against the fallback line without calling the
        API, so a `--plan` run exhausts the budget at the same tree a real run would."""
        self.fallback_spent_usd += est_usd
        self.calls.append({"tree_id": tree_id, "tier": tier, "model": model, "simulated": True, "usd": round(est_usd, 6)})

    def to_dict(self) -> dict:
        return {
            "fallback_allowed_usd": round(self.fallback_allowed_usd, 4),
            "fallback_spent_usd": round(self.fallback_spent_usd, 4),
            "fallback_remaining_usd": round(self.fallback_remaining_usd, 4),
            "sonnet_spent_usd": round(self.sonnet_spent_usd, 4),
            "total_spent_usd": round(self.fallback_spent_usd + self.sonnet_spent_usd, 4),
            "fallback_trees": self.fallback_trees,
            "refused_trees": self.refused_trees,
            "n_paid_calls": len(self.calls),
        }


# ── manifest / coverage ──────────────────────────────────────────────────────

def load_manifest() -> dict:
    if not MANIFEST.is_file():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def window_status(ticker: str, window: Sequence[str], indexes: Mapping[str, dict], manifest: Mapping) -> dict[str, str]:
    """present | missing | no_event per clock-window quarter. An indexed transcript is present
    regardless of what the manifest says; otherwise the manifest status wins; otherwise missing."""
    periods = ((manifest.get("tickers") or {}).get(ticker) or {}).get("periods") or {}
    out: dict[str, str] = {}
    for q in window:
        if q in indexes:
            out[q] = "present"
        else:
            st = str((periods.get(q) or {}).get("status") or "missing")
            out[q] = "present" if st == "present" else st
    return out


def clock_passed(clock: str | None, indexes: Mapping[str, dict], now_fiscal: str | None) -> bool:
    if not clock or fiscal_key(clock) < (0, 0):
        return False
    latest = max((fiscal_key(q) for q in indexes), default=(-1, -1))
    if now_fiscal and fiscal_key(now_fiscal) >= (0, 0):
        latest = max(latest, fiscal_key(now_fiscal))
    return latest > fiscal_key(clock)


# ── evidence verification ────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
_QUOTE_MAP = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def _loose(s: str) -> str:
    return _WS_RE.sub(" ", str(s or "").translate(_QUOTE_MAP)).strip().lower()


def excerpt_in_evidence(excerpt: object, evidence: Sequence[Mapping]) -> bool:
    """True when the LLM's supporting excerpt is a verbatim (whitespace/quote-insensitive) substring
    of a retrieved excerpt, or contains one whole."""
    needle = _loose(str(excerpt or ""))
    if len(needle) < 12:
        return False
    for ev in evidence:
        hay = _loose(str(ev.get("text") or ""))
        if needle in hay or (len(hay) >= 12 and hay in needle):
            return True
    return False


# ── prompts ──────────────────────────────────────────────────────────────────

def _build_user_content(tree: Mapping, match: MatchBlock, evidence: Sequence[Mapping], tier: int | None) -> str:
    ticker = tree.get("ticker", "?")
    tree_id = tree.get("tree_id", "?")
    kind = tree.get("kind", "promise")
    seed = tree.get("seed") or {}
    seed_fp = seed.get("fiscal_period", "?")
    seed_excerpt = str(seed.get("excerpt") or "").strip()
    clock = tree.get("clock") or seed.get("clock")

    lines = [
        f"Company: {ticker}",
        f"Tree: {tree_id}",
        f"Kind: {kind}",
        f"Seed fiscal period: {seed_fp}",
        f"Clock (expected resolution): {clock or 'none stated'}",
        f"Anchors being tracked: {', '.join(match.anchors) or 'not specified'}",
        "",
        "SEED STATEMENT:",
        f"  {seed_excerpt[:400]}",
        "",
        f"POST-SEED EVIDENCE ({len(evidence)} management excerpts from raw transcripts, retrieval tier {tier}):",
    ]
    for i, ev in enumerate(evidence, 1):
        fp = ev.get("fiscal_period", "?")
        spk = ev.get("speaker", "?")
        role = ev.get("role", "?")
        sec = ev.get("section", "?")
        text = str(ev.get("text") or "").strip()[:MAX_EXCERPT_CHARS]
        lines.append(f"  [{i}] fiscal={fp} speaker={spk} ({role}, {sec}) matched={', '.join(ev.get('matched_terms') or [])}")
        lines.append(f"      {text}")
    return "\n".join(lines)


def _proposed_node_py(result: Mapping, tree: Mapping) -> str:
    edge = result.get("proposed_edge", "none")
    fiscal = result.get("proposed_fiscal") or ""
    excerpt = str(result.get("supporting_excerpt") or "").replace('"', '\\"')
    ticker = tree.get("ticker", "")
    tree_id = tree.get("tree_id", "")
    confidence = result.get("confidence", "low")
    lines = [
        "        # Proposed terminal node — review before inserting",
        "        {",
        f'            "edge": "{edge}",',
        f'            "fiscal_period": "{fiscal}",',
        f'            "excerpt": ("{excerpt[:280]}"),',
        '            "dimension": "terminal",',
        '            "status": "verbatim",',
        f'            # confidence={confidence}, tree={ticker}/{tree_id}, source=transcripts_raw',
        "        },",
    ]
    return "\n".join(lines)


# ── LLM calls ────────────────────────────────────────────────────────────────

def _call_json(client: Any, *, model: str, system: str, user: str, max_tokens: int) -> tuple[Any, int, int]:
    """One messages.create call → (parsed json, input_tokens, output_tokens)."""
    from src.llm.anthropic_client import extract_json  # local import keeps --plan free of the SDK

    raw = client.client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    usage = client._usage_from_response(raw.usage)
    client._accumulate_usage(usage)
    text = "".join(block.text for block in raw.content if block.type == "text")
    return extract_json(text), usage.input_tokens, usage.output_tokens


def sonnet_judgment(client: Any, tree: Mapping, match: MatchBlock, evidence: Sequence[Mapping], tier: int,
                    budget: Budget) -> tuple[dict | None, dict]:
    """Sonnet verdict on the evidence. Tier 0-3 evidence is metered only; Tier 5 (Haiku-triaged)
    evidence is on the fallback line and therefore pre-flight gated like the triage itself."""
    user = _build_user_content(tree, match, evidence, tier)
    est_in = est_tokens(SYSTEM_PROMPT + user)
    est = est_usd(MODEL, est_in, 200)
    ledger = {"model": MODEL, "est_tokens": est_in + 200, "est_usd": round(est, 5)}
    if tier >= 4 and not budget.can_afford(est):
        ledger["skipped"] = "fallback_budget_exhausted"
        return None, ledger
    try:
        result, tin, tout = _call_json(client, model=MODEL, system=SYSTEM_PROMPT, user=user, max_tokens=SONNET_MAX_OUTPUT)
    except Exception as exc:  # noqa: BLE001
        ledger["error"] = str(exc)[:300]
        return None, ledger
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        ledger["error"] = f"expected dict, got {type(result).__name__}"
        return None, ledger
    usd = est_usd(MODEL, tin, tout)
    budget.charge(model=MODEL, tier=tier, usd=usd, input_tokens=tin, output_tokens=tout, tree_id=str(tree.get("tree_id")))
    ledger.update({"actual_tokens": tin + tout, "usd": round(usd, 5)})
    return result, ledger


def _triage_corpus(indexes: Mapping[str, dict], window: Sequence[str]) -> tuple[list[dict], str]:
    """Numbered management/unknown sentences from the clock-window transcripts."""
    rows: list[dict] = []
    lines: list[str] = []
    total = 0
    for q in window:
        idx = indexes.get(q)
        if not idx:
            continue
        for turn in _eligible_turns(idx):
            for s in turn.get("sentences") or []:
                text = str(s.get("text") or "").strip()
                if not text:
                    continue
                rid = len(rows)
                line = f"[{rid}] ({q} {turn.get('speaker')}) {text}"
                total += len(line) + 1
                if total > TRIAGE_MAX_CHARS:
                    return rows, "\n".join(lines)  # rows == lines: never offer an id Haiku cannot see
                rows.append({"id": rid, "fiscal_period": q, "turn": turn, "sid": int(s.get("sid", 0)), "text": text})
                lines.append(line)
    return rows, "\n".join(lines)


def haiku_triage(client: Any, tree: Mapping, match: MatchBlock, indexes: Mapping[str, dict], window: Sequence[str],
                 budget: Budget, *, plan_only: bool) -> tuple[list[dict] | None, dict]:
    """Tier 4: Haiku returns sentence ids that reference the anchors. Pre-flight budget gated."""
    rows, corpus = _triage_corpus(indexes, window)
    user = f"ANCHORS: {', '.join(match.anchors)}\nCONTEXT TERMS: {', '.join(match.context) or '-'}\n\nSENTENCES:\n{corpus}"
    est_in = est_tokens(TRIAGE_SYSTEM_PROMPT + user)
    est = est_usd(TRIAGE_MODEL, est_in, 100)
    ledger = {"model": TRIAGE_MODEL, "est_tokens": est_in + 100, "est_usd": round(est, 5), "n_sentences_offered": len(rows)}
    if not rows:
        ledger["skipped"] = "no eligible sentences in window"
        return None, ledger
    if not budget.can_afford(est):
        ledger["skipped"] = "fallback_budget_exhausted"
        return None, ledger
    if plan_only:
        ledger["skipped"] = "plan mode"
        budget.reserve(model=TRIAGE_MODEL, tier=4, est_usd=est, tree_id=str(tree.get("tree_id")))
        return None, ledger
    try:
        ids, tin, tout = _call_json(client, model=TRIAGE_MODEL, system=TRIAGE_SYSTEM_PROMPT, user=user, max_tokens=TRIAGE_MAX_OUTPUT)
    except Exception as exc:  # noqa: BLE001
        ledger["error"] = str(exc)[:300]
        return None, ledger
    usd = est_usd(TRIAGE_MODEL, tin, tout)
    budget.charge(model=TRIAGE_MODEL, tier=4, usd=usd, input_tokens=tin, output_tokens=tout, tree_id=str(tree.get("tree_id")))
    ledger.update({"actual_tokens": tin + tout, "usd": round(usd, 5)})
    if not isinstance(ids, list):
        ids = []
    picked: list[dict] = []
    for i in ids:
        try:
            r = rows[int(i)]
        except (TypeError, ValueError, IndexError):
            continue
        turn = r["turn"]
        sentences = turn.get("sentences") or []
        pos = next((k for k, s in enumerate(sentences) if int(s.get("sid", k)) == r["sid"]), None)
        span = sentences[max(0, (pos or 0) - 1): (pos or 0) + 2] if pos is not None else [{"text": r["text"]}]
        picked.append({
            "fiscal_period": r["fiscal_period"], "speaker": turn.get("speaker"), "role": turn.get("role"),
            "section": turn.get("section"), "turn_idx": int(turn.get("idx", -1)), "sid": r["sid"],
            "matched_terms": ["haiku-triage"], "tier": 4,
            "text": " ".join(str(s.get("text") or "").strip() for s in span).strip(),
        })
    ledger["n_pointed"] = len(picked)
    return picked[:MAX_EVIDENCE_PER_TREE], ledger


# ── per-tree scoring ─────────────────────────────────────────────────────────

def _needs_review(tree: Mapping, reason: str, res: RetrievalResult, match: MatchBlock, wstatus: Mapping[str, str],
                  detail: str = "") -> dict:
    seed = tree.get("seed") or {}
    return {
        "ticker": str(tree.get("ticker") or "").upper(),
        "tree_id": tree.get("tree_id"),
        "kind": tree.get("kind"),
        "title": tree.get("title"),
        "reason": reason,
        "detail": detail,
        "seed_fiscal": seed.get("fiscal_period"),
        "clock": tree.get("clock") or seed.get("clock"),
        "clock_window": list(res.window),
        "transcripts_present": sum(1 for v in wstatus.values() if v == "present"),
        "transcripts_missing": [q for q, v in wstatus.items() if v != "present"],
        "quarters_searched": len(res.quarters_searched),
        "seed_excerpt": str(seed.get("excerpt") or "")[:300],
        "anchors_tried": list(match.anchors),
        "context_tried": list(match.context),
        "generic_inferred": dict(res.generic_map),
        "retrieval_tier": res.tier,
    }


def _retrieval_ledger(res: RetrievalResult, wstatus: Mapping[str, str], llm: Mapping | None) -> dict:
    return {
        "tier": res.tier,
        "n_sentences": len(res.excerpts),
        "n_hits_total": res.n_hits_total,
        "quarters_searched": list(res.quarters_searched),
        "window": list(res.window),
        "window_missing": [q for q, v in wstatus.items() if v != "present"],
        "generic_inferred": dict(res.generic_map),
        "alias_snapshot": dict(res.alias_snapshot),
        "notes": list(res.notes),
        "est_tokens": (llm or {}).get("est_tokens"),
        "actual_tokens": (llm or {}).get("actual_tokens"),
        "usd": (llm or {}).get("usd"),
        "est_usd": (llm or {}).get("est_usd"),
        "triage": (llm or {}).get("triage"),
    }


def score_tree(
    tree: Mapping,
    indexes: Mapping[str, dict],
    manifest: Mapping,
    budget: Budget,
    client: Any,
    *,
    plan_only: bool,
    now_fiscal: str | None,
) -> tuple[dict | None, dict | None]:
    """Return (candidate, needs_review_item); either may be None (both None never happens)."""
    ticker = str(tree.get("ticker") or "").upper()
    tree_id = str(tree.get("tree_id") or "?")
    seed = tree.get("seed") or {}
    seed_fp = str(seed.get("fiscal_period") or "")
    clock = str(tree.get("clock") or seed.get("clock") or "").strip() or None
    match = match_block_for(tree)
    empty = RetrievalResult(tier=None)

    if not indexes:
        return None, _needs_review(tree, "no_transcripts_indexed", empty, match, {}, "no indexed transcripts for ticker")

    res = retrieve(tree, indexes, now_fiscal=now_fiscal)
    wstatus = window_status(ticker, res.window, indexes, manifest)
    window_missing = [q for q, v in wstatus.items() if v != "present"]
    passed = clock_passed(clock, indexes, now_fiscal)

    base = {
        "ticker": ticker,
        "tree_id": tree_id,
        "kind": tree.get("kind"),
        "title": tree.get("title"),
        "seed_fiscal": seed_fp,
        "clock": clock,
        "objects": [str(o) for o in (tree.get("objects") or [])],
        "anchors": list(match.anchors),
    }

    evidence = list(res.excerpts[:MAX_EVIDENCE_PER_TREE])
    tier = res.tier
    llm_ledger: dict = {}

    # ── paid line: only when the free ladder found nothing ──
    if not evidence:
        all_numeric = bool(match.anchors) and all(is_numeric_anchor(a) for a in match.anchors)
        if all_numeric:
            return None, _needs_review(tree, "numeric_target_no_strict_match", res, match, wstatus,
                                       "all anchors numeric; strict matching found nothing")
        if not clock:
            return None, _needs_review(tree, "no_clock_open_goal", res, match, wstatus,
                                       "no clock: tier 3 searched all post-seed quarters, zero hits; no principled window to buy")
        if window_missing:
            return None, _needs_review(tree, "transcript_missing", res, match, wstatus,
                                       f"clock-window transcripts missing: {', '.join(window_missing)}")
        def zero_evidence(reason: str, detail: str, extra_note: str) -> tuple[dict | None, dict]:
            """needs_review item for a tree with no evidence at all. When the expired guard is
            satisfied (clock passed, window complete) the deterministic `expired` proposal rides
            along for the reviewer — whichever path (no budget, triage refused, budget exhausted)
            led here. It stays a needs_review item either way."""
            item = _needs_review(tree, reason, res, match, wstatus, detail)
            if not (passed and not window_missing):
                return None, item
            item["expired_eligible"] = True
            cand = dict(base)
            cand.update({
                "n_evidence_excerpts": 0,
                "proposed_edge": "expired",
                "proposed_fiscal": clock,
                "supporting_excerpt": None,
                "excerpt_verified": None,
                "confidence": "medium",
                "reasoning": (f"Clock {clock} has passed. Tiers 0-3 searched all {len(res.window)} clock-window "
                              f"transcripts (all present) for {', '.join(match.anchors)} and found zero management "
                              f"sentences. {extra_note}"),
                "source": "retrieval",
                "retrieval": _retrieval_ledger(res, wstatus, llm_ledger or None),
                "proposed_node_py": _proposed_node_py({"proposed_edge": "expired", "proposed_fiscal": clock,
                                                       "supporting_excerpt": "", "confidence": "medium"}, tree),
            })
            return cand, item

        if budget.fallback_allowed_usd > 0:
            pointed, tri = haiku_triage(client, tree, match, indexes, res.window, budget, plan_only=plan_only)
            llm_ledger["triage"] = tri
            if tri.get("skipped") == "fallback_budget_exhausted":
                budget.refused_trees += 1
                return zero_evidence("fallback_budget_exhausted",
                                     f"triage est ${tri.get('est_usd')} > remaining ${budget.fallback_remaining_usd:.2f}",
                                     "Haiku triage skipped: fallback budget exhausted.")
            if plan_only:
                cand = dict(base)
                cand.update({"plan": True, "proposed_edge": None, "confidence": None,
                             "n_evidence_excerpts": 0, "retrieval": _retrieval_ledger(res, wstatus, llm_ledger),
                             "note": "plan: would run Haiku triage (tier 4); estimate reserved against the fallback budget"})
                return cand, None
            budget.fallback_trees += 1
            if not pointed:
                budget.refused_trees += 1
                return zero_evidence("no_evidence_retrieved",
                                     "tiers 0-3 zero; Haiku triage pointed at no sentences (refused)",
                                     "Haiku triage pointed at no sentences.")
            evidence, tier = pointed, 5
        else:
            return zero_evidence("no_evidence_retrieved",
                                 "tiers 0-3 searched every present clock-window transcript, zero hits",
                                 "No LLM call.")

    # ── judgment on retrieved (or triaged) evidence ──
    if plan_only:
        user = _build_user_content(tree, match, evidence, tier)
        est_in = est_tokens(SYSTEM_PROMPT + user)
        llm_ledger.update({"model": MODEL, "est_tokens": est_in + 200, "est_usd": round(est_usd(MODEL, est_in, 200), 5)})
        cand = dict(base)
        cand.update({"plan": True, "proposed_edge": None, "confidence": None,
                     "n_evidence_excerpts": len(evidence), "retrieval": _retrieval_ledger(res, wstatus, llm_ledger)})
        return cand, None

    result, sonnet_ledger = sonnet_judgment(client, tree, match, evidence, tier or 0, budget)
    llm_ledger.update(sonnet_ledger)
    if result is None:
        if sonnet_ledger.get("skipped") == "fallback_budget_exhausted":
            budget.refused_trees += 1
            return None, _needs_review(tree, "fallback_budget_exhausted", res, match, wstatus,
                                       f"tier-5 Sonnet est ${sonnet_ledger.get('est_usd')} > remaining "
                                       f"${budget.fallback_remaining_usd:.2f} (triage ran, verdict not bought)")
        return None, _needs_review(tree, "llm_failed", res, match, wstatus, str(sonnet_ledger.get("error") or ""))

    edge = str(result.get("proposed_edge") or "none")
    confidence = str(result.get("confidence") or "low")
    verified = excerpt_in_evidence(result.get("supporting_excerpt"), evidence) if edge in ("delivered", "hit", "missed") else None

    cand = dict(base)
    cand.update({
        "n_evidence_excerpts": len(evidence),
        "proposed_edge": edge,
        "proposed_fiscal": result.get("proposed_fiscal"),
        "supporting_excerpt": result.get("supporting_excerpt"),
        "excerpt_verified": verified,
        "confidence": confidence,
        "reasoning": result.get("reasoning"),
        "source": "sonnet" if tier != 5 else "haiku+sonnet",
        "evidence": [{k: ev.get(k) for k in ("fiscal_period", "speaker", "role", "section", "matched_terms", "tier", "text")}
                     for ev in evidence],
        "retrieval": _retrieval_ledger(res, wstatus, llm_ledger),
        "proposed_node_py": _proposed_node_py(result, tree),
    })

    review: dict | None = None
    if edge == "expired" and (not passed or window_missing):
        # Guard: the LLM may not expire a tree whose clock is open or whose window has gaps.
        cand["proposed_edge"] = "none"
        cand["guard"] = "expired_guard: clock not passed or window incomplete — downgraded to none"
        review = _needs_review(tree, "transcript_missing" if window_missing else "expired_guard", res, match, wstatus,
                               "LLM proposed expired; " + ("window incomplete" if window_missing else "clock not passed or no clock"))
    elif edge in ("delivered", "hit", "missed") and confidence == "low":
        review = _needs_review(tree, "llm_low_confidence", res, match, wstatus,
                               f"LLM proposed {edge} at low confidence")
    elif edge in ("delivered", "hit", "missed") and verified is False:
        review = _needs_review(tree, "llm_low_confidence", res, match, wstatus,
                               "supporting excerpt is not verbatim in the retrieved evidence")
    return cand, review


# ── output ───────────────────────────────────────────────────────────────────

def _write_output(
    candidates: list[dict],
    needs_review: list[dict],
    *,
    n_skipped_closed: int,
    n_skipped_gold: int,
    budget: Budget,
    coverage: Mapping,
    usage: Mapping | None,
    plan_only: bool,
    complete: bool,
) -> dict:
    n_actionable = sum(
        1 for c in candidates
        if c.get("proposed_edge") not in (None, "none") and c.get("confidence") in ("high", "medium")
    )
    n_unverified = sum(1 for c in candidates if c.get("excerpt_verified") is False)
    reasons: dict[str, int] = {}
    for item in needs_review:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    output = {
        "note": ("PLAN MODE: no API calls were made; est_* fields are pre-flight estimates." if plan_only
                 else "LLM-proposed terminal verdicts on raw-transcript evidence. Do not auto-insert. Human review required."),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "plan_mode": plan_only,
        "evidence_source": "transcripts_raw via scripts/_desk_retrieval.py (Tier 0-3 free; Tier 4-5 budget-gated)",
        "n_open_trees_scored": len(candidates),
        "n_needs_review": len(needs_review),
        "needs_review_reasons": reasons,
        "n_skipped_closed": n_skipped_closed,
        "n_skipped_gold": n_skipped_gold,
        "n_actionable": n_actionable,
        "n_excerpt_unverified": n_unverified,
        "budget": budget.to_dict(),
        "usage": dict(usage or {}),
        "coverage": dict(coverage),
        "tier_counts": _tier_counts(candidates),
        "needs_review": needs_review,
        "candidates": candidates,
        "paid_calls": budget.calls,
    }
    out_path = _out_path(plan_only)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    return output


def _tier_counts(candidates: Sequence[Mapping]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in candidates:
        t = ((c.get("retrieval") or {}).get("tier"))
        key = "none" if t is None else str(t)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _usage(client: Any) -> dict:
    if client is None:
        return {}
    return {
        "input_tokens": client.total_input_tokens,
        "output_tokens": client.total_output_tokens,
        "cache_creation_tokens": client.total_cache_creation_tokens,
        "cache_read_tokens": client.total_cache_read_tokens,
    }


# ── main ─────────────────────────────────────────────────────────────────────

def _open_trees(book: Mapping) -> list[dict]:
    trees = book.get("trees") or []
    return [t for t in trees if t.get("open") or t.get("state") == "open"]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", action="store_true", help="simulate: run Tiers 0-3, estimate tokens/USD, zero API calls")
    ap.add_argument("--fallback-budget-usd", type=float, default=0.0,
                    help="run-level budget for the paid Tier 4-5 fallback (default 0.00 = closed)")
    ap.add_argument("--ticker", action="append", help="restrict to ticker(s)")
    ap.add_argument("--tree", action="append", help="restrict to tree_id(s)")
    ap.add_argument("--limit", type=int, default=0, help="score at most N trees")
    ap.add_argument("--now-fiscal", default=None, help="override the 'latest quarter' used by the expired guard")
    args = ap.parse_args(argv)

    plan_only = bool(args.plan)
    client = None
    if not plan_only:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("Error: ANTHROPIC_API_KEY not set. Add it to .env (or use --plan).", file=sys.stderr)
            return 1
        from src.llm.anthropic_client import AnthropicClient

        client = AnthropicClient(api_key=api_key, model=MODEL, max_retries=1)

    budget = Budget(fallback_allowed_usd=max(0.0, float(args.fallback_budget_usd)))
    manifest = load_manifest()
    books = [("desk_ops_v2", load_desk_trees_ops_v2()), ("desk_hc_v2", load_desk_trees_hc_v2())]

    todo: list[tuple[str, dict]] = []
    n_skipped_closed = 0
    n_skipped_gold = 0
    want_t = {t.upper() for t in (args.ticker or [])}
    want_id = set(args.tree or [])
    for book_name, book in books:
        trees = book.get("trees") or []
        opens = _open_trees(book)
        n_skipped_closed += len(trees) - len(opens)
        for tree in opens:
            ticker = str(tree.get("ticker") or "").upper()
            if ticker in GOLD_TICKERS:
                n_skipped_gold += 1
                continue
            if want_t and ticker not in want_t:
                continue
            if want_id and tree.get("tree_id") not in want_id:
                continue
            todo.append((book_name, tree))
    if args.limit:
        todo = todo[: args.limit]
    # Group by ticker (stable within a ticker) so a ticker's ~40 index files load exactly once;
    # the LazyTickerIndexes LRU only keeps two tickers and a scattered order re-reads them.
    first_seen: dict[str, int] = {}
    for _, tree in todo:
        first_seen.setdefault(str(tree.get("ticker") or "").upper(), len(first_seen))
    todo.sort(key=lambda bt: first_seen[str(bt[1].get("ticker") or "").upper()])

    lazy = LazyTickerIndexes([t.get("ticker") for _, t in todo], keep=2)
    candidates: list[dict] = []
    needs_review: list[dict] = []
    coverage = {"trees": len(todo), "window_quarters": 0, "window_present": 0, "window_missing": 0, "trees_no_index": 0}
    merged_coverage = False
    filtered = bool(want_t or want_id or args.limit)
    if filtered and not plan_only and OUT.is_file():
        # A filtered live run re-scores a subset: keep every other tree's prior result in the file.
        try:
            prior = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prior = {}
        if not prior.get("plan_mode"):
            rescored = {t.get("tree_id") for _, t in todo}
            candidates = [c for c in prior.get("candidates") or [] if c.get("tree_id") not in rescored]
            needs_review = [r for r in prior.get("needs_review") or [] if r.get("tree_id") not in rescored]
            pb = prior.get("budget") or {}
            budget.sonnet_spent_usd += float(pb.get("sonnet_spent_usd") or 0)
            budget.fallback_spent_usd += float(pb.get("fallback_spent_usd") or 0)
            budget.fallback_trees += int(pb.get("fallback_trees") or 0)
            budget.refused_trees += int(pb.get("refused_trees") or 0)
            budget.calls.extend(c for c in prior.get("paid_calls") or [] if c.get("tree_id") not in rescored)
            if prior.get("coverage"):
                coverage = dict(prior["coverage"])  # whole-run coverage is unchanged by a re-score
                merged_coverage = True
            print(f"  merging into prior run: keeping {len(candidates)} candidates / {len(needs_review)} needs_review")
    print(f"{'PLAN' if plan_only else 'RUN'}: {len(todo)} open trees · fallback budget ${budget.fallback_allowed_usd:.2f}")
    for book_name, tree in todo:
        ticker = str(tree.get("ticker") or "").upper()
        tree_id = tree.get("tree_id", "?")
        try:
            indexes = lazy[ticker]
        except KeyError:
            indexes = {}
        cand, review = score_tree(tree, indexes, manifest, budget, client, plan_only=plan_only, now_fiscal=args.now_fiscal)
        ledger = (cand or {}).get("retrieval") or {}
        if not merged_coverage:
            if not indexes:
                coverage["trees_no_index"] += 1
            window = ledger.get("window") or (review or {}).get("clock_window") or []
            missing = ledger.get("window_missing") or (review or {}).get("transcripts_missing") or []
            coverage["window_quarters"] += len(window)
            coverage["window_missing"] += len(missing)
            coverage["window_present"] += len(window) - len(missing)
        if cand is not None:
            cand["book"] = book_name
            candidates.append(cand)
        if review is not None:
            review["book"] = book_name
            needs_review.append(review)

        tier = ledger.get("tier")
        n_ev = (cand or {}).get("n_evidence_excerpts", 0)
        if plan_only:
            est = ledger.get("est_usd") or ((ledger.get("triage") or {}).get("est_usd"))
            what = f"tier {tier} · {n_ev} excerpts · est ${est or 0:.4f}" if cand else f"needs_review:{review['reason']}"
        elif cand:
            flag = " · excerpt UNVERIFIED" if cand.get("excerpt_verified") is False else ""
            what = f"tier {tier} · {n_ev} excerpts → {cand.get('proposed_edge')} [{cand.get('confidence')}]{flag}"
            if review:
                what += f" · needs_review:{review['reason']}"
        else:
            what = f"needs_review:{review['reason']}"
        print(f"  {ticker}/{tree_id}: {what}")
        _write_output(candidates, needs_review, n_skipped_closed=n_skipped_closed, n_skipped_gold=n_skipped_gold,
                      budget=budget, coverage=coverage, usage=_usage(client), plan_only=plan_only, complete=False)

    output = _write_output(candidates, needs_review, n_skipped_closed=n_skipped_closed, n_skipped_gold=n_skipped_gold,
                           budget=budget, coverage=coverage, usage=_usage(client), plan_only=plan_only, complete=True)

    est_total = sum(float((c.get("retrieval") or {}).get("est_usd") or 0) for c in candidates)
    est_total += sum(float(((c.get("retrieval") or {}).get("triage") or {}).get("est_usd") or 0) for c in candidates)
    print(f"\nWrote {_out_path(plan_only)}")
    print(f"  Trees scored      : {len(candidates)}   tiers: {output['tier_counts']}")
    print(f"  Needs review      : {len(needs_review)}   {output['needs_review_reasons']}")
    print(f"  Actionable        : {output['n_actionable']}   excerpt unverified: {output['n_excerpt_unverified']}")
    print(f"  Coverage          : {coverage}")
    if plan_only:
        print(f"  Estimated spend   : ${est_total:.4f} (Sonnet on retrieved evidence"
              f"{' + Haiku triage' if budget.fallback_allowed_usd > 0 else ''}); zero API calls made")
    else:
        print(f"  Spend             : {output['budget']}")
        if client is not None:
            print(f"  {client.usage_summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
