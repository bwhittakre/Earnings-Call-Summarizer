from __future__ import annotations

from pathlib import Path

from services.earnings_monitor import book_ranks as book_ranks_mod


def test_load_production_v1_pack():
    # Import from Structured Narrative on sys.path via package-relative path.
    import sys

    sn = Path(__file__).resolve().parents[1] / "Structured Narrative"
    sys.path.insert(0, str(sn))
    from signal_pack import FALLBACK_HYPOTHESES, load_signal_pack  # noqa: E402

    pack = load_signal_pack(sn.parent / "config" / "signal_packs" / "production_v1.yaml")
    assert pack.pack_id == "production_v1"
    assert pack.min_names == 3
    assert len(pack.hypotheses) == 4
    assert pack.hypotheses[0]["signal"] == "quant_z_pit"
    assert pack.hypotheses[0]["dimension"] == "demand"
    assert {(h["signal"], h["dimension"]) for h in pack.hypotheses} == {
        (h["signal"], h["dimension"]) for h in FALLBACK_HYPOTHESES
    }


def test_evaluate_primary_hypotheses_come_from_pack():
    import sys

    sn = Path(__file__).resolve().parents[1] / "Structured Narrative"
    sys.path.insert(0, str(sn))
    import evaluate_narrative_signals as ens  # noqa: E402

    assert ens.SIGNAL_PACK_ID == "production_v1"
    assert len(ens.PRIMARY_HYPOTHESES) == 4
    assert ens.is_primary_hypothesis("agrees_with_quant", "guidance")
    assert not ens.is_primary_hypothesis("llm_level", "demand")


def test_book_ranks_command_includes_trigger(tmp_path: Path):
    from services.earnings_monitor.config import MonitorConfig

    config = MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        inbox_path=tmp_path / "inbox",
        tickers=("MSFT", "AAPL"),
    )
    (tmp_path / "Structured Narrative").mkdir()
    cmd = book_ranks_mod.build_book_ranks_command(
        config,
        trigger_ticker="msft",
        trigger_period="fy2026-q2",
    )
    assert "build_book_ranks.py" in cmd[1]
    assert "MSFT" in cmd and "AAPL" in cmd
    assert cmd[cmd.index("--mode") + 1] == "investable_asof"
    assert cmd[cmd.index("--trigger-ticker") + 1] == "MSFT"
    assert cmd[cmd.index("--trigger-period") + 1] == "FY2026-Q2"


def test_pending_investable_ranks_due(tmp_path: Path):
    from datetime import datetime, timezone

    from services.earnings_monitor import book_ranks as book_ranks_mod
    from services.earnings_monitor.config import MonitorConfig

    config = MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "db.sqlite3",
        inbox_path=tmp_path / "inbox",
    )
    summary = (
        tmp_path
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "book_ranks_summary.json"
    )
    summary.parent.mkdir(parents=True)
    summary.write_text(
        '{"skipped_reason":"awaiting_investable_asof","as_of_date":"2026-08-01",'
        '"period_bucket":"2026-Q2","trigger_ticker":"MSFT","trigger_period":"FY2026-Q2"}\n',
        encoding="utf-8",
    )
    due = book_ranks_mod.pending_investable_ranks_due(
        config,
        now=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    assert due is not None
    assert due["as_of_date"] == "2026-08-01"
    not_due = book_ranks_mod.pending_investable_ranks_due(
        config,
        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert not_due is None
