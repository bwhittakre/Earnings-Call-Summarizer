#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 3 prep — earnings-call date list for the Phase 0 candidate universe.
============================================================================

Not part of the scoring pipeline. A one-off research utility that turns the
Phase 0 candidate list (``output/universe/candidate_list.csv``, built by
``universe_reconstruction.py``) into a concrete "what transcript, for what
date" checklist for manual sourcing, split into what ROIC.ai's free tier can
fetch automatically (~last 2 years / 8 quarters) vs. what needs a manual pull
for the remaining ~8 years of the 10-year window.

Earnings-call dates aren't published as their own SEC field, so this uses each
company's Item 2.02 ("Results of Operations and Financial Condition") 8-K
filing date as a same-day-or-next-day proxy for the call date -- the same
signal ``src/validation`` and ``earnings_scraper`` already lean on elsewhere in
this repo. Pulls the *full* filing history (paginating through
``filings.files`` for anything older than the ``recent`` window holds), not
just the most recent page.

Usage:
    python "Structured Narrative/phase3_prep_transcript_dates.py"
    python "Structured Narrative/phase3_prep_transcript_dates.py" --years 10 --roic-quarters 8
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
CANDIDATE_LIST = HERE / "output" / "universe" / "candidate_list.csv"
OUT_CSV = HERE / "output" / "universe" / "phase3_transcript_sourcing_checklist.csv"
OUT_SUMMARY = HERE / "output" / "universe" / "phase3_transcript_sourcing_summary.csv"

SEC_USER_AGENT = "earnings-scraper (contact: nhirt@cassiuscap.com)"
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
EARNINGS_ITEM = "2.02"


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=30.0,
        follow_redirects=True,
    )


def load_ticker_cik_map(client: httpx.Client) -> dict[str, tuple[str, str]]:
    """ticker -> (cik10, company title)."""
    resp = client.get(TICKER_MAP_URL)
    resp.raise_for_status()
    out: dict[str, tuple[str, str]] = {}
    for row in resp.json().values():
        ticker = str(row.get("ticker", "")).upper()
        if ticker:
            out[ticker] = (str(row.get("cik_str", "")).zfill(10), str(row.get("title", "")))
    return out


@dataclass
class FilingHit:
    form: str
    filing_date: str
    accession: str


def _rows_from_block(block: dict) -> list[dict]:
    forms = block.get("form", [])
    n = len(forms)
    items = block.get("items") or [""] * n
    dates = block.get("filingDate") or [""] * n
    accs = block.get("accessionNumber") or [""] * n
    return [
        {"form": forms[i], "items": items[i], "filing_date": dates[i], "accession": accs[i]}
        for i in range(n)
    ]


def fetch_earnings_8k_dates(client: httpx.Client, cik10: str, earliest: date) -> list[FilingHit]:
    """All Item-2.02 8-K filing dates back to ``earliest``, paginating as needed."""
    resp = client.get(SUBMISSIONS_URL.format(cik10=cik10))
    resp.raise_for_status()
    payload = resp.json()
    filings = payload.get("filings", {})

    all_rows = _rows_from_block(filings.get("recent", {}))
    oldest_seen = min(
        (r["filing_date"] for r in all_rows if r["filing_date"]), default=None
    )

    for extra in filings.get("files", []):
        if oldest_seen and oldest_seen <= earliest.isoformat():
            break
        resp2 = client.get(SUBMISSIONS_FILE_URL.format(name=extra["name"]))
        if resp2.status_code != 200:
            continue
        page_rows = _rows_from_block(resp2.json())
        all_rows.extend(page_rows)
        page_oldest = min((r["filing_date"] for r in page_rows if r["filing_date"]), default=None)
        if page_oldest:
            oldest_seen = min(oldest_seen, page_oldest) if oldest_seen else page_oldest
        time.sleep(0.15)  # be polite to data.sec.gov

    hits = [
        FilingHit(form=r["form"], filing_date=r["filing_date"], accession=r["accession"])
        for r in all_rows
        if r["form"] == "8-K"
        and EARNINGS_ITEM in str(r["items"])
        and r["filing_date"]
        and r["filing_date"] >= earliest.isoformat()
    ]
    hits.sort(key=lambda h: h.filing_date)
    return hits


def calendar_quarter(iso_date: str) -> str:
    y, m, _ = iso_date.split("-")
    q = (int(m) - 1) // 3 + 1
    return f"{y}-Q{q}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", type=int, default=10, help="How many years back to cover (default: 10).")
    ap.add_argument(
        "--roic-quarters",
        type=int,
        default=8,
        help="Most recent N earnings dates ROIC's free tier can fetch automatically (default: 8).",
    )
    args = ap.parse_args()

    if not CANDIDATE_LIST.exists():
        print(f"Error: {CANDIDATE_LIST} not found -- run universe_reconstruction.py first.", file=sys.stderr)
        return 1

    with CANDIDATE_LIST.open(encoding="utf-8") as fh:
        candidates = list(csv.DictReader(fh))

    earliest = date.today() - timedelta(days=365 * args.years + 30)
    rows: list[dict] = []
    summary: list[dict] = []

    with _client() as client:
        cik_map = load_ticker_cik_map(client)
        for cand in candidates:
            ticker = cand["ticker"].upper()
            resolved = cik_map.get(ticker)
            if not resolved:
                print(f"  ! {ticker}: no SEC CIK found -- skipping", file=sys.stderr)
                summary.append({"ticker": ticker, "company": "", "n_dates_found": 0, "note": "no CIK resolved"})
                continue
            cik10, company = resolved
            try:
                hits = fetch_earnings_8k_dates(client, cik10, earliest)
            except httpx.HTTPError as exc:
                print(f"  ! {ticker}: EDGAR fetch failed ({exc}) -- skipping", file=sys.stderr)
                summary.append({"ticker": ticker, "company": company, "n_dates_found": 0, "note": f"fetch failed: {exc}"})
                continue

            n = len(hits)
            n_auto = min(args.roic_quarters, n)
            n_manual = n - n_auto
            for idx, hit in enumerate(hits):
                sourcing = "roic_auto" if idx >= n - args.roic_quarters else "manual"
                rows.append(
                    {
                        "ticker": ticker,
                        "company": company,
                        "approx_call_date": hit.filing_date,
                        "calendar_quarter": calendar_quarter(hit.filing_date),
                        "sourcing": sourcing,
                        "proxy_filing_form": hit.form,
                        "proxy_filing_accession": hit.accession,
                    }
                )
            summary.append(
                {
                    "ticker": ticker,
                    "company": company,
                    "n_dates_found": n,
                    "n_roic_auto": n_auto,
                    "n_manual_needed": n_manual,
                    "earliest_date": hits[0].filing_date if hits else "",
                    "latest_date": hits[-1].filing_date if hits else "",
                    "note": "" if n else "no Item 2.02 8-Ks found in window",
                }
            )
            print(f"  {ticker} ({company}): {n} earnings dates found, {n_manual} need manual sourcing")
            time.sleep(0.15)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ticker", "company", "approx_call_date", "calendar_quarter",
                "sourcing", "proxy_filing_form", "proxy_filing_accession",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {OUT_CSV} ({len(rows)} rows)")

    with OUT_SUMMARY.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ticker", "company", "n_dates_found", "n_roic_auto", "n_manual_needed",
                "earliest_date", "latest_date", "note",
            ],
        )
        writer.writeheader()
        writer.writerows(summary)
    print(f"Wrote {OUT_SUMMARY} ({len(summary)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
