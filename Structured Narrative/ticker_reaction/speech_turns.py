"""Group consecutive same-speaker paragraphs into speech turns (monologues)."""

from __future__ import annotations

import html
from dataclasses import dataclass

from ticker_reaction.load_transcript import Paragraph, TimedTranscript


@dataclass(frozen=True)
class SpeechTurn:
    turn_id: int
    speaker: str
    paragraph_indices: tuple[int, ...]
    paragraph_texts: tuple[str, ...]

    @property
    def full_text(self) -> str:
        return " ".join(t for t in self.paragraph_texts if t).strip()


def _norm_speaker(speaker: str | None) -> str:
    return (speaker or "").strip()


def build_speech_turns(
    transcript: TimedTranscript,
) -> tuple[list[SpeechTurn], dict[int, int]]:
    """
    Consecutive paragraphs with the same speaker form one turn.
    Returns turns in order and paragraph_index -> turn_id.
    """
    paras = sorted(transcript.paragraphs, key=lambda p: (p.start_sec, p.index))
    turns: list[SpeechTurn] = []
    index_to_turn: dict[int, int] = {}
    if not paras:
        return turns, index_to_turn

    cur_speaker = _norm_speaker(paras[0].speaker)
    cur_indices: list[int] = []
    cur_texts: list[str] = []

    def flush() -> None:
        nonlocal cur_indices, cur_texts
        if not cur_indices:
            return
        tid = len(turns)
        turn = SpeechTurn(
            turn_id=tid,
            speaker=cur_speaker,
            paragraph_indices=tuple(cur_indices),
            paragraph_texts=tuple(cur_texts),
        )
        turns.append(turn)
        for idx in cur_indices:
            index_to_turn[idx] = tid
        cur_indices = []
        cur_texts = []

    for p in paras:
        sp = _norm_speaker(p.speaker)
        text = " ".join((p.text or "").split())
        if cur_indices and sp != cur_speaker:
            flush()
            cur_speaker = sp
        elif not cur_indices:
            cur_speaker = sp
        cur_indices.append(p.index)
        cur_texts.append(text)
    flush()
    return turns, index_to_turn


def trigger_preview(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def monologue_html(turn: SpeechTurn, trigger_index: int) -> str:
    """Full monologue HTML with the triggering paragraph emphasized."""
    parts: list[str] = []
    for idx, text in zip(turn.paragraph_indices, turn.paragraph_texts):
        esc = html.escape(text)
        if idx == trigger_index:
            parts.append(f'<p class="mono-para trigger"><mark>{esc}</mark></p>')
        else:
            parts.append(f'<p class="mono-para">{esc}</p>')
    return "".join(parts)


def attach_turn_context(
    *,
    paragraph_index: int,
    paragraph_text: str,
    turns: list[SpeechTurn],
    index_to_turn: dict[int, int],
) -> tuple[int | None, str, str]:
    """
    Returns (speech_turn_id, monologue_plain_text, monologue_html_with_mark).
    Falls back to the paragraph alone if no turn mapping.
    """
    tid = index_to_turn.get(paragraph_index)
    if tid is None or tid < 0 or tid >= len(turns):
        plain = " ".join((paragraph_text or "").split())
        marked = f'<p class="mono-para trigger"><mark>{html.escape(plain)}</mark></p>'
        return None, plain, marked
    turn = turns[tid]
    return turn.turn_id, turn.full_text, monologue_html(turn, paragraph_index)
