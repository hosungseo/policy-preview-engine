"""Read-only access to the persona SQLite DB built by korean-people-persona."""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import config

FIELDS = (
    "id", "uuid", "persona", "professional_persona", "family_persona", "cultural_background",
    "sex", "age", "marital_status", "family_type", "housing_type", "education_level",
    "bachelors_field", "occupation", "district", "province",
)
FILTER_KEYS = frozenset({
    "occupation_like", "province_in", "age_min", "age_max",
    "family_type_like", "housing_type_in", "education_in", "sex",
})
# Fixed statements: lists travel as one JSON parameter (json_each), so no SQL text is ever assembled at run time.
FETCH_SQL = ("SELECT id, uuid, persona, professional_persona, family_persona, cultural_background, sex, age, marital_status,"
             " family_type, housing_type, education_level, bachelors_field, occupation, district, province"
             " FROM persona WHERE id IN (SELECT value FROM json_each(?))")
UUID_SQL = "SELECT id, uuid FROM persona WHERE uuid IN (SELECT value FROM json_each(?))"
EXACT_OCCUPATIONS_SQL = "SELECT DISTINCT occupation FROM persona WHERE occupation IN (SELECT value FROM json_each(?))"
# Each condition is off when its parameter is NULL. Exact occupations also match their former-worker form.
FILTER_SQL = """SELECT id FROM persona WHERE
 (:occ_exact IS NULL AND :occ_like IS NULL
  OR EXISTS (SELECT 1 FROM json_each(:occ_exact) j WHERE occupation = j.value OR occupation = '전직 ' || j.value || ', 현재 구직중')
  OR EXISTS (SELECT 1 FROM json_each(:occ_like) j WHERE occupation LIKE j.value))
 AND (:family IS NULL OR EXISTS (SELECT 1 FROM json_each(:family) j WHERE family_type LIKE j.value))
 AND (:province IS NULL OR province IN (SELECT value FROM json_each(:province)))
 AND (:housing IS NULL OR housing_type IN (SELECT value FROM json_each(:housing)))
 AND (:education IS NULL OR education_level IN (SELECT value FROM json_each(:education)))
 AND (:age_min IS NULL OR age >= :age_min)
 AND (:age_max IS NULL OR age <= :age_max)
 AND (:sex IS NULL OR sex = :sex)
 ORDER BY id"""
_NAME = re.compile(r"^\s*([가-힣]{2,4})\s*씨")


def source() -> str:
    """Where personas come from: "db" (the 1M-person SQLite on the SSD) or "bundle" (the 20k panel shipped in the
    repo). PP_PERSONA_SOURCE picks one; unset uses the 1M DB when it is there and the bundle otherwise."""
    explicit = (os.environ.get("PP_PERSONA_SOURCE") or "").strip()
    if explicit in ("db", "bundle"):
        return explicit
    return "db" if config.persona_db().exists() else "bundle"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None and source() == "bundle":
        from . import bundle_db

        db_path = bundle_db.ensure()
    path = Path(db_path or config.persona_db())
    if not path.exists():
        raise config.DataMissing(f"persona DB not found: {path} — 외장 SSD 연결과 PP_DATA_DIR을 확인하세요")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def extract_name(persona_text: str | None) -> str:
    match = _NAME.match(persona_text or "")
    return match.group(1) if match else ""


@dataclass
class PersonaIndex:
    """Compact in-memory index of every persona, used for stratified sampling."""

    ids: list[int]
    provinces: list[str]
    ages: list[int]
    sexes: list[str]

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> "PersonaIndex":
        rows = conn.execute("SELECT id, province, age, sex FROM persona ORDER BY id").fetchall()
        return cls([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows])

    def strata(self) -> dict[tuple[str, str, str], list[int]]:
        out: dict[tuple[str, str, str], list[int]] = {}
        for pid, prov, age, sex in zip(self.ids, self.provinces, self.ages, self.sexes):
            out.setdefault((prov, config.age_band(age), sex), []).append(pid)
        return out


def fetch(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    found: dict[int, dict] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        for row in conn.execute(FETCH_SQL, (json.dumps(chunk),)):
            item = dict(row)
            item["name"] = extract_name(item["persona"])
            found[item["id"]] = item
    return [found[i] for i in ids if i in found]


def ids_for_uuids(conn: sqlite3.Connection, uuids: list[str], *, strict: bool = False,
                  missing: list[str] | None = None) -> list[int]:
    found: dict[str, int] = {}
    for start in range(0, len(uuids), 500):
        chunk = uuids[start:start + 500]
        for row in conn.execute(UUID_SQL, (json.dumps(chunk, ensure_ascii=False),)):
            found[row[1]] = row[0]
    absent = [u for u in uuids if u not in found]
    if missing is not None:
        missing.extend(absent)
    if strict and absent:
        raise ValueError(f"persona UUIDs not found: {absent}")
    return [found[u] for u in uuids if u in found]


def normalize_filter(group: dict) -> dict:
    """Reject unsupported conditions instead of broadening a requested AND-group."""
    if not isinstance(group, dict) or not group:
        raise ValueError("filter group must be a non-empty object")
    unknown = set(group) - FILTER_KEYS
    if unknown:
        raise ValueError(f"unknown filter keys: {sorted(unknown)}")
    out = {}
    list_keys = {"occupation_like", "family_type_like", "housing_type_in", "education_in", "province_in"}
    for key, value in group.items():
        if key in list_keys:
            values = value if isinstance(value, list) else [value]
            if not values or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"{key} must contain non-empty strings")
            values = [v.strip() for v in values]
            allowed = {"housing_type_in": config.HOUSING_ORDER, "education_in": config.EDUCATION_ORDER}.get(key)
            if key == "province_in":
                invalid = [v for v in values if config.to_raw_province(v) is None]
                if invalid:
                    raise ValueError(f"unknown provinces: {invalid}")
                values = [config.to_raw_province(v) for v in values]
            elif allowed is not None and set(values) - set(allowed):
                raise ValueError(f"unknown {key} values: {sorted(set(values) - set(allowed))}")
            out[key] = values
        elif key in ("age_min", "age_max"):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{key} must be a non-negative integer")
            out[key] = value
        else:
            if value not in ("남자", "여자"):
                raise ValueError("sex must be 남자 or 여자")
            out[key] = value
    if out.get("age_min", 0) > out.get("age_max", float("inf")):
        raise ValueError("age_min must not exceed age_max")
    return out


