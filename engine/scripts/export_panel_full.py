"""Export every original Nemotron-Personas-Korea field, unclipped, for the 20k panel people.

  ../.venv/bin/python scripts/export_panel_full.py   # needs the persona DB (external SSD)

The service reads only panel-20k.jsonl.gz (basic attributes plus four persona texts clipped to 300 chars). This file
keeps the same people in the same order with all source columns, so the panel can be inspected or rebuilt without the
1M-person database. Writes engine/ppservice/data/panel-20k-full.jsonl.xz (xz: about 11 MB against 25 MB as gzip,
so the public GitLab takes it in three 4 MB parts; read it with Python's lzma module or `xz -dc`).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import lzma
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pp import attribution, config, personas, provenance  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "ppservice" / "data"
PANEL = DATA / "panel-20k.jsonl.gz"
OUT = DATA / "panel-20k-full.jsonl.xz"
FULL_SQL = "SELECT * FROM persona WHERE uuid IN (SELECT value FROM json_each(?))"


def main() -> int:
    with gzip.open(PANEL, "rt", encoding="utf-8") as f:
        uuids = [json.loads(line)["uuid"] for line in f if line.strip()]
    conn = personas.connect()
    by_uuid: dict[str, dict] = {}
    for start in range(0, len(uuids), 500):
        for row in conn.execute(FULL_SQL, (json.dumps(uuids[start:start + 500]),)):
            item = dict(row)
            item.pop("id", None)  # local row number of the converted DB, not part of the source data
            by_uuid[item["uuid"]] = item
    missing = [u for u in uuids if u not in by_uuid]
    if missing:
        raise SystemExit(f"{len(missing)} panel people are not in the persona DB")
    digest = hashlib.sha256()
    with lzma.open(OUT, "wt", encoding="utf-8", preset=9 | lzma.PRESET_EXTREME) as f:
        for u in uuids:
            line = json.dumps(by_uuid[u], ensure_ascii=False, sort_keys=True) + "\n"
            digest.update(line.encode("utf-8"))
            f.write(line)
    source = attribution.recorded(config.persona_db())
    provenance.write_metadata(OUT, {"people": len(uuids), "content_sha256": digest.hexdigest()[:12], **source,
                                    "attribution": attribution.build(source, changes=("sampled", "dropped_id"),
                                                                     model_output=False)})
    print(f"wrote {OUT} ({len(uuids):,} people, {len(next(iter(by_uuid.values())))} fields, "
          f"{OUT.stat().st_size / 1e6:.1f} MB, content sha256 {digest.hexdigest()[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
