"""LLM-assisted bulk seed proposal for ops + HC claims desk.

Reads all missed cue-queue rows for every ops/HC ticker and calls Claude
once per ticker to propose 3–8 strong seed candidates.  Each candidate also
carries a proposed retrieval ``match`` block (anchors / context / exclude),
post-processed deterministically by ``propose_match_block``.  Outputs
data/seed_batch_candidates.json for human review.

Rules inherited from the desk:
- Does NOT auto-insert into any catalog.
- Gold book (NVDA) is excluded — "No new LLM on the gold run".
- Output file header mirrors desk_harden_candidates.json convention.
"""
from __future__ import annotations

import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from scripts._desk_trees_v2 import BUCKETS  # noqa: E402
from scripts._desk_trees_v2_ops import TECH_TICKERS  # noqa: E402
from scripts._desk_trees_v2_hc import HC_TICKERS  # noqa: E402
from src.llm.anthropic_client import AnthropicClient, extract_json  # noqa: E402

# ── constants ────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-5"

OUT = ROOT / "data" / "seed_batch_candidates.json"
CROSS = ROOT / "Structured Narrative" / "output" / "cross_company" / "json"

# Regime-transition tickers surfaced first in output (most analytically valuable)
PRIORITY_TICKERS = ("IBM", "ABBV", "JNJ", "MDT", "UNH", "DHR", "SYK")

# Tickers excluded from LLM seeding (gold has its own pipeline)
GOLD_EXCLUDE = frozenset({"NVDA"})

