#!/usr/bin/env python3
"""Sentence-level transcript index for retrieval-first terminal scoring (Step 1).

One JSON per transcript in ``Structured Narrative/transcripts_index/{TICKER}_{PERIOD}.json``,
rebuilt only when the raw ``.txt`` is newer than the index. No LLM, no NLP dependency.

    {
      "ticker": "MSFT", "fiscal_period": "FY2017-Q4",
      "participants": {"Amy Hood": "management", "Keith Weiss": "analyst", "Operator": "operator", "Chris Suh": "ir"},
      "turns": [
        {"idx": 12, "speaker": "Amy Hood", "role": "management", "section": "prepared|qa",
         "sentences": [{"sid": 0, "text": "...", "norm": "..."}]}
      ]
    }

Handles both raw layouts found in transcripts_raw/:
  * Quartr assembly  — ``Speaker:`` on its own line, then one or more paragraph lines
  * pipeline files   — ``Speaker: text`` single-line turns

Role classification is deterministic (see classify_roles). Boilerplate (safe harbor, operator
instructions, GAAP preamble, closing lines) is dropped at sentence level. ``norm`` is the shared
normalised form used by scripts/_desk_retrieval.py — keep normalize_text() the single source.

NVDA (gold book) is never indexed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "Structured Narrative" / "transcripts_raw"
INDEX_DIR = ROOT / "Structured Narrative" / "transcripts_index"
GOLD_TICKERS = frozenset({"NVDA"})
INDEX_VERSION = 4  # v4: normaliser fixes (percentage points, -sses plurals)
UNLABELED_SPEAKER = "Unknown Speaker"
IR_MAX_PREPARED_WORDS = 900  # intro speaker with more prepared words than this is an executive, not IR

_FILE_RE = re.compile(r"^([A-Z][A-Z0-9.\-]{0,9})_(FY\d{4}-Q[1-4])\.txt$")
_PERIOD_FILE_RE = re.compile(r"^(FY\d{4}-Q[1-4])\.txt$")

# ── speaker / turn parsing ──────────────────────────────────────────────────

_NAME_TOKEN = r"[A-Z][A-Za-z'’.\-]*"
_FIRM = r"(?:,\s+[A-Z][A-Za-z0-9&'’.\- ]{1,40})?"  # optional ", Morgan Stanley" after the name
_LABEL_LINE_RE = re.compile(rf"^\s*({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,5}}){_FIRM}\s*:\s*$")
_INLINE_TURN_RE = re.compile(rf"^\s*({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,5}}){_FIRM}\s*:\s+(\S.*)$")
# bare label: a short line of capitalised words with no punctuation ("Operator", "Tyler Scott"),
# optionally followed by an affiliation/title suffix ("Doug Anmuth -- JPMorgan -- Analyst")
_BARE_LABEL_RE = re.compile(rf"^\s*({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,4}})(\s+(?:--|[-–—])\s+[^\n]{{1,120}})?\s*$")
_LEADING_TAG_RE = re.compile(r"^\s*\[[^\]]{1,40}\]\s*")  # "[Operator instructions] "
_HEADER_LINE_RE = re.compile(r"^(?:[A-Z][A-Z0-9.\-]{0,9} Q[1-4] FY\d{4} .*Transcript|Date:\s.*|Source:\s.*|=+)$")
_JUNK_LINE_RE = re.compile(r"^(?:freestar|advertisement|\[?ad\]?|image source:.*|\d+\s*$)", re.I)
# participant roster blocks seen in roic.ai / Motley Fool style dumps
_ROSTER_HEADERS = {
    "executives": "management", "company participants": "management", "corporate participants": "management",
    "management": "management",
    "analysts": "analyst", "conference call participants": "analyst", "participants": "analyst",
}
_ROSTER_SEP_RE = re.compile(r"\s+(?:--|[-–—])\s+")
_CAP_NAME_TOKEN_RE = re.compile(r"^[A-Z][A-Za-z'’\-]*[a-z][A-Za-z'’\-]*\.?$")  # Pierre / McClure / Tien-Tsin
_INITIAL_RE_TOKEN = re.compile(r"^[A-Z]\.$")


def _parse_roster_line(line: str) -> list[tuple[str, str]]:
    """'KC McClure - Managing Director and Head, IR Pierre Nanterme - Chairman and CEO  David Rowland - CFO'
    → [(KC McClure, Managing Director and Head, IR), (Pierre Nanterme, Chairman and CEO), (David Rowland, CFO)].

    Several entries can share one line. The next entry's name is the trailing two capitalised tokens
    before each separator (three when the middle token is an initial); the title is what remains.
    """
    segments = _ROSTER_SEP_RE.split(line)
    if len(segments) < 2:
        return []
    out: list[tuple[str, str]] = []
    pending_name = segments[0].strip()
    for i, seg in enumerate(segments[1:], start=1):
        tokens = seg.split()
        name_tokens: list[str] = []
        if i < len(segments) - 1:
            want = 2
            while tokens and len(name_tokens) < want and (_CAP_NAME_TOKEN_RE.match(tokens[-1]) or _INITIAL_RE_TOKEN.match(tokens[-1])):
                tok = tokens.pop()
                name_tokens.insert(0, tok)
                if _INITIAL_RE_TOKEN.match(tok):
                    want = 3
        title = " ".join(tokens).strip(" ,;")
        if pending_name:
            out.append((pending_name, title))
        pending_name = " ".join(name_tokens)
    return [(n, t) for n, t in out if 1 <= len(n.split()) <= 5]
_SINGLE_WORD_SPEAKERS = frozenset({"operator", "moderator", "host", "unidentified"})
_INLINE_FALSE_POSITIVES = frozenset(
    {"note", "azure", "windows", "office", "linkedin", "dynamics", "revenue", "first", "second", "third",
     "finally", "next", "example", "question", "answer", "bottom", "top", "summary", "outlook", "guidance",
     "great", "okay", "ok", "thanks", "thank", "yes", "no", "sure", "right", "hi", "hello", "good", "well",
     "so", "and", "but", "now", "today", "slide", "page", "table", "figure", "source", "date"}
)
_SENTENCE_LIKE_RE = re.compile(r"[a-z]{2,}[.!?]\s")  # "Great. Okay." is a sentence, not a name
_IR_TITLE_RE = re.compile(r"investor relations|\bIR\b|\bVP,? IR\b", re.I)


def _clean_speaker(label: str) -> str:
    label = re.sub(r"\s+", " ", label.strip())
    label = re.split(r"\s+--\s+|\s+[-–—]\s+|,\s+", label)[0].strip()
    return label


def _plausible_speaker(label: str, known: set[str]) -> bool:
    if label in known:
        return True
    if _SENTENCE_LIKE_RE.search(label + " "):
        return False
    tokens = label.split()
    if not tokens or len(tokens) > 6:
        return False
    if len(tokens) == 1:
        return tokens[0].lower() in _SINGLE_WORD_SPEAKERS
    if tokens[0].lower().strip(".,") in _INLINE_FALSE_POSITIVES:
        return False
    return True


def _hint_from_suffix(suffix: str | None) -> str | None:
    """Role hint from a label suffix such as '-- JPMorgan -- Analyst' or '- Chief Financial Officer'."""
    if not suffix:
        return None
    low = suffix.lower()
    if "analyst" in low:
        return "analyst"
    if _IR_TITLE_RE.search(suffix):
        return "ir"
    if re.search(r"chief|officer|president|ceo|cfo|coo|cto|chairman|founder|executive|vice president|"
                 r"\bvp\b|\bevp\b|\bsvp\b|general manager|head of|director|treasurer|controller", low):
        return "management"
    return None


def parse_turns(raw: str) -> list[dict]:
    """Split a raw transcript into speaker turns: [{speaker, paragraphs: [str]}]."""
    return parse_transcript(raw)[0]


def parse_transcript(raw: str) -> tuple[list[dict], dict[str, str]]:
    """Split a raw transcript into speaker turns plus role hints harvested from label suffixes and
    participant roster blocks: ([{speaker, paragraphs: [str]}], {speaker: role})."""
    turns: list[dict] = []
    known: set[str] = set()
    hints: dict[str, str] = {}
    current: dict | None = None
    roster_role: str | None = None  # inside an "Executives" / "Analysts" block

    def start(speaker: str) -> dict:
        nonlocal current
        current = {"speaker": speaker, "paragraphs": []}
        turns.append(current)
        known.add(speaker)
        return current

    def hint(speaker: str, role: str | None) -> None:
        if role and speaker not in hints:
            hints[speaker] = role

    lines = raw.splitlines()
    for n, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if current is None and _HEADER_LINE_RE.match(stripped):
            continue  # file header block ("CTSH Q1 FY2026 Earnings Call Transcript", "Date:", "Source:", "====")
        if _JUNK_LINE_RE.match(stripped):
            continue
        # roster blocks ("Executives" / "Analysts" followed by "Name - Title" entries) → hints only
        if stripped.lower().rstrip(":") in _ROSTER_HEADERS and (current is None or roster_role is not None):
            roster_role = _ROSTER_HEADERS[stripped.lower().rstrip(":")]
            continue
        if roster_role is not None:
            entries = _parse_roster_line(stripped)
            if entries:
                for name, title in entries:
                    hint(name, "ir" if roster_role == "management" and _IR_TITLE_RE.search(title) else roster_role)
                    known.add(name)
                continue
            roster_role = None  # first non-roster line ends the block
        stripped = _LEADING_TAG_RE.sub("", stripped) or stripped
        m = _LABEL_LINE_RE.match(stripped)
        if m and _plausible_speaker(_clean_speaker(m.group(1)), known):
            start(_clean_speaker(m.group(1)))
            hint(current["speaker"], _hint_from_suffix(stripped[m.end(1):].rstrip(": ")))
            continue
        m = _INLINE_TURN_RE.match(stripped)
        if m and _plausible_speaker(_clean_speaker(m.group(1)), known):
            start(_clean_speaker(m.group(1)))
            rest = m.group(2).strip()
            # "Operator: [Operator instructions] Keith Weiss, Morgan Stanley: Excellent. ..." — a second
            # speaker embedded on the same line gets its own turn.
            for _ in range(3):
                rest_clean = _LEADING_TAG_RE.sub("", rest) or rest
                m2 = _INLINE_TURN_RE.match(rest_clean)
                if m2 and _plausible_speaker(_clean_speaker(m2.group(1)), known) and m2.group(1) != m.group(1):
                    if rest_clean != rest and rest[: len(rest) - len(rest_clean)].strip():
                        current["paragraphs"].append(rest[: len(rest) - len(rest_clean)].strip())
                    start(_clean_speaker(m2.group(1)))
                    rest = m2.group(2).strip()
                    continue
                break
            if rest:
                current["paragraphs"].append(rest)
            continue
        m = _BARE_LABEL_RE.match(stripped)
        if m and _plausible_speaker(m.group(1), known):
            prev_blank = n == 0 or not lines[n - 1].strip()
            next_blank = n + 1 >= len(lines) or not lines[n + 1].strip()
            # a suffixed label ("Doug Anmuth -- JPMorgan -- Analyst") is unambiguous even without blanks
            if (prev_blank and next_blank) or m.group(2):
                start(m.group(1))
                hint(current["speaker"], _hint_from_suffix(m.group(2)))
                continue
        if current is None:
            start(UNLABELED_SPEAKER)
        current["paragraphs"].append(stripped)
    turns = [t for t in turns if t["paragraphs"]]
    if is_unlabeled(turns):
        # No usable speaker attribution: one paragraph per turn so sentence windows and the
        # Q&A boundary still work; every turn is UNLABELED_SPEAKER / role "unknown".
        paras = [p for t in turns for p in t["paragraphs"]]
        return [{"speaker": UNLABELED_SPEAKER, "paragraphs": [p]} for p in paras], {}
    return turns, hints


def is_unlabeled(turns: list[dict]) -> bool:
    """True when speaker labels are absent or too sparse to trust (fewer than 3 labeled turns, or the
    unlabeled block holds most of the text)."""
    if not turns:
        return False
    labeled = [t for t in turns if t["speaker"] != UNLABELED_SPEAKER]
    if len(labeled) < 3:
        return True
    unl_chars = sum(len(p) for t in turns if t["speaker"] == UNLABELED_SPEAKER for p in t["paragraphs"])
    all_chars = sum(len(p) for t in turns for p in t["paragraphs"]) or 1
    return unl_chars / all_chars > 0.6


# ── role classification ─────────────────────────────────────────────────────

_INTRO_RE = re.compile(
    r"(?:on the call|on today'?s call|joining me|with me|joined by|here with me|along with me|"
    r"also on the call|on the line)[^.]{0,40}?\b(?:are|is|today|by)\b([^.]*)\.",
    re.I,
)
_HANDOFF_RE = re.compile(
    r"(?:from the line of|question (?:comes|is) from|next question(?: is| comes)? from|"
    r"first question(?: is| comes)? from|question from|we'?ll (?:take|go to|hear from|move (?:next )?to)|"
    r"line of)\s+(?:the line of\s+)?([A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+){0,3})",
)
# operator-only hand-off shapes (anchored to the start of the operator's turn so management prose
# such as "we have strong momentum" can never match):
#   "Next, we have Carter Gould from UBS."     "Vamil Divan, Guggenheim Securities."
_OPERATOR_HANDOFF_RE = re.compile(
    r"^\s*(?:(?:[Nn]ext,?\s+|[Aa]nd\s+)?[Ww]e(?:'ll)?\s+(?:have|go to|take)\s+(?:a question from\s+)?|"
    r"(?:[Oo]ur|[Tt]he)\s+(?:first|next|final|last)\s+question\s+(?:comes\s+|is\s+)?from\s+)?"
    r"([A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+){0,3})(?:,\s+|\s+(?:from|with|of|at)\s+)[A-Z][^.?!]{1,60}[.?!]?\s*$",
)
_QA_FLIP_RE = re.compile(
    r"(?:first|next) question|question (?:comes|is) from|from the line of|please go ahead with your question|"
    r"we will now begin the question|open (?:the|it) up for questions|begin the q\s*&\s*a|q\s*&\s*a session will now|"
    r"(?:if you (?:have|would like to ask) a question|to ask a question|would like to ask a question)[^.]{0,80}"
    r"(?:press|star|\*|pound|hash)|we'?ll (?:now )?(?:move|go) (?:over )?to q\s*&\s*a|ready (?:for|to take) (?:your )?questions|"
    r"one question and (?:a|one) follow-?up|limit (?:yourself|yourselves) to one question|"
    r"open (?:up )?the (?:call|line)s? (?:to|for) questions|(?:provide|give|repeat) (?:the |your )?instructions|"
    r"take (?:the )?first question|go to (?:the )?first question|\[operator instructions?\]|"
    r"before we (?:get|go|move|turn) to (?:the )?q\s*&\s*a|operator,? (?:let'?s|please|can you|could you|we'?re ready)",
    re.I,
)
_OPERATOR_NAMES = frozenset({"operator", "moderator", "host", "conference operator"})
_ANALYST_HINTS = ("analyst", "unidentified participant", "unknown analyst")
_MGMT_HINTS = ("company representative", "unidentified company", "executive")


def _name_tokens(name: str) -> list[str]:
    return [t.lower().strip(".,;") for t in re.split(r"\s+", name) if t.strip(".,;")]


def _name_in_text(name: str, text_lower: str) -> bool:
    toks = _name_tokens(name)
    if not toks:
        return False
    if " ".join(toks) in text_lower:
        return True
    # first + last token both present (handles middle initials / titles between)
    if len(toks) >= 2 and toks[0] in text_lower and toks[-1] in text_lower:
        return True
    return False


def classify_roles(turns: list[dict], hints: dict[str, str] | None = None) -> tuple[dict[str, str], int]:
    """Return ({speaker: role}, qa_start_turn_idx). Roles: operator | ir | management | analyst | unknown.

    `hints` are roles harvested by the parser from label suffixes ("-- Analyst") and roster blocks
    ("Executives" / "Analysts"); they seed the classification and are trusted over inference.
    """
    speakers = {t["speaker"] for t in turns}
    roles: dict[str, str] = {}
    for s in speakers:
        low = s.lower()
        if low in _OPERATOR_NAMES:
            roles[s] = "operator"
        elif any(h in low for h in _ANALYST_HINTS):
            roles[s] = "analyst"
        elif any(h in low for h in _MGMT_HINTS):
            roles[s] = "management"
        elif hints and hints.get(s) in ("management", "analyst", "ir"):
            roles[s] = hints[s]

    # Q&A flip: first operator turn that hands off a question (or is a bare "Name, Firm." hand-off);
    # fallback: the first turn by anyone that reads as a flip ("we'll now move over to Q&A").
    # A hinted analyst's first turn is always an upper bound.
    qa_start = len(turns)
    seen_non_operator = False  # the opening operator turn always previews the Q&A session — skip it
    for i, t in enumerate(turns):
        text = " ".join(t["paragraphs"])
        if roles.get(t["speaker"]) != "operator":
            seen_non_operator = True
            continue
        if seen_non_operator and (_QA_FLIP_RE.search(text) or _OPERATOR_HANDOFF_RE.match(text)):
            qa_start = i
            break
    if qa_start == len(turns):
        for i, t in enumerate(turns):
            if i == 0:
                continue
            text = " ".join(t["paragraphs"])
            if _QA_FLIP_RE.search(text) or _HANDOFF_RE.search(text):
                qa_start = i
                break
    for i, t in enumerate(turns):
        if roles.get(t["speaker"]) == "analyst" and i > 0:
            # the hand-off turn just before the first analyst, if the operator/IR spoke it
            flip = i - 1 if roles.get(turns[i - 1]["speaker"]) in ("operator", "ir") else i
            qa_start = min(qa_start, flip)
            break

    # IR = speaker of the intro turn (first non-operator turn that names the management team)
    intro_text = ""
    for t in turns[: max(qa_start, 1)]:
        if roles.get(t["speaker"]) == "operator":
            continue
        text = " ".join(t["paragraphs"])
        m = _INTRO_RE.search(text)
        if m:
            intro_text = m.group(1).lower()
            # The intro speaker is IR unless they also carry a real prepared-remarks segment
            # (an executive opening the call, or a mis-attributed opener): IR intros run a few
            # hundred words; a management segment runs well past that.
            prepared_words = sum(
                len(" ".join(u["paragraphs"]).split())
                for u in turns[: max(qa_start, 1)]
                if u["speaker"] == t["speaker"]
            )
            roles.setdefault(t["speaker"], "management" if prepared_words > IR_MAX_PREPARED_WORDS else "ir")
            break

    # management = named in the intro sentence
    if intro_text:
        for s in speakers:
            if s in roles:
                continue
            if _name_in_text(s, intro_text):
                roles[s] = "management"

    # analysts = named in operator hand-offs, or the speaker right after a hand-off
    for i, t in enumerate(turns):
        text = " ".join(t["paragraphs"])
        if roles.get(t["speaker"]) not in ("operator", "ir"):
            continue
        named_all = [m.group(1) for m in _HANDOFF_RE.finditer(text)]
        op_m = _OPERATOR_HANDOFF_RE.match(text) if roles.get(t["speaker"]) == "operator" and i >= qa_start else None
        if op_m:
            named_all.append(op_m.group(1))
        for named in named_all:
            for s in speakers:
                if s in roles and roles[s] != "unknown":
                    continue
                if _name_in_text(s, named.lower()) or _name_in_text(named, s.lower()):
                    roles[s] = "analyst"
        if _QA_FLIP_RE.search(text) or _HANDOFF_RE.search(text) or op_m:
            nxt = turns[i + 1]["speaker"] if i + 1 < len(turns) else None
            if nxt and nxt not in roles:
                roles[nxt] = "analyst"

    # remaining: speaks in prepared remarks → management. Q&A-only speakers are classified by who
    # handed them the floor: after an operator turn → analyst (the operator queues questions);
    # after a colleague/analyst turn → management (a manager passing the answer: "Roopal?").
    # Question ratio is only the tiebreak when there is no predecessor signal.
    first_seen: dict[str, int] = {}
    q_ratio: dict[str, list[int]] = {}
    for i, t in enumerate(turns):
        s = t["speaker"]
        first_seen.setdefault(s, i)
        text = " ".join(t["paragraphs"]).strip()
        bucket = q_ratio.setdefault(s, [0, 0])
        bucket[1] += 1
        if text.endswith("?") or text.count("?") >= 2:
            bucket[0] += 1
    if qa_start == len(turns):
        # No hand-off text survived (roic.ai dumps drop the operator entirely): the Q&A starts at the
        # first new speaker, past the opening, whose turns mostly read as questions.
        for i, t in enumerate(turns):
            s = t["speaker"]
            if i < 2 or first_seen[s] != i or s in roles or s == UNLABELED_SPEAKER:
                continue
            q, n = q_ratio[s]
            if n and q / n >= 0.5:
                qa_start = i
                break
    for s in sorted(speakers, key=lambda x: first_seen[x]):
        if s in roles or s == UNLABELED_SPEAKER:
            continue
        if first_seen[s] < qa_start:
            roles[s] = "management"
            continue
        i = first_seen[s]
        prev_role = roles.get(turns[i - 1]["speaker"]) if i > 0 else None
        if prev_role == "operator":
            roles[s] = "analyst"
        elif prev_role in ("management", "analyst", "ir"):
            roles[s] = "management"
        else:
            q, n = q_ratio[s]
            roles[s] = "analyst" if n and q / n >= 0.6 else "unknown"
    return roles, qa_start


def unlabeled_qa_start(turns: list[dict]) -> int:
    """Q&A boundary for a transcript without speaker labels: the first paragraph (after the opening
    two) that reads like an operator hand-off. Falls back to len(turns) (all prepared)."""
    for i, t in enumerate(turns):
        if i < 2:
            continue
        text = " ".join(t["paragraphs"])
        if _QA_FLIP_RE.search(text) or _HANDOFF_RE.search(text):
            return i
    return len(turns)


# ── boilerplate ─────────────────────────────────────────────────────────────

_BOILERPLATE_RE = re.compile(
    r"forward-?looking statement|safe harbor|risk factors|form 10-?k|form 10-?q|securities and exchange commission|"
    r"actual results (?:could|may|might) differ|undertake (?:no|any) (?:duty|obligation) to update|"
    r"non-?gaap (?:financial )?measures?|reconciliation of (?:the )?(?:differences|gaap|non-?gaap)|"
    r"should not be considered (?:as )?a substitute|substitute for,? or superior to|"
    r"webcast|replay of (?:this|the|today'?s) call|being recorded|listen-?only mode|press (?:the )?star|"
    r"press \*|\[operator instructions\]|operator instructions|you may (?:now )?disconnect|"
    r"this concludes today'?s|that concludes (?:our|today'?s|the)|thank you for (?:joining|participating|your participation)|"
    r"turn the (?:call|conference) (?:back )?over to|i(?:'d| would) (?:now )?like to (?:turn|hand) the (?:call|conference)|"
    r"please proceed|please go ahead|one moment (?:please )?for (?:our|the) (?:first|next) question|"
    r"unless otherwise (?:noted|specified|stated)|growth (?:rates|comparisons) .{0,40}constant currency|"
    r"posted? (?:our )?prepared remarks to (?:our|the) website|investor relations website|"
    r"earnings press release|financial summary slide deck",
    re.I,
)


def is_boilerplate(sentence: str) -> bool:
    return bool(_BOILERPLATE_RE.search(sentence))


# ── sentence split ──────────────────────────────────────────────────────────

_ABBREVIATIONS = (
    "Inc", "Corp", "Co", "Ltd", "LLC", "Mr", "Mrs", "Ms", "Dr", "Jr", "Sr", "St", "vs", "No", "Nos",
    "approx", "est", "etc", "e.g", "i.e", "U.S", "U.K", "E.U", "a.m", "p.m", "Jan", "Feb", "Mar", "Apr",
    "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec", "Fig", "Ph.D",
)
_DOT = "\u2024"  # one-dot leader stands in for protected periods
_ABBR_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")\.", re.I)
_INITIAL_RE = re.compile(r"\b([A-Z])\.(?=\s?[A-Z])")
_DECIMAL_RE = re.compile(r"(\d)\.(\d)")
_SPLIT_RE = re.compile(r"(?<=[.!?])[\"'”’)]?\s+(?=[\"'“‘(\[$]?[A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    protected = _ABBR_RE.sub(lambda m: m.group(1) + _DOT, text)
    protected = _INITIAL_RE.sub(lambda m: m.group(1) + _DOT, protected)
    protected = _DECIMAL_RE.sub(lambda m: m.group(1) + _DOT + m.group(2), protected)
    parts = _SPLIT_RE.split(protected)
    out: list[str] = []
    for part in parts:
        s = part.replace(_DOT, ".").strip()
        if len(s) >= 2:
            out.append(s)
    return out


# ── normalisation (single source for index + retrieval) ─────────────────────

_SCALE_CANON = {
    "billion": "billion", "billions": "billion", "bn": "billion", "b": "billion",
    "million": "million", "millions": "million", "mn": "million", "mm": "million", "m": "million",
    "trillion": "trillion", "trillions": "trillion", "tn": "trillion", "t": "trillion",
    "thousand": "thousand", "k": "thousand",
}
_NUM = r"\d[\d,]*(?:\.\d+)?"
_CURRENCY_SCALE_RE = re.compile(rf"\$\s*({_NUM})\s*(billion|billions|bn|b|million|millions|mn|mm|m|trillion|trillions|tn|t|thousand|k)\b")
_BARE_SCALE_RE = re.compile(rf"(?<![\w$])({_NUM})\s*(billion|billions|million|millions|trillion|trillions)\b(?:\s+(?:us\s+)?dollars?)?")
# "percentage points" / "percent points" are NOT percentages; the alternation is ordered so the
# engine cannot backtrack from `percentage` into `percent` + `age`.
_PERCENT_RE = re.compile(rf"({_NUM})\s*(?:%|percentage(?!\s+point)\b|percent(?!age)(?!\s+point)\b)")
_HYPHEN_RE = re.compile(r"(?<=\w)-(?=\w)")
_PUNCT_RE = re.compile(r"[^\w\s$%.]")
_DOT_NOT_DECIMAL_RE = re.compile(r"(?<!\d)\.|\.(?!\d)")
# `businesses`/`processes`/`losses` → `business`/`process`/`loss` (strip -es after a double-s
# stem) before the generic single-s strip, so singular and plural converge.
_PLURAL_SSES_RE = re.compile(r"\b([a-z]{2,}ss)es\b")
_PLURAL_RE = re.compile(r"\b([a-z]{3,}[^s\s])s\b")
_UNICODE_MAP = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u00a0": " ",
})


def _canon_number(num: str) -> str:
    return num.replace(",", "")


def normalize_text(text: str) -> str:
    """Deterministic normalisation shared by the index and retrieval (see plan Step 2).

    lowercase → unicode dashes/quotes → ASCII → percentages → currency/scale → strip intra-token
    hyphens → drop punctuation (keep $ % and decimal points) → plural-s strip → collapse whitespace.
    Numbers stay strict: no range or approximation folding.
    """
    s = text.translate(_UNICODE_MAP).lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.encode("ascii", "ignore").decode("ascii")
    s = _PERCENT_RE.sub(lambda m: f"{_canon_number(m.group(1))}%", s)
    s = _CURRENCY_SCALE_RE.sub(lambda m: f"${_canon_number(m.group(1))} {_SCALE_CANON[m.group(2)]}", s)
    s = _BARE_SCALE_RE.sub(lambda m: f"${_canon_number(m.group(1))} {_SCALE_CANON[m.group(2)]}", s)
    s = _HYPHEN_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _DOT_NOT_DECIMAL_RE.sub(" ", s)
    s = _PLURAL_SSES_RE.sub(r"\1", s)
    s = _PLURAL_RE.sub(r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── index build ─────────────────────────────────────────────────────────────

def index_path(ticker: str, period: str) -> Path:
    return INDEX_DIR / f"{ticker.upper()}_{period.upper()}.json"


def raw_candidates(ticker: str, period: str) -> list[Path]:
    """Both raw layouts, preferred first: flat `{TICKER}_{PERIOD}.txt` (Quartr assembly) then the
    per-ticker `{TICKER}/{PERIOD}.txt` layout (older pipeline pulls)."""
    t, p = ticker.upper(), period.upper()
    return [RAW_DIR / f"{t}_{p}.txt", RAW_DIR / t / f"{p}.txt"]


def raw_path(ticker: str, period: str, min_bytes: int = 0) -> Path | None:
    for cand in raw_candidates(ticker, period):
        if cand.is_file() and cand.stat().st_size > min_bytes:
            return cand
    return None


def build_index(ticker: str, period: str, raw: str, source_mtime: float | None = None) -> dict:
    turns_raw, hints = parse_transcript(raw)
    unlabeled = bool(turns_raw) and all(t["speaker"] == UNLABELED_SPEAKER for t in turns_raw)
    if unlabeled:
        roles, qa_start = {UNLABELED_SPEAKER: "unknown"}, unlabeled_qa_start(turns_raw)
    else:
        roles, qa_start = classify_roles(turns_raw, hints)
    turns_out: list[dict] = []
    n_sentences = 0
    n_dropped = 0
    for i, t in enumerate(turns_raw):
        role = roles.get(t["speaker"], "unknown")
        section = "prepared" if i < qa_start else "qa"
        sentences: list[dict] = []
        if role != "operator":
            sid = 0
            for para in t["paragraphs"]:
                for sent in split_sentences(para):
                    if is_boilerplate(sent):
                        n_dropped += 1
                        continue
                    sentences.append({"sid": sid, "text": sent, "norm": normalize_text(sent)})
                    sid += 1
        else:
            n_dropped += sum(len(split_sentences(p)) for p in t["paragraphs"])
        n_sentences += len(sentences)
        turns_out.append({"idx": i, "speaker": t["speaker"], "role": role, "section": section, "sentences": sentences})
    return {
        "index_version": INDEX_VERSION,
        "ticker": ticker.upper(),
        "fiscal_period": period.upper(),
        "source_mtime": source_mtime,
        "participants": dict(sorted(roles.items())),
        "unlabeled": unlabeled,
        "qa_start_turn": qa_start,
        "n_turns": len(turns_out),
        "n_sentences": n_sentences,
        "n_boilerplate_dropped": n_dropped,
        "turns": turns_out,
    }


def load_index(ticker: str, period: str) -> dict | None:
    path = index_path(ticker, period)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def iter_raw_files(tickers: Iterable[str] | None = None) -> list[tuple[str, str, Path]]:
    wanted = {t.upper() for t in tickers} if tickers else None
    found: dict[tuple[str, str], Path] = {}
    if not RAW_DIR.is_dir():
        return []
    # per-ticker layout first so the flat layout overrides it when both exist
    for sub in sorted(p for p in RAW_DIR.iterdir() if p.is_dir()):
        ticker = sub.name.upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", ticker):
            continue
        for path in sorted(sub.glob("*.txt")):
            m = _PERIOD_FILE_RE.match(path.name)
            if m:
                found[(ticker, m.group(1))] = path
    for path in sorted(RAW_DIR.glob("*.txt")):
        m = _FILE_RE.match(path.name)
        if m:
            found[(m.group(1), m.group(2))] = path
    out: list[tuple[str, str, Path]] = []
    for (ticker, period), path in sorted(found.items()):
        if ticker in GOLD_TICKERS:
            continue
        if wanted and ticker not in wanted:
            continue
        out.append((ticker, period, path))
    return out


def needs_rebuild(ticker: str, period: str, src: Path, force: bool = False) -> bool:
    if force:
        return True
    dest = index_path(ticker, period)
    if not dest.is_file():
        return True
    try:
        existing = json.loads(dest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True
    if existing.get("index_version") != INDEX_VERSION:
        return True
    return (existing.get("source_mtime") or 0) < src.stat().st_mtime - 1e-6


def build_all(tickers: Iterable[str] | None = None, force: bool = False, verbose: bool = True) -> dict:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    built = skipped = 0
    role_counts: dict[str, int] = {}
    for ticker, period, src in iter_raw_files(tickers):
        if not needs_rebuild(ticker, period, src, force):
            skipped += 1
            continue
        raw = src.read_text(encoding="utf-8", errors="replace")
        idx = build_index(ticker, period, raw, source_mtime=src.stat().st_mtime)
        index_path(ticker, period).write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
        built += 1
        for role in idx["participants"].values():
            role_counts[role] = role_counts.get(role, 0) + 1
        if verbose and built % 100 == 0:
            print(f"  built {built} ...", flush=True)
    return {"built": built, "skipped": skipped, "participant_roles": role_counts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticker", action="append", default=[], help="limit to ticker(s)")
    ap.add_argument("--force", action="store_true", help="rebuild even if index is newer than the raw file")
    ap.add_argument("--show", metavar="TICKER_PERIOD", help="print participants + a sample of one index and exit")
    args = ap.parse_args()

    if args.show:
        ticker, period = args.show.upper().split("_", 1)
        idx = load_index(ticker, period)
        if idx is None:
            print("no index", file=sys.stderr)
            return 1
        print(json.dumps({k: v for k, v in idx.items() if k != "turns"}, indent=2))
        for t in idx["turns"][:60]:
            if not t["sentences"]:
                continue
            print(f"[{t['idx']:>3}] {t['speaker']} ({t['role']}, {t['section']}) n={len(t['sentences'])}")
            print("      ", t["sentences"][0]["text"][:140])
        return 0

    result = build_all(args.ticker or None, force=args.force)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