def _like(values: list[str]) -> list[str]:
    return [v if "%" in v else f"%{v}%" for v in values]


def filter_ids(conn: sqlite3.Connection, group: dict, limit: int = 300, seed: int = 42, *,
               receipt: dict | None = None) -> list[int]:
    """One AND-group of attribute conditions -> matching ids (random sample of `limit`)."""
    if not isinstance(group, dict):
        raise ValueError("filter group must be an object")
    group = normalize_filter(group) if group else {}
    def listed(values) -> str | None:
        values = [str(v) for v in values or []]
        return json.dumps(values, ensure_ascii=False) if values else None

    params = {"occ_exact": None, "occ_like": None, "family": listed(_like(list(group.get("family_type_like") or []))),
              "province": listed(group.get("province_in")), "housing": listed(group.get("housing_type_in")),
              "education": listed(group.get("education_in")),
              "age_min": None if group.get("age_min") is None else int(group["age_min"]),
              "age_max": None if group.get("age_max") is None else int(group["age_max"]),
              "sex": group.get("sex") or None}
    if group.get("occupation_like"):
        # A name that exists in the DB matches exactly (plus its former-worker form), so '검사' finds prosecutors
        # and not '환경 검사원'; anything else is a guessed fragment and matches as a substring.
        values = [str(v) for v in group["occupation_like"]]
        exact = {r[0] for r in conn.execute(EXACT_OCCUPATIONS_SQL, (listed(values),))}
        params["occ_exact"] = listed([v for v in values if v in exact])
        params["occ_like"] = listed(_like([v for v in values if v not in exact]))
        if params["occ_exact"] is None and params["occ_like"] is None:
            return []
    ids = [r[0] for r in conn.execute(FILTER_SQL, params)] if group else []
    total = len(ids)
    if len(ids) > limit:
        ids = sorted(random.Random(seed).sample(ids, limit))
    if receipt is not None:
        receipt.update({"conditions": group, "sql_template": "persona-filter-v1", "parameters": params,
                        "matching_count": total, "returned_count": len(ids), "limit": limit,
                        "sampled": total > limit, "seed": seed if total > limit else None,
                        "order": "id ASC", "sampling": "seeded_random_without_replacement" if total > limit else "none"})
    return ids


def occupation_names(conn: sqlite3.Connection) -> list[str]:
    """Every current occupation name in the DB, so a targeting spec can use names that exist.
    Former workers ('전직 …, 현재 구직중') still match these names through the substring filter."""
    rows = conn.execute("SELECT DISTINCT occupation FROM persona WHERE occupation NOT LIKE '전직 %'")
    return sorted(r[0] for r in rows if r[0])


def usable_keywords(keywords: list[str]) -> list[str]:
    """FTS5 trigram cannot match terms shorter than 3 characters, so drop them."""
    out: list[str] = []
    for word in keywords:
        word = str(word).replace('"', "").strip()
        if len(word) >= 3 and word not in out:
            out.append(word)
    return out


def fts_ids(conn: sqlite3.Connection, keywords: list[str], limit: int = 300) -> list[int]:
    words = usable_keywords(keywords)
    if not words:
        return []
    query = " OR ".join(f'"{w}"' for w in words)
    rows = conn.execute(
        "SELECT rowid FROM persona_fts WHERE persona_fts MATCH ? ORDER BY bm25(persona_fts), rowid LIMIT ?",
        (query, limit),
    ).fetchall()
    return [r[0] for r in rows]


def population(conn: sqlite3.Connection) -> dict:
    def dist(sql: str) -> dict:
        return {k: v for k, v in conn.execute(sql)}

    province = dist("SELECT province, COUNT(*) FROM persona GROUP BY province")
    age_band: dict[str, int] = {}
    for age, count in dist("SELECT age, COUNT(*) FROM persona GROUP BY age").items():
        band = config.age_band(age)
        age_band[band] = age_band.get(band, 0) + count
    region: dict[str, int] = {}
    for prov, count in province.items():
        region[config.REGION_OF[prov]] = region.get(config.REGION_OF[prov], 0) + count
    family: dict[str, int] = {}
    for kind, count in dist("SELECT family_type, COUNT(*) FROM persona GROUP BY family_type").items():
        bucket = config.family_bucket(kind)
        family[bucket] = family.get(bucket, 0) + count
    return {
        "total": conn.execute("SELECT COUNT(*) FROM persona").fetchone()[0],
        "province": province,
        "region": region,
        "sex": dist("SELECT sex, COUNT(*) FROM persona GROUP BY sex"),
        "age_band": age_band,
        "family": family,
        "housing_type": dist("SELECT housing_type, COUNT(*) FROM persona GROUP BY housing_type"),
        "education_level": dist("SELECT education_level, COUNT(*) FROM persona GROUP BY education_level"),
    }