_BUCKET_LIST = ", ".join(BUCKETS)

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are an experienced equity analyst reviewing forward-looking statements from
    earnings calls. Your task: given a list of excerpts from a single company's
    earnings calls, propose the 3–8 strongest claims-desk seed candidates.

    A strong seed:
    - Is a SPECIFIC, TRACKABLE commitment or goal — management said they WILL do
      something concrete, or WANT to achieve something measurable.
    - Has at least one clear "object" (a product, metric, initiative, or entity)
      that can be looked up in future call transcripts.
    - Is NOT routine quarterly guidance, vague aspiration, or boilerplate rhetoric.
    - Has a realistic resolution window: 1–12 quarters.

    Classify each candidate as:
      kind: "promise"  — management commits to a future action (will, expect to, plan to)
      kind: "goal"     — management states a desire/ambition (want, aim, targeting)

    Use EXACTLY one of these buckets (from the desk's BUCKETS constant):
      __BUCKET_LIST__

    For the seed.clock field:
    - Set to the fiscal period where you expect resolution (e.g. "FY2020-Q2")
      if management gives a timeframe. Otherwise null.

    For seed.status:
    - "verbatim" if the excerpt is a direct, unambiguous quote.
    - "composite" if the claim combines multiple sentences or needs interpretation.

    For the match block (the retrieval contract used to find follow-ups in later
    transcripts):
    - "anchors": 1–4 SPECIFIC nouns copied from the excerpt — product names, event
      names, program names, deal/partner names, or numeric targets ("$2 billion",
      "45%", "1 million patients"). NOT dates and NOT clock words ("mid-2019",
      "2022", "FY2020", "Q3", "September") — those belong in seed.clock.
    - "context": 3–8 co-occurrence words that distinguish THIS claim from the
      company's general use of the anchor (verbs like "launch"/"shipped", the
      metric, the segment, the counterparty). These may include months or years.
    - "exclude": phrases that would be false-positive anchor hits (e.g. anchor
      "BUILD" → exclude "build out", "building"). May be an empty list.

    Respond with a JSON object:
    {
      "candidates": [
        {
          "tree_id": "ticker-slug-kebab",
          "title": "Short title (≤10 words)",
          "kind": "promise|goal",
          "bucket": "one_of_8",
          "objects": ["primary object", "alt name"],
          "match": {
            "anchors": ["specific noun or numeric target from the excerpt"],
            "context": ["co-occurrence word", "..."],
            "exclude": ["false-positive phrase", "..."]
          },
          "seed": {
            "fiscal_period": "FY20XX-QX",
            "claim_type": "forward_clock",
            "clock": "FY20XX-QX or null",
            "excerpt": "verbatim quote from the excerpt",
            "dimension": "dimension name from the excerpt metadata",
            "status": "verbatim|composite"
          },
          "confidence": "high|medium",
          "rationale": "1–2 sentences explaining why this is a strong seed"
        }
      ]
    }

    If there are no strong candidates among the excerpts, return {"candidates": []}.
    """
).strip().replace("__BUCKET_LIST__", _BUCKET_LIST)


# ── helpers ──────────────────────────────────────────────────────────────────

def _cue_queue_path(ticker: str) -> Path:
    return CROSS / f"desk_cue_queue_v2_{ticker.upper()}.json"


def _load_missed(ticker: str) -> list[dict]:
    path = _cue_queue_path(ticker)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("missed") or []
    return [dict(r) for r in rows if isinstance(r, Mapping)]


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def excerpt_verified(excerpt: object, source_rows: list[dict]) -> bool:
    """True if `excerpt` is contained in (or contains) a real cue-row excerpt.

    Mirrors the desk's verify_excerpts discipline: a seed the book builder
    cannot trace back to novelty_view text is rejected at build time, so the
    analyst should see that flag here first rather than discover it later.
    """
    want = _norm(excerpt)
    if len(want) < 24:
        return False
    for row in source_rows:
        have = _norm(row.get("excerpt"))
        if want in have or have in want:
            return True
    return False


# ── match block post-processing ──────────────────────────────────────────────

MAX_MATCH_ANCHORS = 6
MAX_MATCH_CONTEXT = 10
MAX_MATCH_EXCLUDE = 6

_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
)
# Tokens that, on their own, only ever describe *when* — never *what*.
_DATE_TOKEN_RE = re.compile(
    r"^(?:"
    r"(?:fy|cy)?20\d\d(?:e|a)?"                       # 2019, FY2020, CY2021, 2022E
    r"|(?:fy|cy)'?\d\d|'\d\d"                         # FY19, CY'22, '22 (bare "45" is a number, kept)
    r"|(?:mid|early|late|end)-?(?:fy|cy)?20\d\d"      # mid-2019, late-FY2020
    r"|q[1-4](?:-?(?:fy|cy)?20\d\d)?"                 # Q3, Q3-2019, Q1FY20
    r"|(?:fy|cy)20\d\d-q[1-4]"                        # FY2020-Q2
    r"|h[12](?:-?20\d\d)?"                            # H1, H2-2020
    r"|" + "|".join(_MONTHS) +
    r"|mid|early|late|end|of|the|by|in|first|second|third|fourth|half|quarter"
    r"|fiscal|calendar|year|years|fy|cy|next|this|coming|later"
    r")$"
)


def _is_date_like(term: str) -> bool:
    """True when every token of `term` is a date/clock token ("mid-2019", "Q3 2019",
    "second half of 2022", "September", "this year"). Terms that pair a date with a
    real noun ("2019 guidance", "$2 billion") are kept — the noun is what gets retrieved."""
    tokens = re.findall(r"[A-Za-z0-9']+", str(term).lower())
    if not tokens:
        return False
    has_date_marker = False
    for tok in tokens:
        if not _DATE_TOKEN_RE.match(tok):
            return False
        if re.search(r"\d|^(?:" + "|".join(_MONTHS) + r"|year|years|quarter|half)$", tok):
            has_date_marker = True
    return has_date_marker


def _clean_terms(raw: object, *, drop_dates: bool = False, cap: int) -> list[str]:
    """Whitespace-normalise, drop empties/date-like (optional), de-dup case-insensitively
    (keeping the first-seen spelling), cap."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        term = re.sub(r"\s+", " ", str(item or "")).strip()
        if not term:
            continue
        if drop_dates and _is_date_like(term):
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= cap:
            break
    return out


