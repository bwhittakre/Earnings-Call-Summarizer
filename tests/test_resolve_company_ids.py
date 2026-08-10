"""Unit tests for ISIN-first Snowflake / LSEG identity resolution."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
SN = REPO / "Structured Narrative"
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from company_config import CompanyProfile, resolve_company_ids  # noqa: E402


class _FakeCursor:
    def __init__(self, *, iris=None, lseg=None):
        self._iris = iris or {}
        self._lseg = lseg or {}
        self.calls: list[str] = []

    def execute(self, sql, params=None):
        self.calls.append(sql)
        self._last_sql = sql
        self._last_params = params

    def fetchall(self):
        if "show databases" in self._last_sql.lower():
            return [(0, "IRIS_TEST"), (0, "LSEG_FOO_A822_BAR"), (0, "MSCI_FOO")]
        return []

    def fetchone(self):
        sql = self._last_sql.upper()
        if "IRIS_UNIV" in sql:
            return self._iris.get("row")
        if "PERMISINDATA" in sql:
            return self._lseg.get("instr")
        if "VW_IBES2MAPPING" in sql and "INSTRPERMID" in sql:
            return self._lseg.get("map_by_instr")
        if "VW_IBES2MAPPING" in sql:
            return self._lseg.get("map_by_ticker")
        if "ASSET_UNIVERSE_TS" in sql:
            return self._lseg.get("barra")
        return None

    @property
    def description(self):
        if "IRIS_UNIV" in getattr(self, "_last_sql", "").upper():
            return [("ticker",), ("estpermid",), ("isin",), ("barra_id",)]
        return []


def test_resolve_isin_first_ignores_conflicting_iris_estpermid():
    """IRIS must not override an ISIN-resolved ESTPERMID (STRW recycle case)."""
    cur = _FakeCursor(
        iris={"row": ("STRW", 111111, "US0000000000", "USWRONG1")},
        lseg={
            "instr": (999,),
            "map_by_instr": (30064884718, "04Y9"),
            "barra": ("USBOFP1", 12),
        },
    )
    profile = CompanyProfile(
        ticker="STRW",
        company_name="Strawberry Fields",
        isin="US8631821019",
    )
    resolved = resolve_company_ids(cur, profile)
    assert resolved.estpermid == 30064884718
    assert resolved.isin == "US8631821019"
    assert resolved.barra_id == "USBOFP1"
    assert any("PERMISINDATA" in c.upper() for c in cur.calls)


def test_resolve_without_isin_uses_iris_then_lseg_ticker():
    cur = _FakeCursor(
        iris={},
        lseg={"map_by_ticker": (42, "CSCO")},
    )
    profile = CompanyProfile(ticker="CSCO", company_name="Cisco")
    resolved = resolve_company_ids(cur, profile)
    assert resolved.estpermid == 42


def test_resolve_isin_path_can_enrich_barra_from_iris_only():
    cur = _FakeCursor(
        iris={"row": ("CSCO", 999999, "US17275R1023", "USACX21")},
        lseg={
            "instr": (1,),
            "map_by_instr": (55, "CSCO"),
            # no barra from MSCI
        },
    )
    profile = CompanyProfile(
        ticker="CSCO",
        company_name="Cisco",
        isin="US17275R1023",
    )
    resolved = resolve_company_ids(cur, profile)
    assert resolved.estpermid == 55  # LSEG wins, not IRIS 999999
    assert resolved.barra_id == "USACX21"  # IRIS enrich only
