import json
from pathlib import Path

p = Path("data/healthcare_large_cap/windows/PFE")
need = []
have = []
for d in sorted(p.iterdir()):
    j = json.loads((d / "000.json").read_text(encoding="utf-8"))
    nxt = j.get("nextFromTimestamp")
    has1 = (d / "001.json").exists()
    if nxt is not None and not has1:
        need.append(f"{d.name} {j.get('eventId')} {nxt}")
    elif nxt is not None and has1:
        have.append(d.name)
print("HAVE001", len(have), ",".join(have))
print("NEED", len(need))
print("\n".join(need))