def propose_match_block(seed: dict, objects: list[str]) -> dict:
    """Deterministic match block for a proposed seed (candidate dict from the LLM).

    - anchors: the LLM's `match.anchors` if any survive cleaning, else `objects`
      (mirrors `match_block_for` in _desk_retrieval, which falls back to objects);
      date-like anchors are dropped, whitespace normalised, de-duplicated, capped at 6.
    - context: cleaned/deduped, capped at 10 (dates are allowed here).
    - exclude: cleaned/deduped, capped at 6.
    - generic: always None (infer from corpus frequency; a human may force it).
    """
    raw_match = seed.get("match") if isinstance(seed, Mapping) else None
    if not isinstance(raw_match, Mapping):
        raw_match = {}

    anchors = _clean_terms(raw_match.get("anchors"), drop_dates=True, cap=MAX_MATCH_ANCHORS)
    if not anchors:
        anchors = _clean_terms(objects, drop_dates=True, cap=MAX_MATCH_ANCHORS)
    context = _clean_terms(raw_match.get("context"), cap=MAX_MATCH_CONTEXT)
    exclude = _clean_terms(raw_match.get("exclude"), cap=MAX_MATCH_EXCLUDE)

    return {"anchors": anchors, "context": context, "exclude": exclude, "generic": None}


def _py_str(value: object) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _py_tuple(terms: list[str]) -> str:
    """Catalog-style tuple literal: (), ("x",), ("a", "b")."""
    if not terms:
        return "()"
    if len(terms) == 1:
        return f"({_py_str(terms[0])},)"
    return "(" + ", ".join(_py_str(t) for t in terms) + ")"


def _build_user_content(ticker: str, missed: list[dict]) -> str:
    lines = [f"Company: {ticker}", f"Number of excerpts: {len(missed)}", ""]
    for i, row in enumerate(missed, 1):
        fiscal = row.get("fiscal_period", "?")
        cls = row.get("class", "?")
        dim = row.get("dimension", "?")
        excerpt = str(row.get("excerpt", "")).strip()
        lines.append(
            f"[{i}] fiscal={fiscal} class={cls} dimension={dim}\n    {excerpt[:300]}"
        )
    return "\n".join(lines)


def _proposed_seed_py(candidate: dict, ticker: str) -> str:
    """Generate a ready-to-paste Python dict matching the catalog schema."""
    seed = candidate.get("seed") or {}
    objects = candidate.get("objects") or []
    objects_repr = "(" + ", ".join(f'"{o}"' for o in objects) + ",)"
    match = candidate.get("match")
    if not isinstance(match, Mapping) or "generic" not in match:
        match = propose_match_block(candidate, list(objects))
    clock = seed.get("clock")
    clock_repr = f'"{clock}"' if clock else "None"
    excerpt = str(seed.get("excerpt") or "").replace('"', '\\"')
    lines = [
        "    {",
        f'        "tree_id": "{candidate.get("tree_id", "")}",',
        f'        "ticker": "{ticker}",',
        f'        "kind": "{candidate.get("kind", "promise")}",',
        f'        "beat_id": "{(candidate.get("tree_id") or "").split("-", 1)[-1]}",',
        f'        "bucket": "{candidate.get("bucket", "")}",',
        f'        "title": "{candidate.get("title", "")}",',
        f'        "objects": {objects_repr},',
        '        "match": {',
        f'            "anchors": {_py_tuple(list(match.get("anchors") or []))},',
        f'            "context": {_py_tuple(list(match.get("context") or []))},',
        f'            "exclude": {_py_tuple(list(match.get("exclude") or []))},',
        "            \"generic\": None,",
        "        },",
        "        \"seed\": {",
        f'            "fiscal_period": "{seed.get("fiscal_period", "")}",',
        '            "claim_type": "forward_clock",',
        f'            "clock": {clock_repr},',
        f'            "excerpt": ("{excerpt}"),',
        f'            "dimension": "{seed.get("dimension", "")}",',
        f'            "status": "{seed.get("status", "verbatim")}",',
        "        },",
        '        "nodes": (),',
        "    },",
    ]
    return "\n".join(lines)


