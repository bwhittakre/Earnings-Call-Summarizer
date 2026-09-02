#!/usr/bin/env python3
"""Resumable transcript back-fill for the ops + HC claims desk (Step 0 of retrieval-first scoring).

The pull itself runs through the Quartr MCP in the agent session; Cursor writes each large
``read_transcript`` / ``list_events`` result to ``agent-tools/*.txt``. This script does the
bookkeeping around those dumps so the pull can stop and resume at any point:

  plan    compute the target (ticker, period) set from the desk books + novelty coverage,
          prioritise it, and write data/transcript_backfill_manifest.json
  events  register Quartr event ids per (ticker, period) — from agent-tools list_events dumps
          and/or ``--add TICKER FY2017-Q4=62683 ...``
  stage   sweep agent-tools read_transcript dumps into staging windows, assemble complete
          transcripts into Structured Narrative/transcripts_raw/{TICKER}_{PERIOD}.txt, update
          the manifest, and print the remaining work queue (NEXT / TODO lines)
  status  print coverage by priority

NVDA (gold book) is excluded everywhere. No LLM. Does not read novelty excerpts for content —
only their fiscal_period labels, to know which quarters the desk covers.

Manifest statuses per (ticker, period):
  present         transcripts_raw file exists (>2 KB)
  staged_partial  one or more windows staged, last window has nextFromTimestamp
  missing         no transcript, event id known or unknown
  no_event        Quartr has no earnings_call event for this period (set manually via --no-event)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._assemble_quartr_windows import paragraphs_to_text  # noqa: E402
from scripts._desk_trees_v2 import fiscal_key  # noqa: E402
from scripts._desk_trees_v2_recall import novelty_path, novelty_periods  # noqa: E402
from scripts._desk_transcript_index import raw_path  # noqa: E402
from services.earnings_monitor.dashboard.claims_trees import (  # noqa: E402
    load_desk_trees_hc_v2,
    load_desk_trees_ops_v2,
)

RAW_DIR = ROOT / "Structured Narrative" / "transcripts_raw"
STAGING = ROOT / "data" / "transcripts_backfill" / "windows"
MANIFEST = ROOT / "data" / "transcript_backfill_manifest.json"
EVENTS = ROOT / "data" / "transcript_backfill_events.json"
AGENT_TOOLS = Path(
    r"C:\Users\BobbyWhittaker\.cursor\projects"
    r"\c-Users-BobbyWhittaker-OneDrive-Cassius-Capital-Desktop-Earnings-Call-Summarizer"
    r"\agent-tools"
)
GOLD_TICKERS = frozenset({"NVDA"})
MIN_RAW_BYTES = 2000
CLOCK_WINDOW_AFTER = 2  # clock + 2 quarters
CLOCK_WINDOW_MAX = 6

_TITLE_RE = re.compile(r"Q([1-4])\s+(\d{4})")


# ── fiscal helpers ───────────────────────────────────────────────────────────

def fiscal_label(year: int, quarter: int) -> str:
    return f"FY{year}-Q{quarter}"


def fiscal_add(fiscal: str, n: int) -> str:
    year, quarter = fiscal_key(fiscal)
    if year < 0:
        return fiscal
    idx = year * 4 + (quarter - 1) + n
    return fiscal_label(idx // 4, idx % 4 + 1)


def fiscal_range(start: str, end: str) -> list[str]:
    """Inclusive list of fiscal labels from start to end (start <= end)."""
    out: list[str] = []
    if fiscal_key(start) < (0, 0) or fiscal_key(end) < (0, 0):
        return out
    cur = start
    while fiscal_key(cur) <= fiscal_key(end):
        out.append(cur)
        cur = fiscal_add(cur, 1)
        if len(out) > 200:
            break
    return out


def clock_window(seed_fiscal: str, clock: str | None) -> list[str]:
    """seed+1 .. clock+CLOCK_WINDOW_AFTER, capped at CLOCK_WINDOW_MAX quarters. Empty if no clock."""
    if not clock or fiscal_key(clock) < (0, 0) or fiscal_key(seed_fiscal) < (0, 0):
        return []
    start = fiscal_add(seed_fiscal, 1)
    end = fiscal_add(clock, CLOCK_WINDOW_AFTER)
    if fiscal_key(end) < fiscal_key(start):
        end = start
    window = fiscal_range(start, end)
    return window[:CLOCK_WINDOW_MAX]


# ── io helpers ───────────────────────────────────────────────────────────────

def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def raw_present(ticker: str, period: str) -> bool:
    """Either raw layout counts: flat `{TICKER}_{PERIOD}.txt` or per-ticker `{TICKER}/{PERIOD}.txt`."""
    return raw_path(ticker, period, MIN_RAW_BYTES) is not None


# ── plan ─────────────────────────────────────────────────────────────────────

def _open_trees(book: dict) -> list[dict]:
    trees = book.get("trees") or []
    return [t for t in trees if t.get("open") or t.get("state") == "open"]


def build_plan() -> dict:
    """Target set = every novelty period for every ops/HC ticker; prioritised by open-tree need."""
    books = [("desk_ops_v2", load_desk_trees_ops_v2()), ("desk_hc_v2", load_desk_trees_hc_v2())]
    tickers: dict[str, dict] = {}
    p1: set[tuple[str, str]] = set()
    p2: set[tuple[str, str]] = set()
    tree_needs: dict[str, dict] = {}

    for book_name, book in books:
        all_tickers = {str(t.get("ticker") or "").upper() for t in (book.get("trees") or [])}
        for ticker in sorted(all_tickers - GOLD_TICKERS):
            if not ticker:
                continue
            novelty = _load_json(novelty_path(ticker), None)
            periods = novelty_periods(novelty) if isinstance(novelty, dict) else []
            tickers.setdefault(ticker, {"book": book_name, "periods": {}})
            for period in periods:
                tickers[ticker]["periods"].setdefault(period, {"priority": 3})

        for tree in _open_trees(book):
            ticker = str(tree.get("ticker") or "").upper()
            if ticker in GOLD_TICKERS or ticker not in tickers:
                continue
            seed = tree.get("seed") or {}
            seed_fp = str(seed.get("fiscal_period") or "")
            clock = tree.get("clock") or seed.get("clock")
            covered = set(tickers[ticker]["periods"])
            win = [p for p in clock_window(seed_fp, clock) if p in covered]
            post = [p for p in covered if fiscal_key(p) > fiscal_key(seed_fp)]
            for p in win:
                p1.add((ticker, p))
            for p in post:
                p2.add((ticker, p))
            tree_needs[str(tree.get("tree_id"))] = {
                "ticker": ticker,
                "seed_fiscal": seed_fp,
                "clock": clock,
                "clock_window": win,
                "n_post_seed": len(post),
            }

    prior = _load_json(MANIFEST, {})
    prior_tickers = prior.get("tickers") or {}
    events = _load_json(EVENTS, {})

    for ticker, block in tickers.items():
        for period, meta in block["periods"].items():
            if (ticker, period) in p1:
                meta["priority"] = 1
            elif (ticker, period) in p2:
                meta["priority"] = 2
            old = ((prior_tickers.get(ticker) or {}).get("periods") or {}).get(period) or {}
            ev = ((events.get(ticker) or {}).get(period)) or {}
            meta["event_id"] = ev.get("event_id") or old.get("event_id")
            meta["event_date"] = ev.get("date") or old.get("event_date")
            meta["staged_windows"] = old.get("staged_windows", 0)
            meta["next_from"] = old.get("next_from")
            if raw_present(ticker, period):
                meta["status"] = "present"
            elif old.get("status") == "no_event":
                meta["status"] = "no_event"
            elif meta["staged_windows"]:
                meta["status"] = "staged_partial"
            else:
                meta["status"] = "missing"

    manifest = {
        "note": "Transcript back-fill manifest for ops + HC desk. NVDA excluded. No LLM.",
        "generated_at": _now(),
        "priority_legend": {
            "1": "clock window (seed+1..clock+2, max 6) of an open tree",
            "2": "post-seed quarter of an open tree",
            "3": "other desk-covered quarter",
        },
        "tickers": tickers,
        "tree_needs": tree_needs,
    }
    manifest["summary"] = summarize(manifest)
    return manifest


def summarize(manifest: dict) -> dict:
    counts: dict[str, dict[str, int]] = {str(p): {} for p in (1, 2, 3)}
    total = 0
    for block in (manifest.get("tickers") or {}).values():
        for meta in (block.get("periods") or {}).values():
            pr = str(meta.get("priority", 3))
            st = str(meta.get("status", "missing"))
            counts.setdefault(pr, {})
            counts[pr][st] = counts[pr].get(st, 0) + 1
            total += 1
    return {"n_periods": total, "by_priority": counts}


# ── events ───────────────────────────────────────────────────────────────────

def _period_from_event(ev: dict) -> str | None:
    et = str(ev.get("eventType") or "")
    fy = ev.get("fiscalYear")
    m = re.fullmatch(r"q_([1-4])", et)
    if m and fy:
        try:
            return fiscal_label(int(fy), int(m.group(1)))
        except ValueError:
            pass
    t = _TITLE_RE.search(str(ev.get("title") or ""))
    if t:
        return fiscal_label(int(t.group(2)), int(t.group(1)))
    return None


def register_events(events_payloads: Iterable[dict], explicit: Iterable[str]) -> dict:
    events = _load_json(EVENTS, {})
    added = 0
    for payload in events_payloads:
        for ev in payload.get("events") or []:
            if str(ev.get("parentEventType") or "") not in ("earnings_call", ""):
                continue
            ticker = str(((ev.get("company") or {}).get("ticker")) or "").upper()
            period = _period_from_event(ev)
            eid = ev.get("id")
            if not ticker or not period or eid is None or ticker in GOLD_TICKERS:
                continue
            slot = events.setdefault(ticker, {})
            if period in slot and slot[period].get("event_id") != eid:
                # keep the earliest-dated event for a period (re-runs / duplicates)
                if str(ev.get("date") or "") >= str(slot[period].get("date") or ""):
                    continue
            slot[period] = {"event_id": int(eid), "date": ev.get("date"), "title": ev.get("title")}
            added += 1
    # --add MSFT FY2017-Q4=62683 FY2018-Q1=62676
    explicit = list(explicit)
    if explicit:
        ticker = explicit[0].upper()
        for item in explicit[1:]:
            if "=" not in item:
                continue
            period, eid = item.split("=", 1)
            events.setdefault(ticker, {})[period.strip().upper()] = {
                "event_id": int(eid.strip()),
                "date": None,
                "title": None,
            }
            added += 1
    _dump_json(EVENTS, events)
    return {"added": added, "n_tickers": len(events), "n_events": sum(len(v) for v in events.values())}


def sweep_agent_tools(kind: str, since_mtime: float = 0.0) -> list[tuple[Path, dict]]:
    """Return (path, payload) for agent-tools dumps of the requested kind: 'events' | 'transcript'.
    Files older than ``since_mtime`` (epoch seconds) are skipped — they were swept before."""
    found: list[tuple[Path, dict]] = []
    if not AGENT_TOOLS.is_dir():
        return found
    for path in AGENT_TOOLS.glob("*.txt"):
        try:
            if since_mtime and path.stat().st_mtime < since_mtime:
                continue
            head = path.open("r", encoding="utf-8").read(64)
        except OSError:
            continue
        if not head.lstrip().startswith("{"):
            continue
        if kind == "events" and '"events"' not in head:
            continue
        if kind == "transcript" and '"eventId"' not in head:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if kind == "events" and isinstance(data.get("events"), list):
            found.append((path, data))
        elif kind == "transcript" and "paragraphs" in data and data.get("eventId") is not None:
            found.append((path, data))
    return found


# ── stage ────────────────────────────────────────────────────────────────────

COVERAGE_GAP_TOLERANCE_S = 90.0


def merge_windows(payloads: list[dict]) -> tuple[bool, float | None, list[dict]]:
    """Union the paragraphs of several read_transcript windows (full-from-start, fromTimestamp
    continuations, or a `section=qna` window) into one ordered, de-duplicated list.

    Returns (complete, next_from, paragraphs). Complete when the windows chain without a gap
    larger than COVERAGE_GAP_TOLERANCE_S and the window that reaches furthest has no
    nextFromTimestamp. A qna-only or gapped set is never complete.
    """
    windows: list[tuple[float, float, dict, list[dict]]] = []
    for payload in payloads:
        paras = [p for p in (payload.get("paragraphs") or []) if isinstance(p, dict) and p.get("start") is not None]
        if not paras:
            continue
        starts = [float(p["start"]) for p in paras]
        windows.append((min(starts), max(starts), payload, paras))
    if not windows:
        return False, None, []
    windows.sort(key=lambda w: w[0])
    if windows[0][0] > COVERAGE_GAP_TOLERANCE_S:
        # no window starts at the beginning of the call
        return False, None, []
    coverage_end = windows[0][1]
    tail_payload = windows[0][2]
    for lo, hi, payload, _ in windows[1:]:
        if lo > coverage_end + COVERAGE_GAP_TOLERANCE_S:
            return False, tail_payload.get("nextFromTimestamp"), []
        if hi >= coverage_end:
            coverage_end = hi
            tail_payload = payload
    next_from = tail_payload.get("nextFromTimestamp")
    seen: set = set()
    merged: list[dict] = []
    for _, _, _, paras in windows:
        for p in paras:
            key = p.get("paragraphId") or (p.get("start"), (p.get("text") or "")[:40])
            if key in seen:
                continue
            seen.add(key)
            merged.append(p)
    merged.sort(key=lambda p: float(p["start"]))
    return next_from is None, next_from, merged


def _event_lookup(events: dict) -> dict[int, tuple[str, str]]:
    lookup: dict[int, tuple[str, str]] = {}
    for ticker, periods in events.items():
        for period, meta in periods.items():
            eid = meta.get("event_id")
            if eid is not None:
                lookup[int(eid)] = (ticker, period)
    return lookup


def stage_dumps(manifest: dict) -> dict:
    events = _load_json(EVENTS, {})
    lookup = _event_lookup(events)
    staged = 0
    skipped_unknown = 0
    touched: set[tuple[str, str]] = set()
    # only look at dumps newer than the last sweep (minus a 10-minute safety margin)
    since = float(manifest.get("last_sweep_epoch") or 0.0)
    sweep_started = datetime.now(timezone.utc).timestamp()
    for path, data in sweep_agent_tools("transcript", since_mtime=max(0.0, since - 600)):
        eid = int(data["eventId"])
        if eid not in lookup:
            skipped_unknown += 1
            continue
        ticker, period = lookup[eid]
        if raw_present(ticker, period):
            continue
        paras = [p for p in (data.get("paragraphs") or []) if isinstance(p, dict)]
        starts = [float(p["start"]) for p in paras if p.get("start") is not None]
        if not paras or not starts:
            continue
        dest_dir = STAGING / ticker / period
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{int(min(starts)):06d}.json"
        if dest.exists():
            continue
        if min(starts) > COVERAGE_GAP_TOLERANCE_S:
            # a late-starting window that overlaps an already-staged one is a `section=qna` pull
            for existing in dest_dir.glob("*.json"):
                prior = _load_json(existing, {})
                prior_starts = [float(p["start"]) for p in (prior.get("paragraphs") or []) if isinstance(p, dict) and p.get("start") is not None]
                if prior_starts and max(prior_starts) > min(starts):
                    data["_section"] = "qna"
                    break
        dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        staged += 1
        touched.add((ticker, period))

    assembled = 0
    tickers = manifest.setdefault("tickers", {})
    for ticker_dir in sorted(p for p in STAGING.iterdir() if p.is_dir()) if STAGING.is_dir() else []:
        ticker = ticker_dir.name.upper()
        for period_dir in sorted(p for p in ticker_dir.iterdir() if p.is_dir()):
            period = period_dir.name.upper()
            if raw_present(ticker, period):
                continue
            windows = sorted(p for p in period_dir.glob("*.json") if p.is_file())
            if not windows:
                continue
            payloads = [_load_json(w, {}) for w in windows]
            meta = tickers.setdefault(ticker, {"book": "?", "periods": {}})["periods"].setdefault(
                period, {"priority": 3}
            )
            meta["staged_windows"] = len(windows)
            meta["event_id"] = meta.get("event_id") or payloads[-1].get("eventId")
            complete, next_from, paragraphs = merge_windows(payloads)
            if complete:
                text = paragraphs_to_text(paragraphs)
                if text:
                    RAW_DIR.mkdir(parents=True, exist_ok=True)
                    (RAW_DIR / f"{ticker}_{period}.txt").write_text(text + "\n", encoding="utf-8")
                    meta["status"] = "present"
                    meta["next_from"] = None
                    assembled += 1
            else:
                meta["status"] = "staged_partial"
                meta["next_from"] = next_from
                meta["has_qna_window"] = any(p.get("_section") == "qna" for p in payloads)

    # refresh present flags + event ids from events file
    for ticker, block in tickers.items():
        for period, meta in (block.get("periods") or {}).items():
            ev = ((events.get(ticker) or {}).get(period)) or {}
            if ev.get("event_id") and not meta.get("event_id"):
                meta["event_id"] = ev["event_id"]
                meta["event_date"] = ev.get("date")
            if raw_present(ticker, period):
                meta["status"] = "present"
                meta["next_from"] = None
    manifest["generated_at"] = _now()
    manifest["last_sweep_epoch"] = sweep_started
    manifest["summary"] = summarize(manifest)
    return {"staged_windows": staged, "assembled": assembled, "skipped_unknown_event": skipped_unknown}


def work_queue(manifest: dict, priority_max: int, limit: int) -> list[str]:
    """NEXT lines = partial transcripts needing another window; TODO = missing with known event id;
    NEED_EVENTS = tickers with missing periods but no event ids at all."""
    lines: list[str] = []
    rows: list[tuple[int, str, str, dict]] = []
    need_events: dict[str, int] = {}
    for ticker, block in (manifest.get("tickers") or {}).items():
        for period, meta in (block.get("periods") or {}).items():
            if meta.get("status") in ("present", "no_event"):
                continue
            pr = int(meta.get("priority", 3))
            if pr > priority_max:
                continue
            if not meta.get("event_id"):
                need_events[ticker] = need_events.get(ticker, 0) + 1
                continue
            rows.append((pr, ticker, period, meta))
    rows.sort(key=lambda r: (r[0], r[1], fiscal_key(r[2])))
    for pr, ticker, period, meta in rows[:limit]:
        if meta.get("status") == "staged_partial":
            hint = "fromTimestamp=%s" % meta.get("next_from") if meta.get("has_qna_window") else "section=qna"
            lines.append(f"NEXT p{pr} {ticker} {period} eventId={meta['event_id']} {hint}")
        else:
            lines.append(f"TODO p{pr} {ticker} {period} eventId={meta['event_id']}")
    for ticker, n in sorted(need_events.items()):
        lines.append(f"NEED_EVENTS {ticker} ({n} periods without event id)")
    return lines


# ── cli ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    ev = sub.add_parser("events")
    ev.add_argument("--add", nargs="+", default=[], metavar="ARG", help="TICKER FYxxxx-Qn=eventId ...")
    ev.add_argument("--no-sweep", action="store_true")
    st = sub.add_parser("stage")
    st.add_argument("--priority-max", type=int, default=3)
    st.add_argument("--limit", type=int, default=40)
    ne = sub.add_parser("no-event")
    ne.add_argument("ticker")
    ne.add_argument("periods", nargs="+")
    sub.add_parser("status")
    args = ap.parse_args()

    if args.cmd == "plan":
        manifest = build_plan()
        _dump_json(MANIFEST, manifest)
        print(json.dumps(manifest["summary"], indent=2))
        print(f"tickers={len(manifest['tickers'])} open_trees={len(manifest['tree_needs'])}")
        print(f"Wrote {MANIFEST}")
        return 0

    manifest = _load_json(MANIFEST, None)
    if manifest is None:
        print("No manifest — run `plan` first.", file=sys.stderr)
        return 1

    if args.cmd == "events":
        payloads = [] if args.no_sweep else [d for _, d in sweep_agent_tools("events")]
        result = register_events(payloads, args.add)
        print(json.dumps(result))
        # refresh manifest event ids
        stage_dumps(manifest)
        _dump_json(MANIFEST, manifest)
        return 0

    if args.cmd == "no-event":
        block = manifest["tickers"].get(args.ticker.upper())
        if block:
            for p in args.periods:
                meta = block["periods"].get(p.upper())
                if meta:
                    meta["status"] = "no_event"
        manifest["summary"] = summarize(manifest)
        _dump_json(MANIFEST, manifest)
        print("ok")
        return 0

    if args.cmd == "stage":
        result = stage_dumps(manifest)
        _dump_json(MANIFEST, manifest)
        print(json.dumps(result))
        print(json.dumps(manifest["summary"]))
        for line in work_queue(manifest, args.priority_max, args.limit):
            print(line)
        return 0

    if args.cmd == "status":
        print(json.dumps(manifest["summary"], indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
