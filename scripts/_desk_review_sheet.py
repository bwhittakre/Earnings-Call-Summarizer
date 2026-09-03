"""Claims Desk review workbook: one Excel tab per ticker, Accept / Reject dropdowns.

Turns the two LLM proposal files into a single human-review artifact:

* ``data/terminal_score_candidates.json`` — proposed terminal verdicts on the
  existing open ops/HC trees (delivered / hit / missed / none) plus the
  ``needs_review`` queue.
* ``data/seed_batch_candidates.json`` — proposed new seed trees (promises and
  goals) mined from uncovered cue rows.

Nothing here writes to the catalogs. The convention stays "propose, never
auto-insert": the analyst marks a DECISION per row in Excel, then ``read`` pulls
those decisions back into ``data/desk_review_decisions.json`` for the apply step.

Usage
-----
    python scripts/_desk_review_sheet.py build          # -> data/desk_review_sheet.xlsx
    python scripts/_desk_review_sheet.py read           # -> data/desk_review_decisions.json
    python scripts/_desk_review_sheet.py read --strict  # fail if any row is undecided

Decision vocabulary (column DECISION)
-------------------------------------
    Accept   verdict: type the terminal node as proposed
             seed:    add the tree to the catalog as proposed
    Reject   verdict: leave the tree open (the proposal is wrong)
             seed:    do not add (not a desk object / duplicate / rhetoric)
    Re-cite  the object is right but the quote is not verbatim or not the best
             sentence — find the exact sentence before typing
    Defer    park it; revisit after the first apply pass

Rows whose proposal is ``none`` (no outcome found) are included so the reviewer
can confirm the tree should stay open; Accept there means "agree, keep open".
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_regimes import load_management_regimes, regime_for_fiscal, regimes_for_ticker  # noqa: E402
from scripts._desk_regimes_builder import load_desk_trees_hc_v2, load_desk_trees_ops_v2  # noqa: E402
from scripts._desk_trees_v2 import fiscal_key, infer_materiality  # noqa: E402
from scripts._desk_catalog_overlay import load_overlay, get_overlay_trees  # noqa: E402

DATA = ROOT / "data"
TERMINAL_IN = DATA / "terminal_score_candidates.json"
SEEDS_IN = DATA / "seed_batch_candidates.json"
XLSX_OUT = DATA / "desk_review_sheet.xlsx"
DECISIONS_OUT = DATA / "desk_review_decisions.json"

DECISIONS = ("Accept", "Reject", "Re-cite", "Defer")
MAX_EXTRA_EVIDENCE = 3

# Column order is the contract between ``build`` and ``read``: ``read`` locates
# columns by header text, so renaming a header here is safe only if both agree.
COLUMNS: list[tuple[str, int]] = [
    ("Row ID", 30),
    ("Type", 10),
    ("Kind", 9),
    ("Title", 42),
    ("Seed qtr", 10),
    ("Clock", 10),
    ("CEO at seed", 18),
    ("Promise / goal as stated (seed quote)", 60),
    ("Proposal", 26),
    ("Outcome quote (verdict evidence)", 60),
    ("Conf.", 8),
    ("Quote verbatim?", 9),
    ("Model reasoning", 55),
    ("Other evidence", 55),
    ("DECISION", 12),
    ("Status", 16),        # pre-populated from overlay; informational only
    ("Materiality", 12),   # editable dropdown: high / medium / low
    ("Notes", 40),
]
HEADERS = [c[0] for c in COLUMNS]
COL = {name: idx + 1 for idx, (name, _) in enumerate(COLUMNS)}  # 1-based


# ── loading ──────────────────────────────────────────────────────────────────

def _build_overlay_status() -> dict[str, str]:
    """Load both overlays and return {tree_id → provenance status string}."""
    ops_overlay = load_overlay("ops")
    hc_overlay = load_overlay("hc")
    status: dict[str, str] = {}
    for ot in get_overlay_trees(ops_overlay) + get_overlay_trees(hc_overlay):
        tid = str(ot.get("tree_id") or "")
        prov = ot.get("provenance") or {}
        if tid:
            status[tid] = str(prov.get("status") or "queued")
    return status


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"missing input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _tree_index() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for book in (load_desk_trees_ops_v2(), load_desk_trees_hc_v2()):
        for tree in book.get("trees") or []:
            out[str(tree.get("tree_id"))] = tree
    return out


def _ceo_at(ticker: str, fiscal: str | None, regimes: list[dict]) -> str:
    if not fiscal:
        return ""
    reg = regime_for_fiscal(ticker, fiscal, regimes)
    return str(reg.get("named_person") or "") if reg else ""


def _regime_caption(ticker: str, regimes: list[dict]) -> str:
    parts = []
    for r in regimes_for_ticker(ticker, regimes):
        end = r.get("end_fiscal") or "present"
        parts.append(f"{r.get('named_person')} ({r.get('start_fiscal')} → {end})")
    return "CEO regimes: " + "; ".join(parts) if parts else "CEO regimes: none catalogued"


def _fmt_evidence(ev: Sequence[Mapping], skip_text: str | None) -> str:
    lines = []
    for e in ev:
        text = str(e.get("text") or "").strip()
        if not text or (skip_text and text == skip_text.strip()):
            continue
        who = str(e.get("speaker") or "").strip()
        lines.append(f"[{e.get('fiscal_period')}] {who}: {text}")
        if len(lines) >= MAX_EXTRA_EVIDENCE:
            break
    return "\n".join(lines)


# ── row assembly ─────────────────────────────────────────────────────────────

def verdict_rows(
    terminal: Mapping,
    trees: Mapping[str, dict],
    regimes: list[dict],
    overlay_status: dict[str, str] | None = None,
) -> dict[str, list[dict]]:
    """One row per open tree that was scored or flagged; keyed by ticker."""
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    ov_status = overlay_status or {}
    review_by_tree = {str(r.get("tree_id")): r for r in terminal.get("needs_review") or []}

    for c in terminal.get("candidates") or []:
        tid = str(c.get("tree_id"))
        ticker = str(c.get("ticker") or "").upper()
        tree = trees.get(tid) or {}
        seed = tree.get("seed") or {}
        edge = str(c.get("proposed_edge") or "none")
        proposal = edge if edge == "none" else f"{edge} @ {c.get('proposed_fiscal') or '?'}"
        if edge == "none":
            proposal = "none — no outcome found, tree stays open"
        flag = review_by_tree.get(tid)
        if flag:
            proposal += f"\nNEEDS REVIEW: {flag.get('reason')} — {flag.get('detail')}"
        verified = c.get("excerpt_verified")
        # Materiality: prefer the tree's seed.materiality (set by build_tree), fall back to infer
        mat_val = str(seed.get("materiality") or tree.get("materiality") or "").strip()
        if not mat_val:
            mat_val = infer_materiality(tree or c)
        by_ticker[ticker].append({
            "Row ID": f"V:{tid}",
            "Type": "Verdict",
            "Kind": str(c.get("kind") or tree.get("kind") or ""),
            "Title": str(c.get("title") or tree.get("title") or ""),
            "Seed qtr": str(c.get("seed_fiscal") or seed.get("fiscal_period") or ""),
            "Clock": str(c.get("clock") or tree.get("clock") or "") or "—",
            "CEO at seed": _ceo_at(ticker, c.get("seed_fiscal") or seed.get("fiscal_period"), regimes),
            "Promise / goal as stated (seed quote)": str(seed.get("excerpt") or tree.get("parent_seed_excerpt") or ""),
            "Proposal": proposal,
            "Outcome quote (verdict evidence)": str(c.get("supporting_excerpt") or ""),
            "Conf.": str(c.get("confidence") or ""),
            "Quote verbatim?": "" if edge == "none" else ("Yes" if verified else "NO"),
            "Model reasoning": str(c.get("reasoning") or ""),
            "Other evidence": _fmt_evidence(c.get("evidence") or [], c.get("supporting_excerpt")),
            "Status": ov_status.get(tid, ""),
            "Materiality": mat_val,
            "_ticker": ticker, "_tree_id": tid, "_edge": edge,
        })
        seen.add(tid)

    # needs_review entries that never produced a candidate (e.g. no transcripts indexed)
    for r in terminal.get("needs_review") or []:
        tid = str(r.get("tree_id"))
        if tid in seen:
            continue
        ticker = str(r.get("ticker") or "").upper()
        tree = trees.get(tid) or {}
        seed = tree.get("seed") or {}
        mat_val = str(seed.get("materiality") or tree.get("materiality") or "").strip()
        if not mat_val:
            mat_val = infer_materiality(tree or r)
        by_ticker[ticker].append({
            "Row ID": f"V:{tid}",
            "Type": "Verdict",
            "Kind": str(r.get("kind") or tree.get("kind") or ""),
            "Title": str(r.get("title") or tree.get("title") or ""),
            "Seed qtr": str(r.get("seed_fiscal") or seed.get("fiscal_period") or ""),
            "Clock": str(r.get("clock") or "") or "—",
            "CEO at seed": _ceo_at(ticker, r.get("seed_fiscal") or seed.get("fiscal_period"), regimes),
            "Promise / goal as stated (seed quote)": str(r.get("seed_excerpt") or seed.get("excerpt") or ""),
            "Proposal": f"NEEDS REVIEW: {r.get('reason')} — {r.get('detail')}",
            "Outcome quote (verdict evidence)": "",
            "Conf.": "",
            "Quote verbatim?": "",
            "Model reasoning": (f"transcripts present {r.get('transcripts_present')}, "
                                f"missing {r.get('transcripts_missing')}, quarters searched {r.get('quarters_searched')}"),
            "Other evidence": "",
            "Status": ov_status.get(tid, ""),
            "Materiality": mat_val,
            "_ticker": ticker, "_tree_id": tid, "_edge": "needs_review",
        })
    return by_ticker


def seed_rows(
    seeds: Mapping,
    regimes: list[dict],
    overlay_status: dict[str, str] | None = None,
) -> dict[str, list[dict]]:
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    ov_status = overlay_status or {}
    for ticker, cands in (seeds.get("candidates_by_ticker") or {}).items():
        ticker = str(ticker).upper()
        for c in cands or []:
            s = c.get("seed") or {}
            tid = str(c.get("tree_id"))
            # Materiality: use candidate field if present (E2 may inject it), else seed field, else infer
            mat_val = str(c.get("materiality") or s.get("materiality") or "").strip()
            if not mat_val:
                mat_val = infer_materiality(c)
            # Status: "provisional-applied"/"confirmed" if already in overlay, else "queued"
            status_val = ov_status.get(tid, "queued")
            by_ticker[ticker].append({
                "Row ID": f"S:{tid}",
                "Type": "New seed",
                "Kind": str(c.get("kind") or ""),
                "Title": str(c.get("title") or ""),
                "Seed qtr": str(s.get("fiscal_period") or ""),
                "Clock": str(s.get("clock") or "") or "—",
                "CEO at seed": _ceo_at(ticker, s.get("fiscal_period"), regimes),
                "Promise / goal as stated (seed quote)": str(s.get("excerpt") or ""),
                "Proposal": f"new {c.get('kind')} tree · bucket: {c.get('bucket')}\nobjects: {', '.join(c.get('objects') or [])}",
                "Outcome quote (verdict evidence)": "",
                "Conf.": str(c.get("confidence") or ""),
                "Quote verbatim?": "Yes" if c.get("excerpt_verified") else "NO",
                "Model reasoning": str(c.get("rationale") or ""),
                "Other evidence": "",
                "Status": status_val,
                "Materiality": mat_val,
                "_ticker": ticker, "_tree_id": tid, "_edge": "seed",
            })
    for rows in by_ticker.values():
        rows.sort(key=lambda r: fiscal_key(r["Seed qtr"]))
    return by_ticker


# ── workbook ─────────────────────────────────────────────────────────────────

def build(xlsx_out: Path = XLSX_OUT) -> dict[str, Any]:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    terminal = _load_json(TERMINAL_IN)
    seeds = _load_json(SEEDS_IN)
    regimes = load_management_regimes()
    trees = _tree_index()
    overlay_status = _build_overlay_status()

    verdicts = verdict_rows(terminal, trees, regimes, overlay_status)
    new_seeds = seed_rows(seeds, regimes, overlay_status)
    tickers = sorted(set(verdicts) | set(new_seeds))

    wb = Workbook()
    readme = wb.active
    readme.title = "README"
    summary = wb.create_sheet("Summary")

    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F3864")
    section_fill = PatternFill("solid", fgColor="D9E1F2")
    verdict_fill = PatternFill("solid", fgColor="FFF2CC")
    wrap = Alignment(wrap_text=True, vertical="top")
    green = PatternFill("solid", fgColor="C6EFCE")
    red = PatternFill("solid", fgColor="FFC7CE")
    amber = PatternFill("solid", fgColor="FFEB9C")
    grey = PatternFill("solid", fgColor="E7E6E6")

    dec_letter = get_column_letter(COL["DECISION"])
    totals = Counter()
    per_ticker_counts: list[tuple[str, int, int, str]] = []

    for ticker in tickers:
        ws = wb.create_sheet(ticker)
        v_rows = verdicts.get(ticker, [])
        s_rows = new_seeds.get(ticker, [])
        per_ticker_counts.append((ticker, len(v_rows), len(s_rows), _regime_caption(ticker, regimes)))
        totals["verdicts"] += len(v_rows)
        totals["seeds"] += len(s_rows)

        ws.cell(row=1, column=1, value=f"{ticker} — Claims Desk review").font = Font(bold=True, size=13)
        ws.cell(row=2, column=1, value=_regime_caption(ticker, regimes)).font = Font(italic=True)
        ws.cell(row=3, column=1, value=(f"{len(v_rows)} verdict(s) on existing trees · {len(s_rows)} proposed new seed(s). "
                                        "Fill DECISION for every row; Notes are free text.")).font = Font(italic=True)

        hdr_row = 5
        for idx, (name, width) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=hdr_row, column=idx, value=name)
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
            ws.column_dimensions[get_column_letter(idx)].width = width
        ws.row_dimensions[hdr_row].height = 30
        ws.freeze_panes = ws.cell(row=hdr_row + 1, column=5)

        r = hdr_row + 1
        first_data_row = r

        def section(label: str) -> None:
            nonlocal r
            c = ws.cell(row=r, column=1, value=label)
            c.font = Font(bold=True)
            for col in range(1, len(COLUMNS) + 1):
                ws.cell(row=r, column=col).fill = section_fill
            r += 1

        def write_rows(rows: list[dict], fill: PatternFill | None) -> None:
            nonlocal r
            for row in rows:
                for idx, name in enumerate(HEADERS, start=1):
                    c = ws.cell(row=r, column=idx, value=row.get(name, ""))
                    c.alignment = wrap
                    if fill is not None and name not in ("DECISION", "Notes"):
                        c.fill = fill
                if row.get("Quote verbatim?") == "NO":
                    ws.cell(row=r, column=COL["Quote verbatim?"]).fill = amber
                r += 1

        section("A. Verdicts on existing trees — did the promise come true?")
        write_rows(v_rows, verdict_fill) if v_rows else write_rows([{"Title": "(no open trees scored for this ticker)"}], None)
        r += 1
        section("B. Proposed new seeds — should this become a tracked promise / goal?")
        write_rows(s_rows, None) if s_rows else write_rows([{"Title": "(no seeds proposed for this ticker)"}], None)
        last_data_row = r - 1

        dv = DataValidation(type="list", formula1='"' + ",".join(DECISIONS) + '"', allow_blank=True,
                            showErrorMessage=True, errorTitle="Decision", error="Pick Accept, Reject, Re-cite or Defer")
        ws.add_data_validation(dv)
        dv.add(f"{dec_letter}{first_data_row}:{dec_letter}{last_data_row}")

        mat_letter = get_column_letter(COL["Materiality"])
        mat_dv = DataValidation(type="list", formula1='"high,medium,low"', allow_blank=True)
        ws.add_data_validation(mat_dv)
        mat_dv.add(f"{mat_letter}{first_data_row}:{mat_letter}{last_data_row}")

        rng = f"{dec_letter}{first_data_row}:{dec_letter}{last_data_row}"
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Accept"'], fill=green))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Reject"'], fill=red))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Re-cite"'], fill=amber))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=['"Defer"'], fill=grey))
        ws.auto_filter.ref = f"A{hdr_row}:{get_column_letter(len(COLUMNS))}{last_data_row}"

    # Summary tab: live COUNTIF formulas so progress shows as the analyst works.
    sum_headers = ["Ticker", "Verdicts", "New seeds", "Rows", "Accept", "Reject", "Re-cite", "Defer", "Undecided", "CEO regimes"]
    for idx, h in enumerate(sum_headers, start=1):
        c = summary.cell(row=1, column=idx, value=h)
        c.font = head_font
        c.fill = head_fill
    row_id_letter = get_column_letter(COL["Row ID"])
    for i, (ticker, nv, ns, caption) in enumerate(per_ticker_counts, start=2):
        summary.cell(row=i, column=1, value=ticker)
        summary.cell(row=i, column=2, value=nv)
        summary.cell(row=i, column=3, value=ns)
        summary.cell(row=i, column=4, value=nv + ns)
        for j, d in enumerate(DECISIONS, start=5):
            summary.cell(row=i, column=j, value=f"=COUNTIF('{ticker}'!{dec_letter}:{dec_letter},\"{d}\")")
        # undecided = rows with a Row ID (V:/S:) minus decided
        summary.cell(row=i, column=9, value=(f"=COUNTIF('{ticker}'!{row_id_letter}:{row_id_letter},\"V:*\")"
                                             f"+COUNTIF('{ticker}'!{row_id_letter}:{row_id_letter},\"S:*\")"
                                             f"-SUM(E{i}:H{i})"))
        summary.cell(row=i, column=10, value=caption.replace("CEO regimes: ", ""))
    tot = len(per_ticker_counts) + 2
    summary.cell(row=tot, column=1, value="TOTAL").font = Font(bold=True)
    for col in range(2, 10):
        L = get_column_letter(col)
        summary.cell(row=tot, column=col, value=f"=SUM({L}2:{L}{tot - 1})").font = Font(bold=True)
    for idx, w in enumerate([8, 9, 10, 7, 8, 8, 8, 8, 10, 90], start=1):
        summary.column_dimensions[get_column_letter(idx)].width = w
    summary.freeze_panes = "B2"

    # README tab
    lines = [
        "CLAIMS DESK REVIEW — what to do",
        "",
        f"Built {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from:",
        f"  verdicts: {TERMINAL_IN.name} (generated {terminal.get('generated_at')})",
        f"  seeds:    {SEEDS_IN.name} (generated {seeds.get('generated_at')})",
        "",
        f"{totals['verdicts']} verdicts + {totals['seeds']} proposed seeds across {len(tickers)} tickers. One tab per ticker.",
        "",
        "Each tab has two sections:",
        "  A. Verdicts — an existing tracked promise/goal and the model's proposed outcome, with the",
        "     verbatim transcript sentence it relied on. Compare the seed quote (col H) to the outcome quote (col J).",
        "  B. New seeds — sentences the model thinks are dated promises or goals worth tracking.",
        "",
        "Fill the DECISION column (dropdown) on every row:",
        "  Accept   verdict: type the outcome as proposed | seed: add the tree as proposed",
        "  Reject   verdict: leave the tree open (proposal wrong) | seed: not a desk object / duplicate / rhetoric",
        "  Re-cite  right object, wrong or non-verbatim sentence — find the exact quote before typing",
        "  Defer    park it for the next pass",
        "",
        "Rows whose Proposal is 'none' mean the model found no outcome; Accept = agree, keep the tree open.",
        "'Quote verbatim? = NO' (amber) means the sentence is NOT found word-for-word in the source — the book",
        "builder will reject it, so choose Re-cite or Reject rather than Accept.",
        "Rows marked NEEDS REVIEW could not be resolved automatically; the reason is in the Proposal column.",
        "",
        "Push back hardest on 'delivered' verdicts: the current mix is 25 delivered vs 2 missed, and",
        "the model leans delivered whenever evidence exists. A vague or partial match is a Reject.",
        "",
        "When done, save this file in place and run:",
        "  python scripts/_desk_review_sheet.py read",
        "which writes data/desk_review_decisions.json; accepted rows are then typed into the catalogs.",
        "",
        "Summary tab shows live counts per ticker (Accept / Reject / Re-cite / Defer / Undecided).",
    ]
    for i, line in enumerate(lines, start=1):
        c = readme.cell(row=i, column=1, value=line)
        if i == 1:
            c.font = Font(bold=True, size=14)
    readme.column_dimensions["A"].width = 120

    xlsx_out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx_out)
    return {"path": str(xlsx_out), "tickers": len(tickers), **totals}


# ── read-back ────────────────────────────────────────────────────────────────

def read(xlsx_in: Path = XLSX_OUT, decisions_out: Path = DECISIONS_OUT, *, strict: bool = False) -> dict[str, Any]:
    from openpyxl import load_workbook

    if not xlsx_in.is_file():
        raise SystemExit(f"workbook not found: {xlsx_in} (run `build` first)")
    wb = load_workbook(xlsx_in, data_only=True)
    decisions: list[dict] = []
    undecided: list[str] = []
    for ws in wb.worksheets:
        if ws.title in ("README", "Summary"):
            continue
        header_row = None
        for row in ws.iter_rows(min_row=1, max_row=10):
            if row[0].value == "Row ID":
                header_row = row[0].row
                break
        if header_row is None:
            continue
        headers = [str(c.value or "") for c in ws[header_row]]
        try:
            i_id, i_dec, i_notes = headers.index("Row ID"), headers.index("DECISION"), headers.index("Notes")
        except ValueError:
            continue
        i_mat = headers.index("Materiality") if "Materiality" in headers else None
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            rid = row[i_id] if i_id < len(row) else None
            if not isinstance(rid, str) or not (rid.startswith("V:") or rid.startswith("S:")):
                continue
            dec = (row[i_dec] if i_dec < len(row) else None) or ""
            dec = str(dec).strip()
            notes = row[i_notes] if i_notes < len(row) else None
            mat_raw = (row[i_mat] if (i_mat is not None and i_mat < len(row)) else None)
            mat_val = str(mat_raw).strip() if mat_raw not in (None, "") else None
            if dec and dec not in DECISIONS:
                raise SystemExit(f"{ws.title}: unknown decision {dec!r} on {rid}")
            if not dec:
                undecided.append(f"{ws.title}:{rid}")
            decisions.append({
                "row_id": rid,
                "type": "verdict" if rid.startswith("V:") else "seed",
                "ticker": ws.title,
                "tree_id": rid[2:],
                "decision": dec or None,
                "materiality": mat_val,
                "notes": str(notes).strip() if notes not in (None, "") else None,
            })
    if strict and undecided:
        raise SystemExit(f"{len(undecided)} undecided rows, e.g. {undecided[:5]}")

    counts = Counter(d["decision"] or "undecided" for d in decisions)
    by_type = {t: dict(Counter(d["decision"] or "undecided" for d in decisions if d["type"] == t)) for t in ("verdict", "seed")}
    payload = {
        "note": "Analyst decisions read from desk_review_sheet.xlsx. Apply step types Accept rows into the catalogs; nothing is auto-inserted.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workbook": str(xlsx_in.relative_to(ROOT)) if xlsx_in.is_relative_to(ROOT) else str(xlsx_in),
        "n_rows": len(decisions),
        "counts": dict(counts),
        "counts_by_type": by_type,
        "decisions": decisions,
    }
    decisions_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": str(decisions_out), "n_rows": len(decisions), "counts": dict(counts), "undecided": len(undecided)}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="write the review workbook")
    b.add_argument("--out", type=Path, default=XLSX_OUT)
    r = sub.add_parser("read", help="read decisions back out of the workbook")
    r.add_argument("--in", dest="inp", type=Path, default=XLSX_OUT)
    r.add_argument("--out", type=Path, default=DECISIONS_OUT)
    r.add_argument("--strict", action="store_true", help="fail if any row is undecided")
    args = ap.parse_args(argv)
    if args.cmd == "read":
        res = read(args.inp, args.out, strict=args.strict)
    else:
        res = build(getattr(args, "out", XLSX_OUT))
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
