#!/usr/bin/env python3
"""Run the pilot earnings extraction through the Cursor SDK driver.

The Cursor SDK agents do the grounded extraction; this script is the coordinator
glue: it builds the source documents, creates the projects, calls
``stream.api.apply`` per company with ``driver="cursor"`` (one long-lived bridge,
concurrency 1), joins each source to its quarter project, and archives the
processed originals.

Store pinning: the zettelkasten store lives at ``<repo>/.zettelkasten`` (see
.cursor/mcp.json). We set ANGELO_WORKSPACE / ZETTELKASTEN_PATH BEFORE importing
any angelo module, and pass the same env to the agent's angelo-zettelkasten MCP
subprocess, so this process, the executor, and the SDK agents all read/write the
SAME store.

Usage
-----
    source scripts/env_setup.sh        # optional (only for PYTHONPATH nicety)
    python scripts/run_extraction.py projects        # create the 5 projects
    python scripts/run_extraction.py smoke           # bridge + MCP connectivity
    python scripts/run_extraction.py extract --company all
    python scripts/run_extraction.py verify
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# --- pin the store BEFORE importing any angelo module ----------------------
os.environ.setdefault("ANGELO_WORKSPACE", str(REPO))
os.environ.setdefault("ZETTELKASTEN_PATH", str(REPO / ".zettelkasten"))
os.environ.setdefault("ANGELO_ZETTELKASTEN", "1")

INBOX = REPO / "inbox"
PROCESSED = INBOX / "_processed"
SCHEMA = "earnings-call"

# name -> source identity + routing. `name` becomes the zettelkasten source id.
PILOT = [
    {
        "name": "dow-inc-2025-q3",
        "file": "Dow-Inc-Q3-2025-Earnings-Call_Transcript_FINAL.pdf",
        "title": "Dow Inc. FQ3 2025 Earnings Call (Oct 23, 2025)",
        "company": "company-dow-inc",
        "quarter": "quarter-2025-q3",
    },
    {
        "name": "dow-inc-2025-q4",
        "file": "Dow-Inc-_4Q25-Earnings-Call_Transcript_FINAL.pdf",
        "title": "Dow Inc. FQ4 2025 Earnings Call (Jan 29, 2026)",
        "company": "company-dow-inc",
        "quarter": "quarter-2025-q4",
    },
    {
        "name": "home-depot-2025-q3",
        "file": "the-home-depot-inc-hd-us-q3-2025-earnings-call-v1.pdf",
        "title": "The Home Depot Q3 2025 Earnings Call (Nov 18, 2025)",
        "company": "company-home-depot",
        "quarter": "quarter-2025-q3",
    },
    {
        "name": "home-depot-2025-q4",
        "file": "hd-4q25-transcript.pdf",
        "title": "The Home Depot Q4 FY2025 Earnings Call (Feb 24, 2026)",
        "company": "company-home-depot",
        "quarter": "quarter-2025-q4",
    },
    {
        "name": "home-depot-2026-q1",
        "file": "hd-1q26-transcript.pdf",
        "title": "The Home Depot Q1 FY2026 Earnings Call (May 19, 2026)",
        "company": "company-home-depot",
        "quarter": "quarter-2026-q1",
    },
]

PROJECT_DESCRIPTIONS = {
    "company-dow-inc": (
        "Dow Inc. (NYSE:DOW) earnings calls, accumulated across quarters — a "
        "materials/chemicals bellwether. Tracks results, margins, guidance, demand "
        "environment, capital allocation, and management tone over time."
    ),
    "company-home-depot": (
        "The Home Depot, Inc. (NYSE:HD) earnings calls across fiscal quarters — "
        "home-improvement retail. Tracks comps, demand, guidance, margins, and tone."
    ),
    "quarter-2025-q3": "Cross-company snapshot of issuers reporting for Q3 2025.",
    "quarter-2025-q4": "Cross-company snapshot of issuers reporting for Q4 2025.",
    "quarter-2026-q1": (
        "Cross-company snapshot of issuers reporting for Q1 2026 "
        "(incl. fiscal-2026 reporters like Home Depot)."
    ),
}


def _companies(which: str) -> list[str]:
    if which == "dow":
        return ["company-dow-inc"]
    if which == "hd":
        return ["company-home-depot"]
    return ["company-dow-inc", "company-home-depot"]


def _rows_for(company: str) -> list[dict]:
    return [r for r in PILOT if r["company"] == company]


def _mcp_servers() -> dict:
    """angelo-zettelkasten MCP for the agents, pinned to the same store."""
    return {
        "angelo-zettelkasten": {
            "command": "angelo-zettelkasten",
            "env": {
                "ANGELO_WORKSPACE": str(REPO),
                "ZETTELKASTEN_PATH": str(REPO / ".zettelkasten"),
                "ANGELO_ZETTELKASTEN": "1",
            },
            "cwd": str(REPO),
        }
    }


def _make_driver(model: str = ""):
    from stream.drivers.cursor import CursorSdkDriver

    return CursorSdkDriver(model=model, workspace=str(REPO), mcp_servers=_mcp_servers())


def _documents(company: str):
    from stream.protocols import Document

    docs = []
    for r in _rows_for(company):
        path = INBOX / r["file"]
        if not path.is_file():
            path = PROCESSED / r["file"]
        if not path.is_file():
            raise FileNotFoundError(f"missing transcript: {r['file']}")
        docs.append(
            Document(name=r["name"], path=str(path), title=r["title"], doc_type="pdf")
        )
    return docs


def cmd_projects(_args) -> int:
    from zettelkasten import server as zk

    for name, desc in PROJECT_DESCRIPTIONS.items():
        raw = zk.create_project(name, description=desc, sources=[])
        res = json.loads(raw) if isinstance(raw, str) else raw
        if res.get("error") and res.get("type") != "AlreadyExists":
            print(f"  ! {name}: {res['error']}")
        else:
            print(f"  + {name}{' (exists)' if res.get('error') else ''}")
    return 0


def cmd_smoke(args) -> int:
    print("Constructing Cursor SDK driver (launches bridge on first turn)...")
    drv = _make_driver(args.model)
    try:
        res = drv.run_agent(
            role="checker",
            persona="You are a connectivity probe.",
            prompt="Reply with exactly the two characters: OK",
            tools=[],
        )
        print(f"ok={res.ok} tool_calls={getattr(res, 'tool_calls', '?')}")
        print(f"text: {res.text[:300]}")
        return 0 if res.ok else 1
    finally:
        drv.close()


def cmd_extract(args) -> int:
    from stream.api import apply

    PROCESSED.mkdir(parents=True, exist_ok=True)
    cmd_projects(args)  # idempotent

    drv = _make_driver(args.model)
    failures = 0
    try:
        for company in _companies(args.company):
            rows = _rows_for(company)
            docs = _documents(company)
            print(f"\n=== extract {company}: {len(docs)} source(s), schema={SCHEMA} ===")
            result = apply(
                docs,
                project=company,
                projects=[company],
                schemas=[SCHEMA],
                driver=drv,
                concurrency=1,
            )
            report = result.get("report", {})
            print(f"  run_id={result.get('run_id')}")
            print(f"  report: {json.dumps(report, default=str)[:600]}")

            # Join each source to its quarter project (extract-once, file-to-many).
            from zettelkasten import server as zk

            for r in rows:
                raw = zk.add_to_project(r["quarter"], r["name"])
                res = json.loads(raw) if isinstance(raw, str) else raw
                if res.get("error") and res.get("type") == "NotFound":
                    zk.create_project(
                        r["quarter"],
                        description=PROJECT_DESCRIPTIONS.get(r["quarter"], ""),
                        sources=[r["name"]],
                    )
                    print(f"  joined {r['name']} -> {r['quarter']} (created)")
                elif res.get("error"):
                    print(f"  ! join {r['name']} -> {r['quarter']}: {res['error']}")
                else:
                    print(f"  joined {r['name']} -> {r['quarter']}")

            # Archive processed originals for this company.
            for r in rows:
                src = INBOX / r["file"]
                if src.is_file():
                    shutil.move(str(src), str(PROCESSED / r["file"]))
                    print(f"  archived {r['file']}")
    finally:
        drv.close()
    return 1 if failures else 0


def cmd_dump(args) -> int:
    """Build the extraction graph for one company and print each task's model."""
    from collections import Counter

    from stream.templates import get_template

    company = _companies(args.company)[0]
    docs = _documents(company)
    spec = get_template("extraction").build(
        documents=docs, schemas=[SCHEMA], project=company, options=None
    )
    print(f"num_tasks={len(spec.tasks)}")
    print("MODELS:", dict(Counter(repr(t.get("model")) for t in spec.tasks)))
    print("AGENTS:", dict(Counter(t.get("agent") for t in spec.tasks)))
    for t in spec.tasks:
        if t.get("model"):
            print("  has-model:", t.get("agent"), "->", repr(t.get("model")))
    print("sample keys:", sorted(spec.tasks[0].keys()))
    return 0


def cmd_verify(_args) -> int:
    from zettelkasten import server as zk

    for name in PROJECT_DESCRIPTIONS:
        raw = zk.get_project(name) if hasattr(zk, "get_project") else None
        print(f"--- {name} ---")
        if raw is not None:
            res = json.loads(raw) if isinstance(raw, str) else raw
            print(json.dumps(res, default=str)[:500])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Pilot earnings extraction via Cursor SDK.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("projects", help="Create the pilot projects.")
    sp_smoke = sub.add_parser("smoke", help="Bridge + MCP connectivity check.")
    sp_smoke.add_argument("--model", default="")
    sp_ext = sub.add_parser("extract", help="Run extraction via the cursor driver.")
    sp_ext.add_argument("--company", choices=["dow", "hd", "all"], default="all")
    sp_ext.add_argument("--model", default="")
    sp_dump = sub.add_parser("dump", help="Print extraction graph task models (no run).")
    sp_dump.add_argument("--company", choices=["dow", "hd"], default="hd")
    sub.add_parser("verify", help="Print project membership.")

    args = ap.parse_args()
    return {
        "projects": cmd_projects,
        "smoke": cmd_smoke,
        "extract": cmd_extract,
        "dump": cmd_dump,
        "verify": cmd_verify,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
