"""Snowflake freshness abstraction without a hard connector dependency."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any


@dataclass(frozen=True)
class FreshnessResult:
    ticker: str
    fiscal_period: str
    is_fresh: bool
    as_of: datetime | None = None
    detail: str = ""


class FreshnessProbe(ABC):
    @abstractmethod
    def check(self, ticker: str, fiscal_period: str) -> FreshnessResult:
        """Check whether required point-in-time data is ready."""


class AlwaysFreshProbe(FreshnessProbe):
    def check(self, ticker: str, fiscal_period: str) -> FreshnessResult:
        return FreshnessResult(ticker.upper(), fiscal_period, True, detail="freshness check disabled")


class SnowflakeFreshnessProbe(FreshnessProbe):
    """Calls an injected query function; no Snowflake package is imported."""

    def __init__(
        self,
        query: Callable[[str, Mapping[str, Any]], Mapping[str, Any] | None],
        *,
        sql: str | None = None,
    ):
        self.query = query
        self.sql = sql or (
            "SELECT is_fresh, as_of, detail FROM earnings_data_freshness "
            "WHERE ticker=%(ticker)s AND fiscal_period=%(fiscal_period)s"
        )

    def check(self, ticker: str, fiscal_period: str) -> FreshnessResult:
        symbol = ticker.upper()
        row = self.query(self.sql, {"ticker": symbol, "fiscal_period": fiscal_period})
        if not row:
            return FreshnessResult(symbol, fiscal_period, False, detail="no freshness row")
        raw_as_of = row.get("as_of")
        as_of: datetime | None
        if isinstance(raw_as_of, datetime):
            as_of = raw_as_of
        elif raw_as_of:
            as_of = datetime.fromisoformat(str(raw_as_of).replace("Z", "+00:00"))
        else:
            as_of = None
        if as_of and as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return FreshnessResult(
            symbol,
            fiscal_period,
            bool(row.get("is_fresh")),
            as_of=as_of,
            detail=str(row.get("detail") or ""),
        )


class StructuredNarrativeFreshnessProbe(FreshnessProbe):
    """Check the existing Structured Narrative Snowflake source for release data."""

    REQUIRED_ACTUAL_MEASURES = frozenset({9, 20})  # EPS and Sales

    def __init__(self, repo_root: Path | str):
        self.structured_narrative_dir = Path(repo_root) / "Structured Narrative"

    def available(self) -> tuple[bool, str]:
        sn_path = str(self.structured_narrative_dir)
        if sn_path not in sys.path:
            sys.path.insert(0, sn_path)
        try:
            from single_company_extractor import connect

            connection = connect()
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                cursor.close()
                connection.close()
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return True, "Structured Narrative Snowflake connection available"

    def check(self, ticker: str, fiscal_period: str) -> FreshnessResult:
        symbol = ticker.upper()
        sn_path = str(self.structured_narrative_dir)
        if sn_path not in sys.path:
            sys.path.insert(0, sn_path)
        try:
            from company_config import get_company, resolve_company_ids
            from fiscal_period_util import company_fiscal_period
            from single_company_extractor import connect, resolve_dbs

            connection = connect()
            cursor = connection.cursor()
            try:
                company = resolve_company_ids(cursor, get_company(symbol))
                lseg, _ = resolve_dbs(cursor)
                measures = sorted(self.REQUIRED_ACTUAL_MEASURES)
                placeholders = ",".join("%s" for _ in measures)
                cursor.execute(
                    f"""
                    SELECT PERENDDATE, MEASURE, MAX(EFFECTIVEDATE) AS AS_OF
                    FROM "{lseg}".DBO.TREACTRPT
                    WHERE ESTPERMID=%s
                      AND PERTYPE=3
                      AND MEASURE IN ({placeholders})
                      AND ANNOUNCEDATE IS NOT NULL
                      AND EFFECTIVEDATE <= CURRENT_TIMESTAMP()
                      AND PERENDDATE >= DATEADD(year, -2, CURRENT_DATE())
                    GROUP BY PERENDDATE, MEASURE
                    """,
                    (company.estpermid, *measures),
                )
                matches = [
                    row
                    for row in cursor.fetchall()
                    if company_fiscal_period(symbol, row[0]).upper()
                    == fiscal_period.upper()
                ]
            finally:
                cursor.close()
                connection.close()
        except Exception as exc:
            return FreshnessResult(
                symbol,
                fiscal_period,
                False,
                detail=f"Snowflake freshness check failed: {type(exc).__name__}: {exc}",
            )

        available = {int(row[1]) for row in matches}
        as_of_values = [row[2] for row in matches if isinstance(row[2], datetime)]
        as_of = max(as_of_values) if as_of_values else None
        if as_of and as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        missing = sorted(self.REQUIRED_ACTUAL_MEASURES - available)
        return FreshnessResult(
            symbol,
            fiscal_period,
            not missing,
            as_of=as_of,
            detail=(
                "required Sales/EPS actuals available"
                if not missing
                else f"waiting for actual measure codes {missing}"
            ),
        )
