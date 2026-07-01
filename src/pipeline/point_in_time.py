from __future__ import annotations

from dataclasses import dataclass


class PointInTimeError(Exception):
    """Raised when point-in-time strict validation fails."""


@dataclass(frozen=True)
class PointInTimeConfig:
    strict: bool = False
    with_prices: bool = False
    unadjusted_prices: bool = False

    @classmethod
    def disabled(cls) -> PointInTimeConfig:
        return cls()

    @classmethod
    def document_only(cls) -> PointInTimeConfig:
        return cls(strict=True, with_prices=False)

    @classmethod
    def transcript_only(cls) -> PointInTimeConfig:
        return cls.document_only()

    @classmethod
    def with_prices(cls, *, unadjusted: bool = False) -> PointInTimeConfig:
        return cls(strict=True, with_prices=True, unadjusted_prices=unadjusted)

    @property
    def active(self) -> bool:
        return self.strict

    @property
    def include_prices(self) -> bool:
        return self.strict and self.with_prices
