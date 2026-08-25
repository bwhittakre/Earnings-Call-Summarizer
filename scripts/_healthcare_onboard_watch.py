#!/usr/bin/env python3
"""Start Healthcare Large-Cap Roz onboard as MCP seed waves finish.

Polls seed_wave_*.json + transcripts_raw. Runs one ticker at a time.
Skips live Roz book sync. Safe to leave running overnight.

  .venv\\Scripts\\python.exe scripts/_healthcare_onboard_watch.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SN = REPO / "Structured Narrative"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from services.earnings_monitor.onboard import (  # noqa: E402
    discover_on_disk_periods,
    run_onboard,
)

HC = REPO / "data" / "healthcare_large_cap"
CATALOG = HC / "company_catalog.json"
STATUS = HC / "onboard_status.json"
LOG = HC / "watch.log"
POLL_SEC = 90
MIN_PERIODS = 8
REPORT_AT = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
SECTOR = "healthcare_large_cap"


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _catalog() -> list[dict]:
    payload = _load_json(CATALOG, {})
    return list(payload.get("companies") or [])


def _written_count(row: object) -> int:
    """Seed waves store periods_written as an int or a list of period ids."""
    if not isinstance(row, dict):
        return 0
    raw = row.get("periods_written", row.get("written", row.get("complete_periods")))
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return 0


def _seeded_tickers() -> set[str]:
    ready: set[str] = set()
    claimed: set[str] = set()
    for path in HC.glob("seed_wave_*.json"):
        payload = _load_json(path, {})
        tickers = payload.get("tickers") or payload.get("results") or []
        rows: list[tuple[str, dict]] = []
        if isinstance(tickers, dict):
            rows = [(str(key).upper(), row) for key, row in tickers.items() if isinstance(row, dict)]
        elif isinstance(tickers, list):
            for row in tickers:
                if isinstance(row, dict):
                    ticker = str(row.get("ticker") or "").upper()
                    if ticker:
                        rows.append((ticker, row))
        for ticker, row in rows:
            status = str(row.get("status") or "").lower()
            pending = row.get("pending_continuations") or row.get("pending_page2") or []
            if pending:
                continue
            if status in {"done", "complete", "completed"}:
                claimed.add(ticker)
    for ticker in claimed:
        if len(discover_on_disk_periods(REPO, ticker)) >= MIN_PERIODS:
            ready.add(ticker)
    return ready


def _already_done() -> set[str]:
    payload = _load_json(STATUS, {})
    done: set[str] = set()
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") in {"completed", "already_standard"}:
            done.add(str(row.get("ticker") or "").upper())
    return {t for t in done if t}


def _parked() -> set[str]:
    """Do not hammer Snowflake when the account requires a network policy.

    A status file with ``retry_snowflake=true`` unparks everyone so a recovered
    account can proceed without deleting history.
    """
    payload = _load_json(STATUS, {})
    retry_sf = bool(payload.get("retry_snowflake"))
    parked: set[str] = set()
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        err = str(row.get("error") or "")
        identity = (
            "Missing ESTPERMID/BARRA_ID" in err
            or "estpermid missing" in err.lower()
        )
        network = "Network policy is required" in err or "Failed to connect to DB" in err
        if identity or (network and not retry_sf):
            parked.add(str(row.get("ticker") or "").upper())
    return {t for t in parked if t}


def _append_status(row: dict) -> None:
    payload = _load_json(STATUS, {"results": []})
    results = list(payload.get("results") or [])
    results.append(row)
    STATUS.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "retry_snowflake": bool(payload.get("retry_snowflake")),
                "note": payload.get("note") or "",
                "results": results,
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    companies = _catalog()
    names = {str(c["ticker"]).upper(): str(c.get("name") or c["ticker"]) for c in companies}
    all_tickers = [str(c["ticker"]).upper() for c in companies]
    _log(f"watch start tickers={all_tickers}")
    idle_rounds = 0
    while True:
        try:
            done = _already_done()
            parked = _parked()
            ready = _seeded_tickers() - done - parked
        except Exception as exc:  # noqa: BLE001
            _log(f"seed-status parse failed: {exc}")
            time.sleep(POLL_SEC)
            continue
        pending = [t for t in all_tickers if t not in done]
        if not pending:
            _log("all tickers onboarded")
            return 0
        if not ready:
            idle_rounds += 1
            if idle_rounds % 10 == 1:
                _log(f"waiting for seed waves; done={sorted(done)} pending={pending}")
            time.sleep(POLL_SEC)
            continue
        idle_rounds = 0
        ticker = next(t for t in all_tickers if t in ready)
        on_disk = discover_on_disk_periods(REPO, ticker)
        if len(on_disk) < MIN_PERIODS:
            _log(f"{ticker}: listed ready but only {len(on_disk)} files; skip")
            time.sleep(POLL_SEC)
            continue
        latest = on_disk[-1]
        _log(f"{ticker}: starting onboard n={len(on_disk)} latest={latest}")
        try:
            result = run_onboard(
                repo_root=REPO,
                ticker=ticker,
                fiscal_period=latest,
                report_at=REPORT_AT,
                company_name=names.get(ticker, ticker),
                skip_pull=True,
                force_mode="onboard",
                skip_book_sync=True,
                research_sector=SECTOR,
                configured_tickers=all_tickers,
            )
            _append_status(result.to_dict())
            _log(f"{ticker}: {result.status} error={result.error}")
        except Exception as exc:  # noqa: BLE001 — keep the night running
            _append_status({"ticker": ticker, "status": "failed", "error": str(exc)})
            _log(f"{ticker}: watch exception {exc}")
            time.sleep(POLL_SEC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
