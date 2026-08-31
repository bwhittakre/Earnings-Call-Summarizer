#!/usr/bin/env python3
import json
from pathlib import Path

root = Path("data/healthcare_large_cap/windows/LLY")
for folder in sorted(p for p in root.iterdir() if p.is_dir()):
    wins = sorted(folder.glob("*.json"))
    nxt = None
    last_name = None
    if wins:
        last = json.loads(wins[-1].read_text(encoding="utf-8"))
        nxt = last.get("nextFromTimestamp")
        last_name = wins[-1].name
    print(f"{folder.name} windows={len(wins)} last={last_name} next={nxt}")
