import json
from pathlib import Path

p = Path("data/healthcare_large_cap/windows/AMGN")
need = []
have = []
single = []
for d in sorted(p.iterdir()):
    if not d.is_dir():
        continue
    files = sorted(d.glob("*.json"))
    if not files:
        continue
    last = files[-1]
    j = json.loads(last.read_text(encoding="utf-8"))
    nxt = j.get("nextFromTimestamp")
    eid = j.get("eventId")
    nparas = len(j.get("paragraphs") or [])
    if nxt is None:
        if last.name == "000.json":
            single.append(d.name)
        else:
            have.append("%s last=%s" % (d.name, last.name))
    else:
        need.append("%s last=%s eventId=%s next=%s paras=%s" % (d.name, last.name, eid, nxt, nparas))
print("COMPLETE_SINGLE", len(single))
print(",".join(single))
print("COMPLETE_MULTI", len(have))
print("\n".join(have))
print("NEED_MORE", len(need))
print("\n".join(need))
