"""Zettel filer guards. Does not talk to MCP."""
from __future__ import annotations

import pytest

from scripts._desk_trees_zettel import refuse_payload, write_source_markdown


def test_zettel_refuses_v1_stamp() -> None:
    with pytest.raises(SystemExit, match="zettel refuses stamp"):
        refuse_payload({"generated_at": "2026-08-17T17:28:40+00:00", "trees": []})


def test_zettel_refuses_blockquote_prefix(tmp_path, monkeypatch) -> None:
    from scripts import _desk_trees_zettel as mod

    monkeypatch.setattr(mod, "SOURCE_MD", tmp_path / "quotes.md")
    with pytest.raises(SystemExit, match="forbidden '>' prefix"):
        write_source_markdown(
            [
                {
                    "tree_id": "bad",
                    "seed": {"fiscal_period": "FY2025-Q1", "excerpt": "> quoted"},
                    "nodes": [],
                }
            ]
        )
