"""Export the stratified 20k panel with ready-made persona profiles, so the service runs without the persona DB.

  ../.venv/bin/python scripts/export_panel_bundle.py   # needs the persona DB (external SSD)

Reads runs/series-housing/panel.json (province × age band × sex, population-proportional), fetches each
person's persona text from the DB, and writes engine/ppservice/data/panel-20k.jsonl.gz with
uuid, sex, age, age_band, province, capital, profile (pp.prompts.persona_profile, texts clipped to 300 chars).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pp import config, personas, prompts  # noqa: E402

PANEL = config.REPO_ROOT / "runs" / "series-housing" / "panel.json"
OUT = Path(__file__).resolve().parents[1] / "ppservice" / "data" / "panel-20k.jsonl.gz"
CAPITAL = {"서울", "인천", "경기"}


def main() -> int:
    saved = json.loads(PANEL.read_text(encoding="utf-8"))
    uuids = [p["uuid"] for p in saved["people"]]
    conn = personas.connect()
    rows = personas.fetch(conn, personas.ids_for_uuids(conn, uuids))
    by_uuid = {r["uuid"]: r for r in rows}
    missing = [u for u in uuids if u not in by_uuid]
    if missing:
        raise SystemExit(f"{len(missing)} panel people are not in the persona DB")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as f:
        for u in uuids:
            r = by_uuid[u]
            row = {"uuid": u, "sex": r["sex"], "age": int(r["age"]), "age_band": config.age_band(int(r["age"])),
                   "province": r["province"], "capital": r["province"] in CAPITAL,
                   "profile": prompts.persona_profile(r)}
            line = json.dumps(row, ensure_ascii=False, sort_keys=True)
            digest.update(line.encode("utf-8"))
            f.write(line + "\n")
    print(json.dumps({"out": str(OUT), "people": len(uuids), "bytes": OUT.stat().st_size,
                      "panel_version": digest.hexdigest()[:12], "seed": saved.get("seed")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
