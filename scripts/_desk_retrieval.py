#!/usr/bin/env python3
"""Retrieval ladder over the sentence index for retrieval-first terminal scoring (Step 2).

Pure Python: no LLM, no network. Reads ``Structured Narrative/transcripts_index/*.json`` built by
scripts/_desk_transcript_index.py and resolves a desk tree (catalog dict or book dict) to verbatim
excerpts through four free tiers:

  Tier 0  clock window (seed+1 .. clock+2, max 6 quarters); exact normalised anchor hit;
          generic anchors need >=1 context term within +-3 sentences of the same turn
  Tier 1  as Tier 0 plus derived aliases (no-space / acronym forms)
  Tier 2  as Tier 1 with seed nouns added to the co-occurrence set (lets a generic anchor with no
          catalog context resolve)
  Tier 3  Tier 0-2 rules over every post-seed indexed quarter; trees without a clock start here

The ladder stops at the first tier that returns >=1 excerpt. Speakers with role analyst / operator
/ ir are never candidates; management and unknown are (unknown ranks lower). Anchors, aliases,
context and exclude terms are normalised with the shared ``normalize_text`` and matched on token
boundaries in the stored ``norm`` field. Exclude terms are blanked out of ``norm`` before anchor
matching. Numbers stay strict.

CLI:
  python scripts/_desk_retrieval.py --alias-audit [--ticker T] [--tree TREE_ID] [--out PATH]
  python scripts/_desk_retrieval.py --show TREE_ID

NVDA (gold book) is excluded everywhere.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_transcript_backfill import clock_window, fiscal_add  # noqa: E402
from scripts._desk_transcript_index import (  # noqa: E402
    INDEX_DIR,
    UNLABELED_SPEAKER,
    load_index,
    normalize_text,
)
from scripts._desk_trees_v2 import fiscal_key  # noqa: E402

GOLD_TICKERS = frozenset({"NVDA"})
GENERIC_THRESHOLD = 2.0  # sentence hits per indexed quarter above which an anchor is generic
MAX_EXCERPTS = 20
COOCCUR_WINDOW = 3  # +-N sentences, same turn
MAX_SEED_NOUNS = 12
MIN_SEED_NOUN_LEN = 4
ELIGIBLE_ROLES = frozenset({"management", "unknown"})
AUDIT_SAMPLES = 5

_INDEX_FILE_RE = re.compile(r"^([A-Z][A-Z0-9.\-]{0,9})_(FY\d{4}-Q[1-4])\.json$")
_CAP_WORD_RE = re.compile(r"^[A-Z][A-Za-z]*$")

# Function words plus earnings-call filler; seed nouns are what is left after removing these.
STOPWORDS = frozenset(
    """
    about above across after again against ahead almost along already also although always among
    another anything around based because become becomes been before begin beginning being believe
    below between both bring brought business businesses came cannot certain certainly come coming
    company companies continue continued could course currently customer customers deliver delivered
    doing done down drive driven during each earlier either else enough even ever every everything
    expect expected first five focus focused forward four from full further getting give given going
    good great growth guidance have having here high higher however include including increase
    increased into itself just know large larger last later least less level levels like little long
    look looking made make making many market maybe mean might more most much must next nothing number
    obviously once only other others over overall part particularly people perhaps period place plan
    plans pleased point pretty prior probably product products progress provide provided quarter
    quarters question quite rather really recently result results right said same second several
    share shares should significant since some something still strong such sure take taking term terms
    than that their them then there these they thing things think third this those though three
    through throughout time today together toward towards under until upon used using very want week
    well were what whatever when where whether which while whole will with within without would year
    years yes your
    """.split()
)


# ── match block ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MatchBlock:
    anchors: tuple[str, ...]
    context: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    generic: bool | None = None


def _terms(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = (raw,)
    out: list[str] = []
    for item in raw:  # type: ignore[union-attr]
        term = str(item).strip()
        if term and term not in out:
            out.append(term)
    return tuple(out)


def match_block_for(tree: Mapping) -> MatchBlock:
    """Retrieval contract for a catalog or book tree: ``tree["match"]`` when it carries anchors,
    otherwise anchors = objects with empty context / exclude and generic = None (infer).
    A match block with context / exclude but no anchors keeps those and takes anchors from objects."""
    match = tree.get("match")
    objects = _terms(tree.get("objects"))
    if not isinstance(match, Mapping):
        return MatchBlock(anchors=objects)
    anchors = _terms(match.get("anchors")) or objects
    generic = match.get("generic")
    if generic is not None and not isinstance(generic, bool):
        generic = None
    return MatchBlock(
        anchors=anchors,
        context=_terms(match.get("context")),
        exclude=_terms(match.get("exclude")),
        generic=generic,
    )


# ── anchors, aliases, seed nouns ────────────────────────────────────────────

_QUANTITY_TOKEN_RE = re.compile(r"^\$?\d[\d.,]*(?:%|x)?$")
# Words that may accompany a number inside a pure quantity ("$150 to $160 million", "10 percentage
# points", "about 45%") without making it a named thing. A token outside this set (a product code,
# a noun, a year+noun phrase) means the anchor is *specific* and its density is inferred instead.
_QUANTITY_WORDS = frozenset({
    "to", "and", "or", "of", "about", "approximately", "roughly", "around", "over", "under", "nearly",
    "almost", "at", "least", "than", "more", "less", "up", "down",
    "million", "billion", "trillion", "thousand", "percent", "percentage", "point", "basi", "bp", "x", "time",
})


def is_numeric_anchor(anchor: str) -> bool:
    """True for a pure quantity ("45%", "$2 billion", "$150 to $160 million", "1.5x"): every
    normalised token is a number / currency / percent or a scale / connector word, and at least one
    token carries a digit. Product codes ("S600", "VX-445", "AMG 510") and year+noun phrases
    ("2019 guidance") are NOT numeric — they are rare, specific names whose generic-ness is
    inferred from corpus density like any other anchor."""
    tokens = normalize_text(str(anchor)).split()
    if not tokens or not any(any(ch.isdigit() for ch in t) for t in tokens):
        return False
    return all(_QUANTITY_TOKEN_RE.match(t) or t in _QUANTITY_WORDS for t in tokens)


def derive_aliases(anchor: str) -> list[str]:
    """Normalised forms an anchor may appear as: the plain normalised form first, then a no-space
    variant for two-token alphabetic anchors ("co op" -> "coop") and an acronym for anchors of
    three or more capitalised words ("World Conference on Lung Cancer" -> "wclc"). Number, scale
    and percent forms are already canonical after normalize_text."""
    plain = normalize_text(str(anchor))
    if not plain:
        return []
    out: list[str] = [plain]
    tokens = plain.split()
    if len(tokens) == 2 and all(t.isalpha() for t in tokens):
        out.append("".join(tokens))
    cap_words = [w for w in str(anchor).split() if _CAP_WORD_RE.match(w)]
    if len(cap_words) >= 3 and len(str(anchor).split()) >= 3:
        acronym = "".join(w[0] for w in cap_words).lower()
        if len(acronym) >= 3:
            out.append(acronym)
    deduped: list[str] = []
    for form in out:
        if form and form not in deduped:
            deduped.append(form)
    return deduped


def seed_nouns(seed_excerpt: str) -> list[str]:
    """Content tokens of the seed excerpt: normalised, >= MIN_SEED_NOUN_LEN chars, alphabetic,
    not a stopword, de-duplicated in order, capped at MAX_SEED_NOUNS."""
    out: list[str] = []
    for tok in normalize_text(str(seed_excerpt or "")).split():
        if len(tok) < MIN_SEED_NOUN_LEN or not tok.isalpha() or tok in STOPWORDS:
            continue
        if tok not in out:
            out.append(tok)
        if len(out) >= MAX_SEED_NOUNS:
            break
    return out


# ── index access ────────────────────────────────────────────────────────────

def load_ticker_indexes(ticker: str) -> dict[str, dict]:
    """Every indexed period for a ticker: {fiscal_period: index}. Empty for gold tickers."""
    t = str(ticker or "").upper()
    if not t or t in GOLD_TICKERS or not INDEX_DIR.is_dir():
        return {}
    out: dict[str, dict] = {}
    for path in sorted(INDEX_DIR.glob(f"{t}_FY*.json")):
        m = _INDEX_FILE_RE.match(path.name)
        if not m or m.group(1) != t:
            continue
        idx = load_index(t, m.group(2))
        if idx is not None:
            out[m.group(2)] = idx
    return dict(sorted(out.items(), key=lambda kv: fiscal_key(kv[0])))


class LazyTickerIndexes(Mapping[str, dict]):
    """Mapping ticker -> indexes that loads on demand and keeps only the most recent tickers in
    memory (the full index set is ~200 MB of JSON)."""

    def __init__(self, tickers: Iterable[str], keep: int = 2) -> None:
        self._tickers = tuple(sorted({str(t).upper() for t in tickers if t} - GOLD_TICKERS))
        self._cache: "OrderedDict[str, dict[str, dict]]" = OrderedDict()
        self._keep = max(1, keep)

    def __getitem__(self, ticker: str) -> dict[str, dict]:
        t = str(ticker).upper()
        if t not in self._tickers:
            raise KeyError(ticker)
        if t in self._cache:
            self._cache.move_to_end(t)
            return self._cache[t]
        loaded = load_ticker_indexes(t)
        self._cache[t] = loaded
        while len(self._cache) > self._keep:
            self._cache.popitem(last=False)
        return loaded

    def __iter__(self):
        return iter(self._tickers)

    def __len__(self) -> int:
        return len(self._tickers)


# ── matching primitives ─────────────────────────────────────────────────────

def _term_re(term_norm: str) -> "re.Pattern[str]":
    return re.compile(r"(?<!\w)" + re.escape(term_norm) + r"(?!\w)")


def _norm_terms(terms: Iterable[str]) -> list[str]:
    out: list[str] = []
    for term in terms:
        n = normalize_text(str(term))
        if n and n not in out:
            out.append(n)
    return out


def _blank_excludes(norm: str, exclude_res: Sequence["re.Pattern[str]"]) -> str:
    for rx in exclude_res:
        norm = rx.sub(" ", norm)
    return norm


def _eligible_turns(index: Mapping) -> list[dict]:
    return [t for t in (index.get("turns") or []) if t.get("role") in ELIGIBLE_ROLES and t.get("sentences")]


@dataclass
class _Hit:
    fiscal_period: str
    turn: dict
    sid: int
    anchors: list[str]
    terms: list[str]
    tier: int


def _search(
    indexes: Mapping[str, dict],
    periods: Sequence[str],
    alias_map: Mapping[str, Sequence[str]],
    generic_map: Mapping[str, bool],
    cooccur_terms: Sequence[str],
    exclude_terms: Sequence[str],
    tier: int,
) -> list[_Hit]:
    """One pass of the ladder rule over ``periods``: an eligible-speaker sentence hits when any alias
    of any anchor matches its exclude-blanked norm; a generic anchor additionally needs one of
    ``cooccur_terms`` within +-COOCCUR_WINDOW sentences of the same turn."""
    alias_res = {a: [(al, _term_re(al)) for al in forms] for a, forms in alias_map.items()}
    cooccur_res = [(c, _term_re(c)) for c in cooccur_terms]
    exclude_res = [_term_re(e) for e in exclude_terms]
    # One combined "does ANY alias occur here?" regex per sentence; the per-anchor loop below only
    # runs on the (rare) sentences that pass it. Same result, ~N-aliases fewer regex calls per sentence.
    all_forms = sorted({al for forms in alias_map.values() for al in forms}, key=len, reverse=True)
    any_re = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(al) for al in all_forms) + r")(?!\w)") if all_forms else None
    hits: list[_Hit] = []
    for period in periods:
        idx = indexes.get(period)
        if not idx:
            continue
        for turn in _eligible_turns(idx):
            sentences = turn["sentences"]
            norms = [s.get("norm") or "" for s in sentences]
            for pos, sentence in enumerate(sentences):
                if any_re is None or not any_re.search(norms[pos]):
                    continue
                matched_anchors: list[str] = []
                matched_terms: list[str] = []
                cleaned_pos: str | None = None  # exclude-blanked norm, computed only once a raw alias matches
                for anchor, forms in alias_res.items():
                    hit_forms = [al for al, rx in forms if rx.search(norms[pos])]
                    if hit_forms and exclude_res:
                        if cleaned_pos is None:
                            cleaned_pos = _blank_excludes(norms[pos], exclude_res)
                        hit_forms = [al for al, rx in forms if rx.search(cleaned_pos)]
                    if not hit_forms:
                        continue
                    if generic_map.get(anchor, False):
                        lo, hi = max(0, pos - COOCCUR_WINDOW), min(len(norms), pos + COOCCUR_WINDOW + 1)
                        near = [c for c, rx in cooccur_res if any(rx.search(norms[j]) for j in range(lo, hi))]
                        if not near:
                            continue
                        matched_terms.extend(c for c in near if c not in matched_terms)
                    matched_anchors.append(anchor)
                    matched_terms.extend(al for al in hit_forms if al not in matched_terms)
                if matched_anchors:
                    hits.append(_Hit(period, turn, int(sentence.get("sid", pos)), matched_anchors, matched_terms, tier))
    return hits


def _count_hits(indexes: Mapping[str, dict], forms: Sequence[str], exclude_terms: Sequence[str] = ()) -> tuple[int, list[_Hit]]:
    alias_map = {"_": list(forms)}
    hits = _search(indexes, list(indexes.keys()), alias_map, {"_": False}, [], list(exclude_terms), tier=-1)
    return len(hits), hits


_GENERIC_CACHE: dict[tuple, dict] = {}


def _generic_cache_key(anchor: str, indexes: Mapping[str, dict], exclude: Sequence[str]) -> tuple | None:
    """Stable identity of an inference: ticker + a per-quarter content fingerprint (source mtime,
    turn and sentence counts) + anchor + excludes. The fingerprint keeps a rebuilt index — or a
    test fixture reusing the same ticker/quarters with different sentences — from hitting a stale
    entry. None when the indexes carry no single ticker, so those are never cached."""
    tickers = {str(idx.get("ticker") or "") for idx in indexes.values() if isinstance(idx, Mapping)}
    if len(tickers) != 1 or not next(iter(tickers)):
        return None
    fingerprint = tuple(
        (p, indexes[p].get("source_mtime"), len(indexes[p].get("turns") or []),
         sum(len(t.get("sentences") or []) for t in indexes[p].get("turns") or []))
        for p in sorted(indexes)
    )
    return (next(iter(tickers)), fingerprint, str(anchor), tuple(exclude))


def infer_generic(anchor: str, indexes: Mapping[str, dict], exclude: Sequence[str] = ()) -> dict:
    """Hit density of an anchor (all alias forms) over eligible speakers across every index of the
    ticker. generic = numeric anchor, or hits_per_quarter > GENERIC_THRESHOLD. Memoised per
    (ticker, quarter set, anchor, excludes): the same anchor across trees, or the alias audit's
    second look, costs nothing."""
    key = _generic_cache_key(anchor, indexes, exclude)
    if key is not None and key in _GENERIC_CACHE:
        return dict(_GENERIC_CACHE[key])
    out = _infer_generic_uncached(anchor, indexes, exclude)
    if key is not None:
        _GENERIC_CACHE[key] = dict(out)
    return out


def infer_generic_many(anchors: Sequence[str], indexes: Mapping[str, dict], exclude: Sequence[str] = ()) -> dict[str, dict]:
    """``infer_generic`` for several anchors in ONE pass over the ticker's sentences (the per-anchor
    scan was 84% of retrieval time). Cached anchors are served from the memo; the rest share a
    single ``_search`` whose per-hit ``anchors`` list is tallied per anchor."""
    out: dict[str, dict] = {}
    todo: list[str] = []
    for anchor in anchors:
        key = _generic_cache_key(anchor, indexes, exclude)
        if key is not None and key in _GENERIC_CACHE:
            out[anchor] = dict(_GENERIC_CACHE[key])
        else:
            todo.append(anchor)
    if not todo:
        return out
    quarters = len(indexes)
    alias_map = {a: derive_aliases(a) for a in todo}
    alias_map = {a: forms for a, forms in alias_map.items() if forms}
    counts: dict[str, int] = {a: 0 for a in todo}
    if alias_map and quarters:
        hits = _search(indexes, list(indexes.keys()), alias_map, {a: False for a in alias_map}, [], _norm_terms(exclude), tier=-1)
        for h in hits:
            for a in h.anchors:
                counts[a] = counts.get(a, 0) + 1
    for anchor in todo:
        hpq = counts[anchor] / quarters if quarters else 0.0
        res = {
            "hits": counts[anchor],
            "quarters": quarters,
            "hits_per_quarter": round(hpq, 3),
            "generic": bool(is_numeric_anchor(anchor) or hpq > GENERIC_THRESHOLD),
        }
        key = _generic_cache_key(anchor, indexes, exclude)
        if key is not None:
            _GENERIC_CACHE[key] = dict(res)
        out[anchor] = res
    return out


def _infer_generic_uncached(anchor: str, indexes: Mapping[str, dict], exclude: Sequence[str] = ()) -> dict:
    forms = derive_aliases(anchor)
    quarters = len(indexes)
    hits = _count_hits(indexes, forms, _norm_terms(exclude))[0] if forms and quarters else 0
    hpq = hits / quarters if quarters else 0.0
    return {
        "hits": hits,
        "quarters": quarters,
        "hits_per_quarter": round(hpq, 3),
        "generic": bool(is_numeric_anchor(anchor) or hpq > GENERIC_THRESHOLD),
    }


# ── retrieval ───────────────────────────────────────────────────────────────

@dataclass
class RetrievalResult:
    tier: int | None
    excerpts: list[dict] = field(default_factory=list)
    window: list[str] = field(default_factory=list)
    window_indexed: list[str] = field(default_factory=list)
    post_seed_quarters: list[str] = field(default_factory=list)
    quarters_searched: list[str] = field(default_factory=list)
    generic_map: dict[str, bool] = field(default_factory=dict)
    alias_snapshot: dict[str, list[str]] = field(default_factory=dict)
    n_hits_total: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "excerpts": self.excerpts,
            "window": self.window,
            "window_indexed": self.window_indexed,
            "post_seed_quarters": self.post_seed_quarters,
            "quarters_searched": self.quarters_searched,
            "generic_map": self.generic_map,
            "alias_snapshot": self.alias_snapshot,
            "n_hits_total": self.n_hits_total,
            "notes": self.notes,
        }


def _tree_kind(tree: Mapping) -> str:
    return str(tree.get("current_kind") or tree.get("kind") or "promise")


def _tree_clock(tree: Mapping) -> str | None:
    seed = tree.get("seed") or {}
    clock = str(tree.get("clock") or seed.get("clock") or "").strip()
    return clock if clock and fiscal_key(clock) >= (0, 0) else None


def _qidx(fiscal: str) -> int:
    y, q = fiscal_key(fiscal)
    return y * 4 + q if y >= 0 else -1


MAX_EXCERPT_SENTENCES = 6  # merged hit spans (hit sentences + one neighbour each side) never exceed this


def _excerpt_from_hits(hits: Sequence[_Hit], generic_map: Mapping[str, bool]) -> dict:
    """One excerpt for one or more hit sentences of the same turn: the hit sentence(s) plus one
    neighbouring sentence on each side within the turn, joined by a single space."""
    first = hits[0]
    sentences = first.turn["sentences"]
    sids = sorted({h.sid for h in hits})
    positions = [next((i for i, s in enumerate(sentences) if int(s.get("sid", i)) == sid), sid) for sid in sids]
    span = sentences[max(0, positions[0] - 1): positions[-1] + 2]
    anchors: list[str] = []
    terms: list[str] = []
    for h in hits:
        anchors.extend(a for a in h.anchors if a not in anchors)
        terms.extend(t for t in h.terms if t not in terms)
    return {
        "fiscal_period": first.fiscal_period,
        "speaker": first.turn.get("speaker") or UNLABELED_SPEAKER,
        "role": first.turn.get("role") or "unknown",
        "section": first.turn.get("section") or "prepared",
        "turn_idx": int(first.turn.get("idx", -1)),
        "sid": sids[0],
        "sids": sids,
        "anchors": anchors,
        "matched_terms": terms,
        "specific_anchor": any(not generic_map.get(a, False) for a in anchors),
        "tier": first.tier,
        "text": " ".join(str(s.get("text") or "").strip() for s in span).strip(),
        "norm": " ".join(str(s.get("norm") or "").strip() for s in span).strip(),
    }


def _group_hits(hits: list[_Hit]) -> list[list[_Hit]]:
    """Collapse duplicate (period, turn, sid) hits, then chain hit sentences of the same turn whose
    +-1 spans would overlap (sid gap <= 2) into one excerpt, capped at MAX_EXCERPT_SENTENCES."""
    merged: "OrderedDict[tuple, _Hit]" = OrderedDict()
    for h in hits:
        key = (h.fiscal_period, int(h.turn.get("idx", -1)), h.sid)
        if key in merged:
            m = merged[key]
            m.anchors.extend(a for a in h.anchors if a not in m.anchors)
            m.terms.extend(t for t in h.terms if t not in m.terms)
        else:
            merged[key] = h
    ordered = sorted(merged.values(), key=lambda h: (fiscal_key(h.fiscal_period), int(h.turn.get("idx", -1)), h.sid))
    groups: list[list[_Hit]] = []
    for h in ordered:
        if groups:
            g = groups[-1]
            same_turn = g[0].fiscal_period == h.fiscal_period and g[0].turn is h.turn
            if same_turn and h.sid - g[-1].sid <= 2 and (h.sid - g[0].sid + 3) <= MAX_EXCERPT_SENTENCES:
                g.append(h)
                continue
        groups.append([h])
    return groups


def rank_excerpts(excerpts: list[dict], *, kind: str, clock: str | None, seed_fiscal: str) -> list[dict]:
    """Deterministic ranking: (1) quarter distance from clock for promises / recency for goals,
    (2) prepared before qa, (3) more distinct matched terms, (4) specific anchor before generic,
    (5) management before unknown; tie-break (fiscal_period, turn_idx, sid). A promise without a
    clock ranks by distance from the seed quarter."""
    ref = _qidx(clock) if clock else _qidx(seed_fiscal)

    def key(e: dict):
        q = _qidx(e["fiscal_period"])
        if kind == "goal":
            primary = -q
        else:
            primary = abs(q - ref)
        return (
            primary,
            0 if e.get("section") == "prepared" else 1,
            -len(set(e.get("matched_terms") or [])),
            0 if e.get("specific_anchor") else 1,
            0 if e.get("role") == "management" else 1,
            fiscal_key(e["fiscal_period"]),
            e.get("turn_idx", 0),
            e.get("sid", 0),
        )

    ranked = sorted(excerpts, key=key)
    for n, e in enumerate(ranked, start=1):
        e["rank"] = n
    return ranked


def retrieve(tree: Mapping, indexes: Mapping[str, dict], *, now_fiscal: str | None = None) -> RetrievalResult:
    """Run the Tier 0-3 ladder for one tree over ``indexes`` ({fiscal_period: index} for the
    tree's ticker). Stops at the first tier with >=1 excerpt. ``now_fiscal`` caps the post-seed
    quarters (inclusive) when given."""
    block = match_block_for(tree)
    seed = tree.get("seed") or {}
    seed_fiscal = str(seed.get("fiscal_period") or "")
    clock = _tree_clock(tree)
    kind = _tree_kind(tree)
    result = RetrievalResult(tier=None)

    if not block.anchors:
        result.notes.append("no anchors (empty objects and match)")
        return result

    indexed = sorted((p for p in indexes if fiscal_key(p) >= (0, 0)), key=fiscal_key)
    post_seed = [p for p in indexed if fiscal_key(p) > fiscal_key(seed_fiscal)]
    if now_fiscal:
        post_seed = [p for p in post_seed if fiscal_key(p) <= fiscal_key(now_fiscal)]
    window = clock_window(seed_fiscal, clock) if clock else []
    window_indexed = [p for p in window if p in indexes]
    result.window, result.window_indexed, result.post_seed_quarters = window, window_indexed, post_seed

    exclude_norm = _norm_terms(block.exclude)
    context_norm = _norm_terms(block.context)
    alias_snapshot = {a: derive_aliases(a) for a in block.anchors}
    alias_snapshot = {a: forms for a, forms in alias_snapshot.items() if forms}
    result.alias_snapshot = alias_snapshot
    if not alias_snapshot:
        result.notes.append("anchors normalise to nothing")
        return result

    generic_map: dict[str, bool] = {}
    if block.generic is not None:
        generic_map = {anchor: bool(block.generic) for anchor in alias_snapshot}
    else:
        inferred = infer_generic_many(list(alias_snapshot), indexes, exclude_norm)
        generic_map = {anchor: bool(inferred[anchor]["generic"]) for anchor in alias_snapshot}
    result.generic_map = generic_map
    if block.generic is not None:
        result.notes.append(f"generic overridden by catalog: {block.generic}")

    anchor_tokens = {tok for forms in alias_snapshot.values() for f in forms for tok in f.split()}
    nouns = [n for n in seed_nouns(str(seed.get("excerpt") or "")) if n not in anchor_tokens and n not in context_norm]
    plain_map = {a: forms[:1] for a, forms in alias_snapshot.items()}
    full_map = alias_snapshot
    rules = (
        (plain_map, context_norm),  # tier 0
        (full_map, context_norm),  # tier 1
        (full_map, context_norm + nouns),  # tier 2
    )

    def run_tier3(periods: Sequence[str]) -> list[_Hit]:
        """Tier 0-2 rules in order over the widened window; reported as tier 3."""
        for sub, (amap, cooccur) in enumerate(rules):
            found = _search(indexes, periods, amap, generic_map, cooccur, exclude_norm, tier=3)
            if found:
                result.notes.append(f"tier 3 resolved with tier {sub} rule")
                return found
        return []

    hits: list[_Hit] = []
    if clock:
        if not window_indexed:
            result.notes.append("clock window has no indexed transcripts" if window else "clock window empty")
        else:
            for tier, (amap, cooccur) in enumerate(rules):
                hits = _search(indexes, window_indexed, amap, generic_map, cooccur, exclude_norm, tier=tier)
                if hits:
                    result.tier = tier
                    result.quarters_searched = list(window_indexed)
                    break
    else:
        result.notes.append("no clock: tiers 0-2 skipped")

    if not hits:
        if post_seed:
            hits = run_tier3(post_seed)
            result.quarters_searched = list(post_seed)
            if hits:
                result.tier = 3
        else:
            result.notes.append("no post-seed indexed quarters")
            result.quarters_searched = []

    if not hits:
        result.tier = None
        result.notes.append("no excerpt at any free tier")
        return result

    groups = _group_hits(hits)
    excerpts = [_excerpt_from_hits(g, generic_map) for g in groups]
    result.n_hits_total = len(excerpts)
    ranked = rank_excerpts(excerpts, kind=kind, clock=clock, seed_fiscal=seed_fiscal)
    kept = ranked[:MAX_EXCERPTS]
    if len(ranked) > MAX_EXCERPTS:
        result.notes.append(f"capped {len(ranked)} hits to {MAX_EXCERPTS}")
    result.excerpts = sorted(kept, key=lambda e: (fiscal_key(e["fiscal_period"]), e["turn_idx"], e["sid"]))
    return result


# ── alias audit ─────────────────────────────────────────────────────────────

def _fmt_sample(h: _Hit, width: int = 150) -> str:
    sent = next((s for s in h.turn["sentences"] if int(s.get("sid", -1)) == h.sid), None)
    text = re.sub(r"\s+", " ", str((sent or {}).get("text") or "")).strip()
    if len(text) > width:
        text = text[: width - 3] + "..."
    return f"[{h.fiscal_period} | {h.turn.get('speaker')} | {h.turn.get('role')} | {h.turn.get('section')}] {text}"


def audit_tree(tree: Mapping, indexes: Mapping[str, dict]) -> tuple[list[str], RetrievalResult]:
    block = match_block_for(tree)
    seed = tree.get("seed") or {}
    seed_fiscal = str(seed.get("fiscal_period") or "")
    clock = _tree_clock(tree)
    result = retrieve(tree, indexes)
    lines = [
        f"{tree.get('tree_id')}  ({tree.get('ticker')}, {_tree_kind(tree)}; seed {seed_fiscal}; clock {clock or '-'}; "
        f"indexed {len(indexes)} q, post-seed {len(result.post_seed_quarters)} q, "
        f"window {len(result.window_indexed)}/{len(result.window)} indexed)"
    ]
    if block.context or block.exclude or block.generic is not None:
        lines.append(f"  match: context={list(block.context)} exclude={list(block.exclude)} generic={block.generic}")
    exclude_norm = _norm_terms(block.exclude)
    window_set = set(result.window_indexed)
    for anchor in block.anchors:
        forms = derive_aliases(anchor)
        if not forms:
            lines.append(f"  {anchor!r:<34} normalises to nothing")
            continue
        n_hits, hits = _count_hits(indexes, forms, exclude_norm)  # one scan: density + samples
        hpq = n_hits / len(indexes) if indexes else 0.0
        stats = {"hits": n_hits, "hits_per_quarter": round(hpq, 3),
                 "generic": bool(is_numeric_anchor(anchor) or hpq > GENERIC_THRESHOLD)}
        label = "generic " if result.generic_map.get(anchor, stats["generic"]) else "specific"
        if is_numeric_anchor(anchor):
            label += " (numeric)"
        alias_note = "" if forms == [forms[0]] else f"  aliases={forms[1:]}"
        lines.append(
            f"  {anchor!r:<34} {stats['hits']:>5} hits  {stats['hits_per_quarter']:>5.1f}/q  {label}"
            f"  norm={forms[0]!r}{alias_note}"
        )
        samples = [h for h in hits if h.fiscal_period in window_set]
        samples += [h for h in hits if h.fiscal_period not in window_set and fiscal_key(h.fiscal_period) > fiscal_key(seed_fiscal)]
        samples += [h for h in hits if fiscal_key(h.fiscal_period) <= fiscal_key(seed_fiscal)]
        for h in samples[:AUDIT_SAMPLES]:
            lines.append("      " + _fmt_sample(h))
    if result.tier is None:
        lines.append(f"  ladder: none  (searched {len(result.quarters_searched)} q; {'; '.join(result.notes)})")
    else:
        lines.append(
            f"  ladder: tier {result.tier}  {len(result.excerpts)} excerpts ({result.n_hits_total} hits before cap; "
            f"searched {len(result.quarters_searched)} q"
            + (f"; {'; '.join(result.notes)}" if result.notes else "")
            + ")"
        )
        first = result.excerpts[0]
        lines.append(f"      first: [{first['fiscal_period']} | {first['speaker']} | {first['role']} | {first['section']}] "
                     f"matched={first['matched_terms']}  {first['text'][:160]}")
    return lines, result


def alias_audit(trees: Sequence[Mapping], indexes_by_ticker: Mapping[str, Mapping[str, dict]]) -> str:
    """Per tree, per anchor: hit counts, density, inferred generic flag and sample sentences; per
    tree the tier the ladder resolves at. Ends with a tier summary."""
    out: list[str] = []
    tier_counts: dict[str, int] = {"0": 0, "1": 0, "2": 0, "3": 0, "none": 0}
    unresolved: list[str] = []
    generic_anchors: list[str] = []
    by_ticker: dict[str, list[Mapping]] = {}
    for tree in trees:
        ticker = str(tree.get("ticker") or "").upper()
        if ticker in GOLD_TICKERS:
            continue
        by_ticker.setdefault(ticker, []).append(tree)
    for ticker in sorted(by_ticker):
        indexes = indexes_by_ticker.get(ticker) or {}
        for tree in by_ticker[ticker]:
            lines, result = audit_tree(tree, indexes)
            out.extend(lines)
            out.append("")
            key = "none" if result.tier is None else str(result.tier)
            tier_counts[key] += 1
            if result.tier is None:
                unresolved.append(str(tree.get("tree_id")))
            for anchor, generic in result.generic_map.items():
                if generic:
                    generic_anchors.append(f"{tree.get('tree_id')}:{anchor}")
    out.append("=" * 78)
    out.append(f"trees audited: {sum(tier_counts.values())}")
    out.append("resolved at  " + "  ".join(f"tier {k}: {v}" for k, v in tier_counts.items() if k != "none") + f"  none: {tier_counts['none']}")
    out.append("unresolved: " + (", ".join(unresolved) if unresolved else "-"))
    out.append("generic anchors: " + (", ".join(generic_anchors) if generic_anchors else "-"))
    return "\n".join(out)


# ── cli ─────────────────────────────────────────────────────────────────────

def catalog_trees() -> list[dict]:
    """The 44 hand-typed ops + HC trees, materialised as book-shaped dicts (clock / match / open)."""
    from scripts._desk_trees_v2 import build_tree
    from scripts._desk_trees_v2_catalogs import OPS_TREES
    from scripts._desk_trees_v2_hc_catalogs import HC_TREES

    return [build_tree(t) for t in (*OPS_TREES, *HC_TREES) if str(t.get("ticker") or "").upper() not in GOLD_TICKERS]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alias-audit", action="store_true", help="per-tree, per-anchor hit audit + ladder tier")
    ap.add_argument("--ticker", action="append", default=[], help="limit the audit to ticker(s)")
    ap.add_argument("--tree", action="append", default=[], help="limit the audit to tree id(s)")
    ap.add_argument("--out", metavar="PATH", help="also write the audit text to PATH")
    ap.add_argument("--show", metavar="TREE_ID", help="print the retrieved excerpts for one tree and exit")
    args = ap.parse_args()

    trees = catalog_trees()
    if args.show:
        tree = next((t for t in trees if t["tree_id"] == args.show), None)
        if tree is None:
            print(f"unknown tree {args.show}", file=sys.stderr)
            return 1
        indexes = load_ticker_indexes(tree["ticker"])
        result = retrieve(tree, indexes)
        header = {k: v for k, v in result.to_dict().items() if k != "excerpts"}
        print(json.dumps(header, indent=2))
        for e in result.excerpts:
            print(f"\n#{e['rank']} [{e['fiscal_period']} | {e['speaker']} | {e['role']} | {e['section']} | turn {e['turn_idx']} sid {e['sid']}]"
                  f" matched={e['matched_terms']}")
            print("   " + e["text"])
        return 0

    if not args.alias_audit:
        ap.print_help()
        return 1
    tickers = {t.upper() for t in args.ticker}
    ids = set(args.tree)
    selected = [t for t in trees if (not tickers or t["ticker"] in tickers) and (not ids or t["tree_id"] in ids)]
    if not selected:
        print("no trees selected", file=sys.stderr)
        return 1
    report = alias_audit(selected, LazyTickerIndexes(t["ticker"] for t in selected))
    print(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\nWrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
