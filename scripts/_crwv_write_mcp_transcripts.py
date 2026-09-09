"""Merge Quartr MCP full+Q&A windows into transcripts_raw for CRWV."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._write_quartr_mcp_transcript import paragraphs_to_text  # noqa: E402

AGENT = Path(
    r"C:\Users\BobbyWhittaker\.cursor\projects"
    r"\c-Users-BobbyWhittaker-OneDrive-Cassius-Capital-Desktop-Earnings-Call-Summarizer"
    r"\agent-tools"
)
OUT = ROOT / "Structured Narrative" / "transcripts_raw"

# (period, full_window, qna_window)
WINDOWS = [
    ("FY2025-Q1", "65cf5d53-ee2a-4e69-b5e8-1041f06efe9f.txt", "9a66c297-1ea8-4b9d-9d96-cbbc7b0a9a22.txt"),
    ("FY2025-Q2", "37c7ee6b-fda3-4329-acd2-6235d0270877.txt", "2b3c1c09-4ab7-4fe8-9e19-9fdfe1694fce.txt"),
    ("FY2025-Q3", "eb670d32-d58d-43a8-9b1b-b4cfe6a1f13a.txt", "16189b38-e694-4ec6-a357-ad75dfd5a5bf.txt"),
    ("FY2025-Q4", "26312d85-7aa8-4a2e-a8c3-6cdb108c34aa.txt", "2f8da52a-4bd1-4387-894b-928b87a178fd.txt"),
    ("FY2026-Q1", "bc600fd0-f22b-42de-bbab-35953b3fce15.txt", "a5fb3efd-0a6d-47a1-8f75-90529eb53370.txt"),
    ("FY2026-Q2", "fe6ff2a3-6e77-49c0-ac35-05f7c6b16e10.txt", "bc8a4a7e-a739-4cf4-91a3-c90c9a35760b.txt"),
]


def _load(name: str) -> dict:
    path = AGENT / name
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Not an object: {path}")
    return data


def _merge(full: dict, qna: dict) -> list[dict]:
    seen: set[object] = set()
    out: list[dict] = []
    for payload in (full, qna):
        for item in payload.get("paragraphs") or []:
            if not isinstance(item, dict):
                continue
            pid = item.get("paragraphId")
            key = pid if pid is not None else (item.get("start"), item.get("text"))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    out.sort(key=lambda p: (float(p.get("start") or 0), str(p.get("paragraphId") or "")))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for period, full_name, qna_name in WINDOWS:
        paras = _merge(_load(full_name), _load(qna_name))
        text = paragraphs_to_text(paras)
        dest = OUT / f"CRWV_{period}.txt"
        dest.write_text(text + "\n", encoding="utf-8")
        print(f"{dest.name}: {len(paras)} paragraphs, {dest.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
