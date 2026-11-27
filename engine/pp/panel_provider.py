"""Panel provider: policy text + N -> synthetic citizens as JSON, for other tools.

    provide({"policy_text": "공개 정책 문안", "n": 24, "affected": 8}, db_path)

The people come from the persona database (NVIDIA Nemotron-Personas-Korea, CC BY 4.0). The database path is
`--db`, else PP_PERSONA_DB, else PP_DATA_DIR/vendor/korean-people-persona/database/persona.db. It is opened read-only.

No model is called. The representative part is a stratified sample (province x age band x sex). The affected part is
found without a language model: occupation names of the database that appear in the policy text, occupation names the
caller passes, and full-text keywords the caller passes (for example the node names of a document graph).

Every person is synthetic. The output says so in `notice`, and the caller must carry that notice into whatever it
shows. The provider does not invent a stance or an activity level: `agent.stance` is a fixed neutral sentence and
`agent.activity` is a constant, and `agent.stance_basis` / `agent.activity_basis` say so.
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import config, panel, personas, prompts, provenance, selection

SCHEMA = "pp.panel/1"
MAX_N = 5000
MAX_POLICY_CHARS = 500_000
NOTICE = ("이 목록의 사람은 모두 합성 인물입니다(NVIDIA Nemotron-Personas-Korea 기반). 실제 사람이 아니며, "
          "이들의 반응은 실제 여론이 아닙니다. 결과를 보여 줄 때 이 표시를 함께 보여 주세요.")
SOURCE = {
    "dataset": "nvidia/Nemotron-Personas-Korea",
    "url": "https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea",
    "license": "CC BY 4.0",
    "changes": "층화 추출, 서술문을 300자로 자름",
}
NEUTRAL_STANCE = "정해진 입장 없음. 이 문안을 처음 읽는다."
DEFAULT_ACTIVITY = 0.5
PERSONA_LIMIT = 800
REQUEST_KEYS = frozenset({"policy_text", "n", "affected", "keywords", "occupations", "provinces", "age_min", "age_max",
                          "sex", "seed"})


class PanelRequestError(ValueError):
    """The request cannot be served as asked (bad numbers, unknown province, no one matches)."""


def _int(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PanelRequestError(f"{name} must be an integer")
    if not low <= value <= high:
        raise PanelRequestError(f"{name} must be between {low} and {high}")
    return value


def _strings(value, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PanelRequestError(f"{name} must be a list of strings")
    out: list[str] = []
    for item in value:
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out


def normalize_request(raw: dict) -> dict:
    """Validate one request. Unknown keys are an error, so a typo never silently changes the sample."""
    if not isinstance(raw, dict):
        raise PanelRequestError("request must be a JSON object")
    unknown = set(raw) - REQUEST_KEYS
    if unknown:
        raise PanelRequestError(f"unknown request keys: {sorted(unknown)}")
    policy_text = raw.get("policy_text") or ""
    if not isinstance(policy_text, str):
        raise PanelRequestError("policy_text must be a string")
    if len(policy_text) > MAX_POLICY_CHARS:
        raise PanelRequestError(f"policy_text is longer than {MAX_POLICY_CHARS} characters")
    n = _int(raw.get("n"), "n", 1, MAX_N)
    affected = _int(raw.get("affected", 0), "affected", 0, n)
    provinces = []
    for name in _strings(raw.get("provinces"), "provinces"):
        province = config.to_raw_province(name)
        if not province:
            raise PanelRequestError(f"unknown province: {name}")
        if province not in provinces:
            provinces.append(province)
    age_min = _int(raw["age_min"], "age_min", 0, 130) if raw.get("age_min") is not None else None
    age_max = _int(raw["age_max"], "age_max", 0, 130) if raw.get("age_max") is not None else None
    if age_min is not None and age_max is not None and age_min > age_max:
        raise PanelRequestError("age_min is greater than age_max")
    sex = raw.get("sex")
    if sex is not None and sex not in ("남자", "여자"):
        raise PanelRequestError("sex must be 남자 or 여자")
    return {
        "policy_text": policy_text, "n": n, "affected": affected,
        "keywords": _strings(raw.get("keywords"), "keywords"),
        "occupations": _strings(raw.get("occupations"), "occupations"),
        "provinces": provinces, "age_min": age_min, "age_max": age_max, "sex": sex,
        "seed": _int(raw.get("seed", 42), "seed", 0, 2_147_483_647),
    }


def _eligible(req: dict, province: str, age: int, sex: str) -> bool:
    if req["provinces"] and province not in req["provinces"]:
        return False
    if req["age_min"] is not None and age < req["age_min"]:
        return False
    if req["age_max"] is not None and age > req["age_max"]:
        return False
    return req["sex"] is None or sex == req["sex"]


def eligible_strata(index: personas.PersonaIndex, req: dict) -> dict[tuple[str, str, str], list[int]]:
    """Sampling strata (province, age band, sex) over the people the request allows."""
    out: dict[tuple[str, str, str], list[int]] = {}
    for pid, province, age, sex in zip(index.ids, index.provinces, index.ages, index.sexes):
        if _eligible(req, province, age, sex):
            out.setdefault((province, config.age_band(age), sex), []).append(pid)
    return out


def occupations_in_text(names: list[str], text: str, limit: int = 12) -> list[str]:
    """Occupation names of the database that appear word for word in the policy text, longest first."""
    hits = [name for name in names if len(name) >= 2 and name in text]
    return sorted(hits, key=lambda name: (-len(name), name))[:limit]


def _label(p: dict) -> str:
    return " · ".join([config.age_band(p["age"]), p["sex"], config.PROVINCE_DISPLAY.get(p["province"], p["province"]),
                       p["occupation"]])


def to_person(p: dict, kind: str, found_by: list[str]) -> dict:
    """One persona row -> the public shape. `agent` holds the fields a simulation agent needs."""
    label = _label(p)
    story = " ".join(part for part in (prompts.clip(p.get("persona"), 300),
                                       prompts.clip(p.get("professional_persona"), 300)) if part)
    return {
        "uuid": p["uuid"], "kind": kind, "found_by": found_by, "label": label,
        "sex": p["sex"], "age": p["age"], "age_band": config.age_band(p["age"]),
        "province": config.PROVINCE_DISPLAY.get(p["province"], p["province"]),
        "region": config.REGION_OF.get(p["province"], ""), "district": p["district"],
        "occupation": p["occupation"], "education_level": p["education_level"],
        "marital_status": p["marital_status"], "family_type": p["family_type"], "housing_type": p["housing_type"],
        "persona": prompts.clip(p.get("persona"), 300),
        "profile": prompts.persona_profile(p),
        "agent": {
            "name": f"{label} #{str(p['uuid'])[-6:]}",
            "persona": prompts.clip(f"[합성 인물] {label}. {story}", PERSONA_LIMIT),
            "stance": NEUTRAL_STANCE, "stance_basis": "none",
            "activity": DEFAULT_ACTIVITY, "activity_basis": "default",
        },
    }


class Provider:
    """Holds one read-only connection and the sampling index, so a server loads the database once."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else config.persona_db()
        if db_path is None and personas.source() == "bundle":
            from . import bundle_db
            self.db_path = bundle_db.ensure()
        # Pass the caller's path through unchanged, so personas.connect applies its own default when none was given.
        self.conn = personas.connect(self.db_path)
        self.index = personas.PersonaIndex.load(self.conn)
        self.occupation_names = personas.occupation_names(self.conn)
        self._lock = threading.Lock()

    def close(self) -> None:
        self.conn.close()

    def provide(self, raw: dict) -> dict:
        req = normalize_request(raw)
        with self._lock:
            return self._provide(req)

    def _affected(self, req: dict, exclude: set[int]) -> tuple[list[dict], dict]:
        matched = occupations_in_text(self.occupation_names, req["policy_text"])
        occupations = req["occupations"] + [name for name in matched if name not in req["occupations"]]
        keywords = personas.usable_keywords(req["keywords"])
        info = {"occupations_in_text": matched, "occupations_used": occupations, "keywords_used": keywords,
                "keywords_too_short": [k for k in req["keywords"] if k not in keywords], "channels": {}, "filters": []}
        if not req["affected"] or not (occupations or keywords):
            return [], info
        group: dict = {}
        if occupations:
            group["occupation_like"] = occupations
        if req["provinces"]:
            group["province_in"] = req["provinces"]
        for key in ("age_min", "age_max", "sex"):
            if req[key] is not None:
                group[key] = req[key]
        spec = {"filters": [group] if occupations else [], "keywords": keywords}
        info["filters"] = spec["filters"]
        # Ask for more than needed: full-text hits ignore the demographic limits and are dropped below.
        picked, channels = panel.build_affected(self.conn, spec, exclude, k=req["affected"] * 3, seed=req["seed"])
        info["channels"] = channels
        sexes = {row["id"]: row["sex"] for row in personas.fetch(self.conn, [c["id"] for c in picked])}
        kept = [c for c in picked if _eligible(req, c["province"], c["age"], sexes.get(c["id"], ""))]
        return kept[:req["affected"]], info

    def _provide(self, req: dict) -> dict:
        strata = eligible_strata(self.index, req)
        available = sum(len(ids) for ids in strata.values())
        if not available:
            raise PanelRequestError("no one in the database matches the province, age and sex limits")
        representative = panel.sample_representative(strata, req["n"] - req["affected"], seed=req["seed"])
        initial_rep = list(representative)
        refill = []
        affected, info = self._affected(req, set(representative))
        found_by = {c["id"]: c["found_by"] for c in affected}
        short = req["affected"] - len(affected)
        if short:  # fill the gap with more representative people, so the caller still gets n when possible
            taken = set(representative) | set(found_by)
            rest = {key: [i for i in ids if i not in taken] for key, ids in strata.items()}
            refill = panel.sample_representative(rest, short, seed=req["seed"] + 1)
            representative += refill
        rows = {row["id"]: row for row in personas.fetch(self.conn, representative + list(found_by))}
        people = [to_person(rows[i], "representative", []) for i in representative if i in rows]
        people += [to_person(rows[i], "affected", found_by[i]) for i in found_by if i in rows]
        receipt = selection.receipt(
                source=provenance.artifact(self.db_path), requested_spec={**{k: v for k, v in req.items() if k != "policy_text"},
                    "policy_hash": provenance.input_hash(req["policy_text"])},
                spec={"filters": info["filters"], "keywords": info["keywords_used"], "semantic_query": "",
                      "demographic_limits": {k: req[k] for k in ("provinces", "age_min", "age_max", "sex")}},
                strata=strata, rep_ids=representative, affected=affected, rows=list(rows.values()),
                n_rep=req["n"] - req["affected"], seed=req["seed"], pool_uuids=None,
                affected_receipt=info, channel_counts=info["channels"],
                missing_semantic_uuids=[], semantic_note="not used")
        receipt["representative"]["strata_basis"] = "initial_draw_only"
        receipt["representative"]["draws"] = [
            {"seed": req["seed"], "requested_count": req["n"] - req["affected"],
             "uuids": [rows[i]["uuid"] for i in initial_rep]},
            {"seed": req["seed"] + 1, "requested_count": short,
             "uuids": [rows[i]["uuid"] for i in refill],
             "exclude_uuids": [rows[i]["uuid"] for i in initial_rep + list(found_by)]},
        ]
        return {
            "schema": SCHEMA, "synthetic": True, "notice": NOTICE,
            "source": {**SOURCE, "population": len(self.index.ids)},
            "request": {key: value for key, value in req.items() if key != "policy_text"}
            | {"policy_chars": len(req["policy_text"])},
            "counts": {"requested": req["n"], "returned": len(people), "eligible": available,
                       "representative": len(representative), "affected_requested": req["affected"],
                       "affected_found": len(found_by)},
            "affected_search": info,
            "selection": receipt,
            "people": people,
        }


def provide(raw: dict, db_path: Path | None = None) -> dict:
    """One-off call: open the database, serve one request, close."""
    provider = Provider(db_path)
    try:
        return provider.provide(raw)
    finally:
        provider.close()
