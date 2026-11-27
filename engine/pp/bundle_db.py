"""Persona DB built from the portable 20k panel bundle, so the deep pipeline runs without the 1M-person SSD database.

The bundle (engine/ppservice/data/panel-20k.jsonl.gz) stores each person as a ready-made profile text written by
prompts.persona_profile. This module parses that text back into the `persona` table columns the pipeline reads and
adds the same FTS5 trigram index. The file is cached under the data directory and rebuilt when the bundle changes.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from . import config
from .filelock_util import lock_file, unlock_file

BUNDLE = Path(__file__).resolve().parents[1] / "ppservice" / "data" / "panel-20k.jsonl.gz"
NO_NAME = "(이름 없음)"
FTS_COLS = ("professional_persona", "family_persona", "cultural_background")
COLUMNS = ("id", "uuid", "persona", "professional_persona", "family_persona", "cultural_background", "sex", "age",
           "marital_status", "family_type", "housing_type", "education_level", "bachelors_field", "occupation",
           "district", "province")

# Fixed statements matching COLUMNS and FTS_COLS (checked in tests/test_bundle_db.py).
CREATE_SQL = ("CREATE TABLE persona (id INTEGER PRIMARY KEY, uuid TEXT, persona TEXT, professional_persona TEXT,"
              " family_persona TEXT, cultural_background TEXT, sex TEXT, age INTEGER, marital_status TEXT, family_type TEXT,"
              " housing_type TEXT, education_level TEXT, bachelors_field TEXT, occupation TEXT, district TEXT, province TEXT)")
INSERT_SQL = ("INSERT INTO persona (id, uuid, persona, professional_persona, family_persona, cultural_background, sex, age,"
              " marital_status, family_type, housing_type, education_level, bachelors_field, occupation, district, province)"
              " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
FTS_SQL = ("CREATE VIRTUAL TABLE persona_fts USING fts5(professional_persona, family_persona, cultural_background,"
           " content='persona', content_rowid='id', tokenize='trigram')")
FTS_FILL_SQL = ("INSERT INTO persona_fts(rowid, professional_persona, family_persona, cultural_background)"
                " SELECT id, professional_persona, family_persona, cultural_background FROM persona")


def bundle_path() -> Path:
    return Path((os.environ.get("PP_PANEL_BUNDLE") or "").strip() or BUNDLE)


def _after(line: str, prefix: str) -> str:
    if not line.startswith(prefix):
        raise ValueError(f"profile line does not start with {prefix!r}: {line[:40]!r}")
    return line[len(prefix):]


def parse_profile(row: dict) -> dict:
    """One bundle row -> persona columns (without id). Inverse of prompts.persona_profile for the long form."""
    lines = row["profile"].split("\n")
    if len(lines) < 11 or lines[6] != "":
        raise ValueError(f"unexpected profile layout for {row.get('uuid')}")
    district = _after(lines[2], "사는 곳: ").rsplit(" (", 1)[0]
    education, marital = _after(lines[4], "학력: ").split(" / 혼인: ", 1)
    family, housing = _after(lines[5], "가구: ").rsplit(" / 주거: ", 1)
    return {
        "uuid": row["uuid"], "persona": lines[7], "professional_persona": lines[8], "family_persona": lines[9],
        "cultural_background": lines[10], "sex": row["sex"], "age": int(row["age"]), "marital_status": marital,
        "family_type": family, "housing_type": housing, "education_level": education, "bachelors_field": "",
        "occupation": _after(lines[3], "직업: "), "district": district, "province": row["province"],
    }


def build(dest: Path, source: Path | None = None) -> int:
    """Write the persona DB at `dest` from the bundle; returns the number of people."""
    raw = gzip.decompress((source or bundle_path()).read_bytes())
    rows = [parse_profile(json.loads(line)) for line in raw.decode("utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda r: r["uuid"])  # ids are stable for a given bundle
    conn = sqlite3.connect(dest)
    try:
        conn.execute(CREATE_SQL)
        conn.executemany(INSERT_SQL, [(i + 1, *(r[c] for c in COLUMNS[1:])) for i, r in enumerate(rows)])
        conn.execute("CREATE UNIQUE INDEX persona_uuid ON persona(uuid)")
        conn.execute("CREATE INDEX persona_occupation ON persona(occupation)")
        conn.execute(FTS_SQL)
        conn.execute(FTS_FILL_SQL)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def ensure() -> Path:
    """Path of the cached persona DB for the current bundle, building it once (safe across threads and processes)."""
    source = bundle_path()
    if not source.exists():
        raise config.DataMissing(f"panel bundle not found: {source}")
    version = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    folder = config.data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"panel-20k.{version}.db"
    if dest.exists():
        return dest
    with open(folder / "panel-20k.lock", "w+") as lock:
        lock_file(lock, nonblocking=False)
        try:
            if not dest.exists():
                tmp = dest.with_suffix(f".tmp{os.getpid()}")
                tmp.unlink(missing_ok=True)
                build(tmp, source)
                tmp.replace(dest)
        finally:
            unlock_file(lock)
    return dest
