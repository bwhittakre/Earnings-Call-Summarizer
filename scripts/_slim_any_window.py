from pathlib import Path
import json, sys
src = Path(sys.argv[1])
ticker = sys.argv[2]
period = sys.argv[3]
idx = int(sys.argv[4])
data = json.loads(src.read_text(encoding="utf-8"))
paras = []
for item in data.get("paragraphs") or []:
    text = str(item.get("text") or "").strip()
    if not text:
        continue
    row = {"text": text}
    sp = str(item.get("speakerName") or item.get("speaker") or "").strip()
    if sp:
        row["speakerName"] = sp
    if item.get("start") is not None:
        row["start"] = item.get("start")
    paras.append(row)
dest_dir = Path("data/healthcare_large_cap/windows") / ticker / period
dest_dir.mkdir(parents=True, exist_ok=True)
dest = dest_dir / f"{idx:03d}.json"
payload = {"eventId": data.get("eventId"), "nextFromTimestamp": data.get("nextFromTimestamp"), "paragraphs": paras}
dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
print(f"WROTE={dest} paras={len(paras)}")
