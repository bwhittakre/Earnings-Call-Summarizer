#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared claim + footnote quote rendering for HTML reports."""
from __future__ import annotations

import html

STATUS_CHIPS = {
    "composite": ("composite", "Ellipsis-stitched quote — every fragment is verbatim."),
    "anchored": ("anchored", "Verbatim span located for the claim."),
    "paraphrased": ("paraphrased", "Faithful paraphrase confirmed by rescue judge."),
    "unverified": ("unverified", "No supporting span found."),
}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def status_of(ev: dict) -> str:
    status = ev.get("status")
    if status:
        return status
    return "verbatim" if ev.get("verified") else "unverified"


def status_chip(status: str) -> str:
    if status not in STATUS_CHIPS:
        return ""
    label, title = STATUS_CHIPS[status]
    return f' <span class="chip {esc(status)}" title="{esc(title)}">{esc(label)}</span>'


def render_evidence_block(
    evidence: list[dict],
    id_prefix: str,
    notes_heading: str,
) -> str:
    """Render claim bullets with superscript refs and a footnote quote block."""
    if not evidence:
        return ""

    bullets: list[str] = []
    footnotes: list[str] = []
    for i, ev in enumerate(evidence, start=1):
        src_id = f"{id_prefix}-src-{i}"
        fn_id = f"{id_prefix}-fn-{i}"
        sup = f'<sup class="ref" id="{src_id}"><a href="#{fn_id}">{i}</a></sup>'
        bullets.append(f"<li>{esc(ev.get('claim'))}{sup}</li>")

        status = status_of(ev)
        chip = status_chip(status)
        canon = ev.get("canonical")
        canon_html = ""
        if (
            status in ("anchored", "paraphrased")
            and canon
            and canon.strip() != (ev.get("excerpt") or "").strip()
        ):
            canon_html = f'<div class="canon">verbatim: &ldquo;{esc(canon)}&rdquo;</div>'
        footnotes.append(
            f'<li id="{fn_id}"><a class="back" href="#{src_id}">[{i}]</a> '
            f'&ldquo;{esc(ev.get("excerpt"))}&rdquo;{chip}{canon_html}</li>'
        )

    bullets_html = f'<ul class="bul">{"".join(bullets)}</ul>'
    notes_html = (
        f'<div class="notes"><h4>{esc(notes_heading)}</h4>'
        f'<ol>{"".join(footnotes)}</ol></div>'
    )
    return bullets_html + notes_html


EVIDENCE_CSS = """
  .bul { margin: 6px 0 0; padding-left: 1.2em; font-size: 13px; }
  .bul li { margin-bottom: 4px; }
  .ref a { color: #2563eb; text-decoration: none; font-weight: 600; }
  .notes { margin-top: 8px; font-size: 12px; color: #444; }
  .notes h4 { margin: 0 0 6px; font-size: 11px; text-transform: uppercase;
              letter-spacing: .04em; color: #666; font-weight: 600; }
  .notes ol { margin: 0; padding-left: 1.4em; }
  .notes li { margin-bottom: 8px; }
  .back { color: #2563eb; text-decoration: none; font-weight: 600; margin-right: 4px; }
  .chip { display: inline-block; font-size: 10px; padding: 1px 5px; border-radius: 3px;
          text-transform: uppercase; letter-spacing: .03em; margin-left: 4px; }
  .chip.composite { background: #e8f0fe; color: #1a4a8a; }
  .chip.anchored { background: #e6f4ea; color: #1a5c2e; }
  .chip.paraphrased { background: #fef7e0; color: #7a5c00; }
  .chip.unverified { background: #fce8e6; color: #8a1a1a; }
  .canon { margin-top: 4px; font-size: 11px; color: #555; font-style: italic; }
  .quarter-evidence { margin-top: 6px; padding-top: 4px; border-top: 1px dashed #ddd; }
"""
