"""File desk v2 trees into zettelkasten.

Copies excerpts from desk_trees_v2.json only. Does not read transcripts_raw.
Does not call create_extraction_graph. Does not dump the remaining 125.
Quote bodies must not use a '>' prefix.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TREES_PATH = (
    ROOT
    / "Structured Narrative"
    / "output"
    / "cross_company"
    / "json"
    / "desk_trees_v2.json"
)
SOURCE_MD = (
    ROOT
    / "Structured Narrative"
    / "output"
    / "cross_company"
    / "json"
    / "desk_trees_v2_nvda_quotes.md"
)
NVDA_STAMP = "2026-08-27T18:02:00+00:00"
V1_STAMP = "2026-08-17T17:28:40+00:00"
SPLIT = "nvda-gold-20q-fy2022q2-fy2027q1"
GRAPH = "desk-trees-v2-nvda"
GRAPH_DIR = ROOT / ".zettelkasten" / GRAPH
FORBIDDEN = ("transcripts_raw", "create_extraction_graph")


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:48] or "note"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def refuse_payload(payload: dict) -> None:
    stamp = str(payload.get("generated_at") or "")
    if stamp == V1_STAMP or stamp != NVDA_STAMP:
        raise SystemExit(f"zettel refuses stamp {stamp!r}; need {NVDA_STAMP!r}")
    blob = json.dumps(payload)
    if "transcripts_raw" in blob:
        raise SystemExit("zettel refuses transcripts_raw")


def write_source_markdown(trees: list[dict]) -> Path:
    lines = [
        "# Claims desk v2 NVIDIA gold quotes",
        "",
        f"Copied from desk_trees_v2.json. Stamp {NVDA_STAMP}. Split {SPLIT}.",
        "One seed plus later cites per tree. Not a transcript dump.",
        "Not the leftover Path ID rows. Path ID is not the verdict.",
        "",
    ]
    for tree in trees:
        seed = tree.get("seed") or {}
        lines.append(f"## {tree['tree_id']} seed {seed.get('fiscal_period')}")
        lines.append("")
        excerpt = str(seed.get("excerpt") or "").strip()
        if excerpt.startswith(">"):
            raise SystemExit(f"{tree['tree_id']} seed uses forbidden '>' prefix")
        lines.append(excerpt)
        lines.append("")
        for node in tree.get("nodes") or []:
            if str(node.get("edge") or "") == "silent":
                continue
            node_excerpt = str(node.get("excerpt") or "").strip()
            if not node_excerpt:
                continue
            if node_excerpt.startswith(">"):
                raise SystemExit(
                    f"{tree['tree_id']} {node.get('fiscal_period')} uses '>' prefix"
                )
            lines.append(
                f"## {tree['tree_id']} {node.get('fiscal_period')} {node.get('edge')}"
            )
            lines.append("")
            lines.append(node_excerpt)
            lines.append("")
    text = "\n".join(lines)
    for token in FORBIDDEN:
        if token in text:
            raise SystemExit(f"source markdown contains forbidden {token!r}")
    SOURCE_MD.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_MD.write_text(text, encoding="utf-8")
    return SOURCE_MD


def _note_markdown(
    *,
    note_id: str,
    title: str,
    excerpt: str,
    citation: str,
    tags: list[str],
    aliases: list[str],
    links: list[dict[str, str]],
    role: str,
    tree_id: str,
    kind: str,
) -> str:
    if excerpt.startswith(">"):
        raise SystemExit(f"{note_id} body uses forbidden '>' prefix")
    tag_lines = "\n".join(f"- {tag}" for tag in tags)
    alias_lines = "\n".join(f"- {alias}" for alias in aliases)
    link_blocks = []
    for link in links:
        link_blocks.append(
            "- target: "
            f"{link['target']}\n"
            f"  relation: {link['relation']}\n"
            f"  direction: outgoing"
        )
    links_yaml = "\n".join(link_blocks) if link_blocks else ""
    front = [
        "---",
        f"id: {note_id}",
        f'title: "{title}"',
        "type: quote",
        "source:",
        "  book: desk_trees_v2.json",
        f"  chapter: {citation}",
        "tags:",
        tag_lines,
    ]
    if links_yaml:
        front.extend(["links:", links_yaml])
    front.extend(
        [
            "aliases:",
            alias_lines,
            "grounding:",
            "  verified: true",
            "  method: exact",
            "  score: 1.0",
            "epistemic_status: grounded",
            "---",
            "",
            f"# {title}",
            "",
            excerpt,
            "",
            f"_Reader note: {role}. Citation: {citation}. "
            f"Tree {tree_id}. Kind {kind}. Split {SPLIT}. "
            "Path ID hit/miss is not the verdict._",
            "",
        ]
    )
    return "\n".join(front)


def _claim_markdown(
    *,
    note_id: str,
    title: str,
    body: str,
    tags: list[str],
    supports: list[str],
) -> str:
    tag_lines = "\n".join(f"- {tag}" for tag in tags)
    links = "\n".join(
        f"- target: {item}\n  relation: supports\n  direction: outgoing"
        for item in supports
    )
    return "\n".join(
        [
            "---",
            f"id: {note_id}",
            f'title: "{title}"',
            "type: claim",
            "source:",
            "  book: desk_trees_v2.json",
            "tags:",
            tag_lines,
            "links:",
            links,
            "epistemic_status: grounded",
            "---",
            "",
            f"# {title}",
            "",
            body,
            "",
            f"_Reader note: scored terminal. Split {SPLIT}. "
            "Open / unresolved trees have no claim._",
            "",
        ]
    )


def _spine_markdown(
    *,
    note_id: str,
    title: str,
    tree: dict,
    ordered_ids: list[str],
) -> str:
    items = "\n".join(f"- {item}" for item in ordered_ids)
    return "\n".join(
        [
            "---",
            f"id: {note_id}",
            f'title: "{title}"',
            "type: index",
            "source:",
            "  book: desk_trees_v2.json",
            "tags:",
            f"- {str(tree.get('ticker') or '').lower()}",
            f"- {tree.get('beat_id')}",
            f"- {tree.get('kind')}",
            "- desk-trees-v2",
            "- spine",
            "prerequisites:",
            items,
            "epistemic_status: grounded",
            "---",
            "",
            f"# {title}",
            "",
            f"Lineage for {tree.get('tree_id')}. Fiscal order. "
            "Silent quarters have no quote note.",
            "",
            items,
            "",
        ]
    )


def file_tree(tree: dict, existing: dict[str, str]) -> dict[str, object]:
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    ticker = str(tree.get("ticker") or "").lower()
    kind = str(tree.get("kind") or "")
    beat = str(tree.get("beat_id") or "")
    tree_id = str(tree.get("tree_id") or "")
    seed = tree.get("seed") or {}
    notes = []
    prior_id = None
    seed_id = f"20260827-{_slug(tree_id)}-seed"
    seed_excerpt = str(seed.get("excerpt") or "").strip()
    reused = existing.get(_norm(seed_excerpt))
    if reused:
        seed_id = reused
        notes.append({"id": seed_id, "reused": True, "role": "seed"})
    else:
        path = GRAPH_DIR / f"{seed_id}.md"
        path.write_text(
            _note_markdown(
                note_id=seed_id,
                title=f"{tree['ticker']} {seed.get('fiscal_period')} {beat} — seed",
                excerpt=seed_excerpt,
                citation=str(seed.get("citation") or ""),
                tags=[ticker, beat, kind, "desk-trees-v2", "seed"],
                aliases=[f"{tree['ticker']} {seed.get('fiscal_period')} {tree_id} seed"],
                links=[],
                role="tree seed",
                tree_id=tree_id,
                kind=kind,
            ),
            encoding="utf-8",
        )
        existing[_norm(seed_excerpt)] = seed_id
        notes.append({"id": seed_id, "reused": False, "role": "seed"})
    prior_id = seed_id
    ordered = [seed_id]
    for node in tree.get("nodes") or []:
        edge = str(node.get("edge") or "")
        if edge == "silent":
            continue
        excerpt = str(node.get("excerpt") or "").strip()
        if not excerpt:
            continue
        note_id = f"20260827-{_slug(tree_id)}-{_slug(str(node.get('fiscal_period')))}-{_slug(edge)}"
        reused = existing.get(_norm(excerpt))
        relation = edge if edge != "restated" else "responds-to"
        if reused:
            note_id = reused
            notes.append({"id": note_id, "reused": True, "role": edge})
        else:
            path = GRAPH_DIR / f"{note_id}.md"
            path.write_text(
                _note_markdown(
                    note_id=note_id,
                    title=(
                        f"{tree['ticker']} {node.get('fiscal_period')} "
                        f"{beat} — {edge}"
                    ),
                    excerpt=excerpt,
                    citation=str(node.get("citation") or ""),
                    tags=[ticker, beat, kind, "desk-trees-v2", edge],
                    aliases=[
                        f"{tree['ticker']} {node.get('fiscal_period')} "
                        f"{tree_id} {edge}"
                    ],
                    links=(
                        [{"target": prior_id, "relation": relation}]
                        if prior_id
                        else []
                    ),
                    role=f"{edge} cite",
                    tree_id=tree_id,
                    kind=kind,
                ),
                encoding="utf-8",
            )
            existing[_norm(excerpt)] = note_id
            notes.append({"id": note_id, "reused": False, "role": edge})
        prior_id = note_id
        ordered.append(note_id)

    spine_id = f"20260827-{_slug(tree_id)}-spine"
    (GRAPH_DIR / f"{spine_id}.md").write_text(
        _spine_markdown(
            note_id=spine_id,
            title=str(tree.get("title") or tree_id),
            tree=tree,
            ordered_ids=ordered,
        ),
        encoding="utf-8",
    )

    claim = None
    scored = None
    if kind == "promise" and tree.get("delivery") in {"delivered", "missed"}:
        scored = tree.get("delivery")
    if kind == "goal" and tree.get("goal_outcome") in {"hit", "missed"}:
        scored = tree.get("goal_outcome")
    if scored:
        claim_id = f"20260827-{_slug(tree_id)}-claim-{scored}"
        (GRAPH_DIR / f"{claim_id}.md").write_text(
            _claim_markdown(
                note_id=claim_id,
                title=f"{tree.get('title')} — {scored}",
                body=(
                    f"{tree.get('coverage_summary') or scored}. "
                    f"Seed {seed.get('citation')}. Terminal {ordered[-1]}."
                ),
                tags=[ticker, beat, kind, "desk-trees-v2", str(scored)],
                supports=[ordered[0], ordered[-1]],
            ),
            encoding="utf-8",
        )
        claim = claim_id
    return {
        "tree_id": tree_id,
        "notes": notes,
        "spine": spine_id,
        "claim": claim,
    }


def main() -> int:
    payload = json.loads(TREES_PATH.read_text(encoding="utf-8"))
    refuse_payload(payload)
    trees = [tree for tree in (payload.get("trees") or []) if isinstance(tree, dict)]
    write_source_markdown(trees)
    existing: dict[str, str] = {}
    filed = [file_tree(tree, existing) for tree in trees]
    print(
        json.dumps(
            {
                "graph": GRAPH,
                "source_md": str(SOURCE_MD),
                "n_trees": len(filed),
                "n_claims": sum(1 for item in filed if item["claim"]),
                "trees": filed,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
