"""Build the portable 20,000-person panel bundle from NVIDIA Nemotron-Personas-Korea.

Source: https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea (CC BY 4.0; 1,000,000 synthetic people, public,
no sign-in). The panel keeps the province x age band x sex proportions of the full list (largest-remainder seats,
deterministic for a seed) and stores each person as the ready-made profile text that pp.prompts.persona_profile writes.

  cd engine
  ../.venv/bin/python scripts/build_panel_from_nemotron.py                       # downloads about 2 GB of parquet
  ../.venv/bin/python scripts/build_panel_from_nemotron.py --parquet-dir DIR     # parquet files already on disk
  ../.venv/bin/python scripts/build_panel_from_nemotron.py --persona-db          # also the full 1M persona DB

Writes engine/ppservice/data/panel-20k.jsonl.gz (uuid, sex, age, age_band, province, capital, profile). With
--persona-db it also writes the full list as SQLite with an FTS5 trigram index at the path pp.config.persona_db()
reads (data/vendor/korean-people-persona/database/persona.db, about 10 GB), which `python -m pp run`,
scripts/build_population.py and scripts/build_roster_1m.py use.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pp import config, prompts, provenance  # noqa: E402
from pp.panel import allocate  # noqa: E402

REPO_ID = "nvidia/Nemotron-Personas-Korea"
OUT = Path(__file__).resolve().parents[1] / "ppservice" / "data" / "panel-20k.jsonl.gz"
CAPITAL = {"서울", "인천", "경기"}
STRATA_COLS = ["uuid", "province", "age", "sex"]
PROFILE_COLS = ["uuid", "persona", "professional_persona", "family_persona", "cultural_background", "sex", "age",
                "marital_status", "family_type", "housing_type", "education_level", "bachelors_field", "occupation",
                "district", "province"]
# The persona DB schema the engine reads (pp.personas); text columns after `persona` get the FTS5 index.
TEXT_COLS = ["persona", "professional_persona", "sports_persona", "arts_persona", "travel_persona",
             "culinary_persona", "family_persona", "cultural_background", "skills_and_expertise",
             "hobbies_and_interests", "career_goals_and_ambitions"]
DB_COLS = ["uuid", *TEXT_COLS, "sex", "age", "marital_status", "family_type", "housing_type", "education_level",
           "bachelors_field", "occupation", "district", "province"]


def download(dest: Path, revision: str) -> Path:
    """Fetch the public parquet files (no token needed) into `dest`; returns the folder holding them."""
    from huggingface_hub import snapshot_download

    path = snapshot_download(repo_id=REPO_ID, repo_type="dataset", allow_patterns=["data/*.parquet", "README.md"],
                             local_dir=dest, revision=revision)
    return Path(path) / "data"


def parquet_files(folder: Path) -> list[Path]:
    files = sorted(folder.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no parquet files in {folder}")
    return files


def batches(files: list[Path], columns: list[str]):
    import pyarrow.parquet as pq

    for path in files:
        for batch in pq.ParquetFile(path).iter_batches(columns=columns, batch_size=50_000):
            yield from batch.to_pylist()


def choose(files: list[Path], n: int, seed: int) -> set[str]:
    """uuids of n adults keeping the province x age band x sex proportions of the whole list."""
    strata: dict[tuple, list[str]] = defaultdict(list)
    for row in batches(files, STRATA_COLS):
        if int(row["age"]) < 19:
            continue
        strata[(row["province"], config.age_band(int(row["age"])), row["sex"])].append(row["uuid"])
    seats = allocate({k: len(v) for k, v in strata.items()}, n)
    rng = random.Random(seed)
    chosen: set[str] = set()
    for key in sorted(strata, key=str):
        chosen.update(rng.sample(sorted(strata[key]), seats[key]))
    return chosen


def write_bundle(files: list[Path], chosen: set[str], out: Path) -> dict:
    rows = {r["uuid"]: r for r in batches(files, PROFILE_COLS) if r["uuid"] in chosen}
    missing = chosen - set(rows)
    if missing:
        raise SystemExit(f"{len(missing)} chosen people not found on the second pass")
    out.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    tmp = out.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f:
        for uuid in sorted(rows):
            r = rows[uuid]
            line = json.dumps({"uuid": uuid, "sex": r["sex"], "age": int(r["age"]),
                               "age_band": config.age_band(int(r["age"])), "province": r["province"],
                               "capital": r["province"] in CAPITAL, "profile": prompts.persona_profile(r)},
                              ensure_ascii=False, sort_keys=True)
            digest.update((line + "\n").encode("utf-8"))
            f.write(line + "\n")
    tmp.replace(out)
    return {"out": str(out), "people": len(rows), "bytes": out.stat().st_size, "panel_version": digest.hexdigest()[:12]}


def write_persona_db(files: list[Path], dest: Path) -> int:
    """The full list as the SQLite table `persona` plus the FTS5 trigram index the engine searches."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    cols = ", ".join(["id INTEGER PRIMARY KEY", "uuid TEXT", *[f"{c} TEXT" for c in TEXT_COLS], "sex TEXT",
                      "age INTEGER", "marital_status TEXT", "family_type TEXT", "housing_type TEXT",
                      "education_level TEXT", "bachelors_field TEXT", "occupation TEXT", "district TEXT",
                      "province TEXT"])
    conn.execute(f"CREATE TABLE persona ({cols})")
    insert = f"INSERT INTO persona (id, {', '.join(DB_COLS)}) VALUES ({', '.join('?' * (len(DB_COLS) + 1))})"
    count = 0
    buffer = []
    for row in batches(files, DB_COLS):
        count += 1
        buffer.append((count, *(row[c] for c in DB_COLS)))
        if len(buffer) >= 20_000:
            conn.executemany(insert, buffer)
            buffer.clear()
    conn.executemany(insert, buffer)
    conn.execute("CREATE UNIQUE INDEX persona_uuid ON persona(uuid)")
    conn.execute("CREATE INDEX persona_occupation ON persona(occupation)")
    conn.execute("CREATE INDEX persona_province ON persona(province)")
    fts = TEXT_COLS[1:]
    conn.execute(f"CREATE VIRTUAL TABLE persona_fts USING fts5({', '.join(fts)}, content='persona', content_rowid='id',"
                 " tokenize='trigram')")
    conn.execute(f"INSERT INTO persona_fts(rowid, {', '.join(fts)}) SELECT id, {', '.join(fts)} FROM persona")
    conn.commit()
    conn.close()
    tmp.replace(dest)
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--parquet-dir", type=Path, help="folder with the dataset's parquet files (skips the download)")
    parser.add_argument("--download-dir", type=Path, default=config.data_dir() / "nemotron-personas-korea",
                        help="where the download goes (default: data/nemotron-personas-korea)")
    parser.add_argument("--n", type=int, default=20_000, help="panel size (default 20000)")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--revision", help="HF branch/tag/commit for downloads; full commit SHA for local parquet")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--persona-db", nargs="?", const=config.persona_db(), type=Path, default=None,
                        help="also write the full persona DB (default path: pp.config.persona_db())")
    args = parser.parse_args(argv)

    if args.parquet_dir:
        if args.revision and not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
            parser.error("local parquet --revision must be a full commit SHA (or omit for unknown)")
        revision = args.revision
    else:
        from huggingface_hub import HfApi

        revision = HfApi().dataset_info(REPO_ID, revision=args.revision or "main").sha
        if not revision:
            raise RuntimeError("HF did not return a source commit SHA")
    files = parquet_files(args.parquet_dir or download(args.download_dir, revision))
    report = write_bundle(files, choose(files, args.n, args.seed), args.out)
    report["seed"] = args.seed
    report.update(source_repo=REPO_ID, source_revision=revision,
                  revision_status="user_supplied" if args.parquet_dir and revision else "resolved" if revision else "unknown")
    provenance.write_metadata(args.out, report)
    if args.persona_db:
        report["persona_db"] = str(args.persona_db)
        report["persona_db_rows"] = write_persona_db(files, args.persona_db)
        provenance.write_metadata(args.persona_db, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