def _process_ticker(
    ticker: str,
    missed: list[dict],
    client: AnthropicClient,
) -> list[dict]:
    """Call LLM once for this ticker; return list of enriched candidate dicts."""
    user_content = _build_user_content(ticker, missed)
    label = f"{ticker}_seed_batch"
    try:
        raw = client.client.messages.create(
            model=client.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        client._accumulate_usage(client._usage_from_response(raw.usage))
        raw_text = "".join(
            block.text for block in raw.content if block.type == "text"
        )
        payload = extract_json(raw_text)
        if isinstance(payload, list):
            payload = {"candidates": payload}
        candidates = payload.get("candidates") or []
    except Exception as exc:
        print(f"  [WARN] LLM call failed for {ticker}: {exc}", file=sys.stderr)
        return []

    results = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        cand["ticker"] = ticker
        objects = cand.get("objects") or []
        if isinstance(objects, str):
            objects = [objects]
        cand["match"] = propose_match_block(cand, [str(o) for o in objects])
        cand["excerpt_verified"] = excerpt_verified(
            (cand.get("seed") or {}).get("excerpt"), missed
        )
        cand["proposed_seed_py"] = _proposed_seed_py(cand, ticker)
        results.append(cand)
    return results


def _write_output(
    candidates_by_ticker: dict[str, list[dict]],
    book_for: dict[str, str],
    total_cue_rows: int,
    *,
    complete: bool,
) -> dict:
    """Serialise current progress. Called after every ticker so a crash keeps work."""
    n_proposed = sum(len(v) for v in candidates_by_ticker.values())
    n_unverified = sum(
        1 for v in candidates_by_ticker.values() for c in v if not c.get("excerpt_verified")
    )
    output = {
        "note": "LLM-proposed seeds. Do not auto-insert. Human review required.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": complete,
        "n_tickers_scanned": len(candidates_by_ticker),
        "n_cue_rows_reviewed": total_cue_rows,
        "n_proposed_seeds": n_proposed,
        "n_excerpt_unverified": n_unverified,
        "priority_tickers": list(PRIORITY_TICKERS),
        "candidates_by_ticker": {
            ticker: [{**c, "book": book_for.get(ticker, "unknown")} for c in cands]
            for ticker, cands in candidates_by_ticker.items()
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set. Add it to .env.", file=sys.stderr)
        return 1

    client = AnthropicClient(api_key=api_key, model=MODEL, max_retries=1)

    # Build ticker list: priority tickers first, then rest alphabetically
    ops_tickers = [t for t in TECH_TICKERS if t not in GOLD_EXCLUDE]
    hc_tickers = list(HC_TICKERS)
    all_tickers = list(
        dict.fromkeys(
            list(PRIORITY_TICKERS)
            + sorted(t for t in ops_tickers if t not in PRIORITY_TICKERS)
            + sorted(t for t in hc_tickers if t not in PRIORITY_TICKERS)
        )
    )

    total_cue_rows = 0
    candidates_by_ticker: dict[str, list[dict]] = {}
    book_for: dict[str, str] = {
        **{t: "desk_ops_v2" for t in ops_tickers},
        **{t: "desk_hc_v2" for t in hc_tickers},
    }

    print(f"Scanning {len(all_tickers)} tickers...")
    for ticker in all_tickers:
        missed = _load_missed(ticker)
        if not missed:
            print(f"  {ticker}: no cue queue found — skipping")
            continue
        total_cue_rows += len(missed)
        print(f"  {ticker}: {len(missed)} missed rows → calling LLM...", end=" ", flush=True)
        proposals = _process_ticker(ticker, missed, client)
        candidates_by_ticker[ticker] = proposals
        n_unv = sum(1 for p in proposals if not p.get("excerpt_verified"))
        print(f"{len(proposals)} proposed" + (f" ({n_unv} excerpt unverified)" if n_unv else ""))
        _write_output(candidates_by_ticker, book_for, total_cue_rows, complete=False)

    output = _write_output(candidates_by_ticker, book_for, total_cue_rows, complete=True)

    print(f"\nWrote {OUT}")
    print(f"  Tickers scanned : {output['n_tickers_scanned']}")
    print(f"  Cue rows reviewed: {total_cue_rows}")
    print(f"  Seeds proposed  : {output['n_proposed_seeds']}")
    print(f"  Excerpt unverified: {output['n_excerpt_unverified']} (LLM paraphrased; re-cite before typing)")
    print(f"\n{client.usage_summary()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
