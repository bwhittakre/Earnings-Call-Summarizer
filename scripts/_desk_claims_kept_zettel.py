"""File kept follow-up pairs into zettelkasten.

Copies excerpts from desk_claims_v1.json only. Does not read transcripts_raw.
Does not call create_extraction_graph. Does not dump the remaining 125.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS_PATH = (
    ROOT
    / "Structured Narrative"
    / "output"
    / "cross_company"
    / "json"
    / "desk_claims_v1.json"
)
SOURCE_MD = (
    ROOT
    / "Structured Narrative"
    / "output"
    / "cross_company"
    / "json"
    / "desk_claims_v1_kept_quotes.md"
)
LOCKED = "2026-08-17T17:28:40+00:00"
SPLIT = "asof-path-id-17aug-book-v1"
PILOT_GRAPH = "desk-path-id-v1-pilot"
KEPT_GRAPH = "desk-claims-v1-kept"
PILOT_DIR = ROOT / ".zettelkasten" / PILOT_GRAPH
KEPT_DIR = ROOT / ".zettelkasten" / KEPT_GRAPH


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _kept_rows(payload: dict) -> list[dict]:
    rows = []
    for row in payload.get("rows") or []:
        if row.get("state") != "kept":
            continue
        if not str(row.get("follow_up_excerpt") or "").strip():
            raise SystemExit(
                f"kept row missing follow-up: {row.get('ticker')} {row.get('period')}"
            )
        rows.append(row)
    if len(rows) != int((payload.get("counts") or {}).get("kept") or 0):
        raise SystemExit("kept-row count does not match payload counts.kept")
    return rows


def write_source_markdown(rows: list[dict]) -> Path:
    lines = [
        "# Claims desk v1 kept follow-up quotes",
        "",
        f"Copied from desk_claims_v1.json. Stamp {LOCKED}. Split {SPLIT}.",
        "Seed cite plus next-quarter follow-up for each kept pair.",
        "Not a transcript dump. Not the remaining 125.",
        "",
    ]
    for row in rows:
        lines.append(
            f"## {row['ticker']} {row['fiscal_period']} seed {row['beat_id']}"
        )
        lines.append("")
        lines.append(str(row["excerpt"]).strip())
        lines.append("")
        lines.append(
            f"## {row['ticker']} {row['next_fiscal_period']} follow-up {row['beat_id']}"
        )
        lines.append("")
        lines.append(str(row["follow_up_excerpt"]).strip())
        lines.append("")
    SOURCE_MD.write_text("\n".join(lines), encoding="utf-8")
    return SOURCE_MD


def _notes_in(graph: str, folder: Path) -> list[dict]:
    found = []
    if not folder.is_dir():
        return found
    for path in folder.glob("*.md"):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        note_id = ""
        aliases: list[str] = []
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            front = parts[1] if len(parts) > 2 else ""
            body = parts[2] if len(parts) > 2 else text
            id_match = re.search(r"^id:\s*(\S+)", front, re.M)
            if id_match:
                note_id = id_match.group(1)
            aliases = re.findall(r"-\s+(.+)", front)
        found.append(
            {
                "id": note_id or path.stem,
                "graph": graph,
                "aliases": [item.strip() for item in aliases],
                "body": _norm(body.split("_Reader note:")[0]),
            }
        )
    return found


def _existing_catalog() -> list[dict]:
    return _notes_in(PILOT_GRAPH, PILOT_DIR) + _notes_in(KEPT_GRAPH, KEPT_DIR)


def _match_existing(
    excerpt: str,
    catalog: list[dict],
    aliases: list[str] | None = None,
) -> dict | None:
    want_aliases = {_norm(item) for item in (aliases or []) if item}
    for note in catalog:
        note_aliases = {_norm(item) for item in note["aliases"]}
        if want_aliases and want_aliases & note_aliases:
            return note
    want = _norm(excerpt)
    if not want:
        return None
    for note in catalog:
        if want and want in note["body"]:
            return note
    return None


def _note_body(excerpt: str, citation: str, role: str, beat_id: str) -> str:
    return (
        f"{excerpt.strip()}\n\n"
        f"_Reader note: {role}. Citation: {citation}. "
        f"Beat {beat_id}. Split {SPLIT}. Status kept. "
        f"Path ID hit/miss is not the verdict._"
    )


def _ensure_note(
    add_note,
    *,
    graph: str,
    title: str,
    excerpt: str,
    citation: str,
    role: str,
    beat_id: str,
    ticker: str,
    alias: str,
    existing: dict | None,
) -> dict:
    if existing:
        return {
            "id": existing["id"],
            "graph": existing["graph"],
            "reused": True,
            "title": title,
        }
    result = add_note(
        graph=graph,
        title=title,
        type="quote",
        body=_note_body(excerpt, citation, role, beat_id),
        source_book="desk_claims_v1.json",
        source_chapter=citation,
        tags=[
            ticker.lower(),
            beat_id,
            "desk-claims-v1",
            "kept",
            role.replace(" ", "-"),
        ],
        aliases=[alias],
        epistemic_status="grounded",
    )
    if "error" in result:
        raise SystemExit(result)
    return {
        "id": result.get("id"),
        "graph": graph,
        "reused": False,
        "title": title,
    }


def main() -> None:
    os.environ.setdefault("ANGELO_WORKSPACE", str(ROOT))
    os.environ.setdefault("ZETTELKASTEN_PATH", str(ROOT / ".zettelkasten"))
    sys.path.insert(0, str(ROOT))

    payload = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    if str(payload.get("generated_at") or "") != LOCKED:
        raise SystemExit(f"claims stamp {payload.get('generated_at')!r} != {LOCKED!r}")
    rows = _kept_rows(payload)
    source_path = write_source_markdown(rows)

    from zettelkasten.server import (  # type: ignore
        add_note,
        add_to_project,
        create_project,
        create_source,
        ingest_source,
        link_notes,
    )

    ingested = json.loads(ingest_source(path=str(source_path)))
    if ingested.get("error"):
        raise SystemExit(ingested)
    created = json.loads(
        create_source(
            name=KEPT_GRAPH,
            doc_type="report",
            title="Claims desk v1 kept follow-up quotes",
            year=2026,
            abstract=(
                "Seed plus next-quarter follow-up excerpts for kept claims. "
                "Copied from desk_claims_v1.json. Not the remaining 125."
            ),
            content_hash=str(ingested.get("content_hash") or ""),
            source_path=str(source_path),
            date="2026-08-27",
            update=True,
        )
    )
    if created.get("error") and created.get("type") != "AlreadyExists":
        raise SystemExit(created)

    catalog = _existing_catalog()
    pairs = []
    for row in rows:
        ticker = str(row["ticker"])
        beat = str(row["beat_id"])
        seed_alias = f"{ticker} {row['period']} {row['fiscal_period']}"
        follow_alias = (
            f"{ticker} {row['next_fiscal_period']} "
            f"{row['follow_up_dimension']} kept-follow-up"
        )
        seed_existing = _match_existing(
            str(row["excerpt"]),
            catalog,
            aliases=[seed_alias, f"{seed_alias} kept-seed"],
        )
        follow_existing = _match_existing(
            str(row["follow_up_excerpt"]),
            catalog,
            aliases=[follow_alias],
        )
        seed = _ensure_note(
            add_note,
            graph=KEPT_GRAPH,
            title=f"{ticker} {row['fiscal_period']} {beat} — kept seed",
            excerpt=str(row["excerpt"]),
            citation=str(row["citation"]),
            role="kept seed",
            beat_id=beat,
            ticker=ticker,
            alias=f"{seed_alias} kept-seed",
            existing=seed_existing,
        )
        follow = _ensure_note(
            add_note,
            graph=KEPT_GRAPH,
            title=(
                f"{ticker} {row['next_fiscal_period']} {beat} — kept follow-up"
            ),
            excerpt=str(row["follow_up_excerpt"]),
            citation=str(row["follow_up_citation"]),
            role="kept follow-up",
            beat_id=beat,
            ticker=ticker,
            alias=follow_alias,
            existing=follow_existing,
        )
        if not follow_existing:
            catalog.append(
                {
                    "id": follow["id"],
                    "graph": follow["graph"],
                    "aliases": [],
                    "body": _norm(row["follow_up_excerpt"]),
                }
            )
        if not seed_existing:
            catalog.append(
                {
                    "id": seed["id"],
                    "graph": seed["graph"],
                    "aliases": [],
                    "body": _norm(row["excerpt"]),
                }
            )
        linked = json.loads(
            link_notes(
                graph=follow["graph"],
                source_id=str(follow["id"]),
                target_id=str(seed["id"]),
                relation="responds-to",
                direction="outgoing",
                target_graph="" if follow["graph"] == seed["graph"] else seed["graph"],
            )
        )
        if linked.get("error") and linked.get("type") != "AlreadyExists":
            raise SystemExit(linked)
        pairs.append(
            {
                "ticker": ticker,
                "beat": beat,
                "seed": seed,
                "follow": follow,
                "relation": "responds-to",
            }
        )

    tickers = sorted({row["ticker"] for row in rows})
    for ticker in tickers:
        name = f"company-{ticker.lower()}"
        proj = json.loads(
            create_project(
                name=name,
                description=f"{ticker} earnings cites. Claims desk kept pairs.",
                sources=[KEPT_GRAPH, PILOT_GRAPH],
            )
        )
        if proj.get("type") == "AlreadyExists":
            json.loads(add_to_project(project=name, source=KEPT_GRAPH))

    print(
        json.dumps(
            {
                "source": KEPT_GRAPH,
                "source_md": str(source_path),
                "n_pairs": len(pairs),
                "pairs": pairs,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
