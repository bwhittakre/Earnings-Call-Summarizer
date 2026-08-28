"""File grounded-desk Phase 2 pilot notes into the local zettelkasten.

Copies excerpts from desk_path_id_v1.json only. Does not read transcripts_raw.
Does not call create_extraction_graph. Does not rewrite path_id_v1.json.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESK_PATH = ROOT / "Structured Narrative" / "output" / "cross_company" / "json" / "desk_path_id_v1.json"
SOURCE_MD = ROOT / "Structured Narrative" / "output" / "cross_company" / "json" / "desk_path_id_v1_pilot_quotes.md"
LOCKED = "2026-08-17T17:28:40+00:00"
SPLIT = "asof-path-id-17aug-book-v1"
SOURCE_NAME = "desk-path-id-v1-pilot"

PILOT_KEYS = (
    ("ADBE", "2021-Q2"),
    ("ADSK", "2021-Q2"),
    ("CRM", "2021-Q2"),
    ("IBM", "2021-Q2"),
    ("INTU", "2021-Q2"),
    ("MSFT", "2021-Q2"),
    ("ORCL", "2021-Q2"),
    ("MSFT", "2022-Q4"),
    ("MSFT", "2023-Q1"),
    ("ADBE", "2023-Q2"),
    ("IBM", "2023-Q2"),
    ("ADSK", "2023-Q3"),
    ("CRM", "2025-Q1"),
    ("ORCL", "2025-Q1"),
    ("ADSK", "2026-Q1"),
)


def _rows() -> list[dict]:
    payload = json.loads(DESK_PATH.read_text(encoding="utf-8"))
    if str(payload.get("generated_at") or "") != LOCKED:
        raise SystemExit(f"desk stamp {payload.get('generated_at')!r} != {LOCKED!r}")
    want = set(PILOT_KEYS)
    found = []
    for row in payload.get("rows") or []:
        key = (str(row.get("ticker") or ""), str(row.get("period") or ""))
        if key in want:
            found.append(row)
    if len(found) != len(PILOT_KEYS):
        raise SystemExit(f"expected {len(PILOT_KEYS)} pilot rows, found {len(found)}")
    order = {key: i for i, key in enumerate(PILOT_KEYS)}
    found.sort(key=lambda r: order[(r["ticker"], r["period"])])
    return found


def write_source_markdown(rows: list[dict]) -> Path:
    lines = [
        "# Desk Path ID v1 pilot quotes",
        "",
        f"Copied from desk_path_id_v1.json. Stamp {LOCKED}. Split {SPLIT}.",
        "Not a transcript dump. Each excerpt below is the verified novelty_view cite.",
        "",
    ]
    for row in rows:
        lines.append(
            f"## {row['ticker']} {row['period']} {row['fiscal_period']}"
        )
        lines.append("")
        lines.append(str(row["excerpt"]))
        lines.append("")
    SOURCE_MD.write_text("\n".join(lines), encoding="utf-8")
    return SOURCE_MD


def _note_body(row: dict) -> str:
    excerpt = str(row["excerpt"]).strip()
    hit = "hit" if row.get("hit") else "miss"
    return (
        f"{excerpt}\n\n"
        f"_Reader note: Claim: {row.get('claim')}. "
        f"Citation: {row.get('source')}. "
        f"Path metadata (not the claim): predicted {row.get('predicted')} "
        f"→ realized {row.get('realized')} ({hit}). "
        f"Novelty magnitude {row.get('novelty_magnitude')}. "
        f"Split {SPLIT}._"
    )


def main() -> None:
    os.environ.setdefault("ANGELO_WORKSPACE", str(ROOT))
    os.environ.setdefault("ZETTELKASTEN_PATH", str(ROOT / ".zettelkasten"))
    sys.path.insert(0, str(ROOT))

    rows = _rows()
    source_path = write_source_markdown(rows)

    from zettelkasten.server import (  # type: ignore
        add_note,
        add_to_project,
        create_project,
        create_source,
        ingest_source,
    )

    ingested = json.loads(
        ingest_source(path=str(source_path))
    )
    if ingested.get("error"):
        raise SystemExit(ingested)
    created = json.loads(
        create_source(
            name=SOURCE_NAME,
            doc_type="report",
            title="Desk Path ID v1 pilot quotes",
            year=2026,
            abstract=(
                "Verified competitive_position excerpts for the 15-row grounded-desk "
                "Phase 2 pilot. Copied from desk_path_id_v1.json."
            ),
            content_hash=str(ingested.get("content_hash") or ""),
            source_path=str(source_path),
            date="2026-08-26",
            update=True,
        )
    )
    if created.get("error") and created.get("type") != "AlreadyExists":
        raise SystemExit(created)

    created_notes = []
    for row in rows:
        title = (
            f"{row['ticker']} {row['fiscal_period']} competitive_position — "
            f"{str(row.get('claim') or '')[:72]}"
        )
        queue = "first-print" if row["period"] == "2021-Q2" else "high-novelty-miss"
        result = add_note(
            graph=SOURCE_NAME,
            title=title,
            type="quote",
            body=_note_body(row),
            source_book="desk_path_id_v1.json",
            source_chapter=f"{row['ticker']} {row['fiscal_period']}",
            tags=[
                str(row["ticker"]).lower(),
                "competitive_position",
                "desk-path-id-v1",
                queue,
            ],
            aliases=[f"{row['ticker']} {row['period']} {row['fiscal_period']}"],
            epistemic_status="grounded",
        )
        if "error" in result:
            raise SystemExit(result)
        created_notes.append(
            {
                "id": result.get("id"),
                "title": title,
                "ticker": row["ticker"],
                "period": row["period"],
            }
        )

    tickers = sorted({row["ticker"] for row in rows})
    projects = []
    for ticker in tickers:
        name = f"company-{ticker.lower()}"
        proj = json.loads(
            create_project(
                name=name,
                description=f"{ticker} earnings cites. Desk Phase 2 pilot source only.",
                sources=[SOURCE_NAME],
            )
        )
        if proj.get("type") == "AlreadyExists":
            added = json.loads(add_to_project(project=name, source=SOURCE_NAME))
            proj = {"name": name, "reused": True, "add": added}
        projects.append(proj)

    print(
        json.dumps(
            {
                "source": SOURCE_NAME,
                "source_md": str(source_path),
                "ingested": {
                    "content_hash": ingested.get("content_hash"),
                    "existing_source": ingested.get("existing_source"),
                },
                "notes": created_notes,
                "projects": [p.get("name") for p in projects],
                "n_notes": len(created_notes),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
