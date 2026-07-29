"""Snowflake freshness abstraction without a hard connector dependency."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
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
