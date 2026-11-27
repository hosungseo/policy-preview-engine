"""The '100만 명 지도' bundle for the website: every persona as a dot, and the Jev panel of a series run on top.

  python -m pp peoplemap --run series-housing-ctx --bundle ../web/public/series/housing.json \\
      --geo <시군구·읍면동·시도 GeoJSON 폴더> --out ../web/public/series/housing-map

writes (the page fetches them in the browser)
  dots.bin        Uint16 x,y per persona (km * QUANT), persona DB order (district, id)
  panel.bin       the panel in panel order: dot index (Uint32 × n) · tenure code (Uint8 × n: 0 own, 1 jeonse,
                  2 monthly, 3 other; +4 owns two homes or more) · favour % (Uint8 × m·n, measure-major)
                  · against % (Uint8 × m·n). Answers are the "alone" condition only.
  meta.json       extent, district table, outlines, measures, file sizes, notes
  people-NN.json  the panel's persona cards, CHUNK people per file (fetched when a dot is clicked)

Only a dot's district is real (see dotmap). Every favour mean is checked against the series bundle before writing.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import dotmap, personas

QUANT = 64
CHUNK = 500
TENURE = {"own": 0, "jeonse": 1, "monthly": 2, "other": 3, "free": 3}
TENURE_LABELS = ["자가", "전세", "월세", "기타"]
SHORT = {"경상남": "경남", "경상북": "경북", "전라남": "전남", "충청남": "충남", "충청북": "충북"}
MAX_GAP = 0.011   # a panel mean may differ from the bundle by rounding only (answers are stored as whole percents)


class PeopleMapError(RuntimeError):
    pass


def display(district: str) -> str:
    """'경상북-포항시 남구' -> '경북 포항시 남구'."""
    prov, rest = district.split("-", 1)
    return f"{SHORT.get(prov, prov)} {rest}"


def first_sentence(text: str | None, limit: int = 120) -> str:
    text = (text or "").strip()
    m = re.search(r"[.!?。](\s|$)", text)
    s = text[: m.end()].strip() if m else text
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def district_counts(conn: sqlite3.Connection) -> tuple[list[tuple[str, int]], np.ndarray]:
    """[(district, count)] in DB order, and every persona id in dot order (district, then id)."""
    rows = conn.execute("SELECT id, district FROM persona ORDER BY district, id").fetchall()
    order: list[list] = []
    for _, d in rows:
        if order and order[-1][0] == d:
            order[-1][1] += 1
        else:
            order.append([d, 1])
    return [(d, n) for d, n in order], np.array([r[0] for r in rows], dtype=np.int64)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def panel_arrays(run_dir: Path, measure_ids: list[str], uuids: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Tenure codes (n) and favour / against percents (m × n) of the panel, in panel order."""
    pos = {u: i for i, u in enumerate(uuids)}
    n, m = len(uuids), len(measure_ids)
    ten = np.full(n, 255, np.uint8)
    for r in _read_jsonl(run_dir / "tenure.jsonl"):
        if r["uuid"] in pos:
            ten[pos[r["uuid"]]] = TENURE[r["assigned"]] + (4 if r.get("multi_home") else 0)
    if (ten == 255).any():
        raise PeopleMapError(f"{int((ten == 255).sum())} panel people have no assigned tenure")
    fav, opp = np.zeros((m, n), np.uint8), np.zeros((m, n), np.uint8)
    for k, mid in enumerate(measure_ids):
        seen = np.zeros(n, bool)
        for r in _read_jsonl(run_dir / "answers" / f"{mid}__alone.jsonl"):
            i = pos.get(r["uuid"])
            if i is None:
                continue
            fav[k, i] = round(r["favor"] * 100)
            opp[k, i] = round((r["stance_probs"][0] + r["stance_probs"][1]) * 100)
            seen[i] = True
        if not seen.all():
            raise PeopleMapError(f"{mid}: {int((~seen).sum())} panel people have no answer")
    return ten, fav, opp


def build(run_dir: Path, bundle_path: Path, geo_dir: Path, out_dir: Path,
          conn: sqlite3.Connection | None = None, boundaries: dotmap.Boundaries | None = None) -> dict:
    conn = conn or personas.connect()
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    measures = bundle["measures"]
    mids = [m["id"] for m in measures]

    districts, ids = district_counts(conn)
    b = boundaries or dotmap.Boundaries.load(geo_dir)
    X, Y, table = dotmap.place(districts, b)
    at = {int(pid): i for i, pid in enumerate(ids)}

    panel = json.loads((Path(run_dir) / "panel.json").read_text(encoding="utf-8"))["people"]
    uuids = [p["uuid"] for p in panel]
    pids = personas.ids_for_uuids(conn, uuids)
    if len(pids) != len(uuids):
        raise PeopleMapError(f"{len(uuids) - len(pids)} panel uuids are not in the persona DB")
    idx = np.array([at[p] for p in pids], np.uint32)
    ten, fav, opp = panel_arrays(Path(run_dir), mids, uuids)
    for k, m in enumerate(measures):
        want, got = m["conditions"]["alone"]["favor"], float(fav[k].mean()) / 100
        if abs(want - got) > MAX_GAP:
            raise PeopleMapError(f"{m['id']}: panel favour {got:.4f} but the bundle says {want:.4f}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    np.stack([np.round(X * QUANT), np.round(Y * QUANT)], 1).astype("<u2").tofile(out / "dots.bin")
    with open(out / "panel.bin", "wb") as fh:
        for arr in (idx.astype("<u4"), ten, fav, opp):
            fh.write(np.ascontiguousarray(arr).tobytes())

    cards = personas.fetch(conn, [int(p) for p in pids])
    dist_index = {row["d"]: j for j, row in enumerate(table)}
    files = []
    for c in range(0, len(cards), CHUNK):
        rows = [[dist_index[p["district"]], int(p["age"]), 0 if p["sex"] == "남자" else 1, p["occupation"],
                 p["family_type"], p["housing_type"], first_sentence(p["persona"])] for p in cards[c:c + CHUNK]]
        name = f"people-{c // CHUNK:02d}.json"
        (out / name).write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        files.append(name)

    width, height = dotmap.extent(b)
    meta = {
        "version": 1, "series": bundle.get("id"), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "NVIDIA Nemotron-Personas-Korea (CC BY 4.0)",
        "quant": QUANT, "n_dots": int(len(ids)), "width_km": width, "height_km": height,
        "districts": [{"k": r["d"], "name": display(r["d"]), "s": r["s"], "n": r["n"], "cx": r["cx"], "cy": r["cy"]}
                      for r in table],
        "outlines": dotmap.outlines(b),
        "panel": {"n": int(len(idx)), "m": len(mids), "chunk": CHUNK, "files": files, "condition": "alone"},
        "measures": [{"id": m["id"], "short": m["short"], "date": m["date"], "title": m["title"],
                      "agency": m.get("agency", ""), "favor": m["conditions"]["alone"]["favor"]} for m in measures],
        "tenure_labels": TENURE_LABELS,
        "sizes": {p.name: p.stat().st_size for p in sorted(out.iterdir()) if p.is_file() and p.name != "meta.json"},
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"dots": int(len(ids)), "panel": int(len(idx)), "measures": len(mids), "files": len(files) + 3}
