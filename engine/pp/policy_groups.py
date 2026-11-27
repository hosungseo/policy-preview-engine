"""Policy-condition targeting, grouping, and visit-backed consultation views (pp.run/3).

Keeps the fast public path (CLI / HTTP API / MCP) aligned with policy conditions
(age, eligibility, region, keywords) instead of dumping dozens of unrelated raw
occupations, connects `visit_shared` venues and missing-person rules, collapses
repeated guidance sentences, and preserves all anti-overconfidence safeguards.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config, diagnostics, panel, panel_provider, personas, provenance, public_rules, selection, visit_shared

SCHEMA = "pp.run/3"
MAX_CONDITION_GROUPS = 8
MAX_INFERRED_GROUPS = 4
REP_OTHER_GROUP = "일반 대표 패널(문안 조건 외)"

CONDITION_KEYS = frozenset({
    "name", "label", "age_min", "age_max", "provinces", "occupations", "keywords",
    "eligibility", "family_type_like", "housing_type_in", "education_in", "sex", "clause_ids",
})

ELIGIBILITY_CLUE = re.compile(r"기초연금|기초생활|수급|취약계층|저소득|차상위|장애|한부모|다문화")
ELIGIBILITY_CAUTION = (
    "합성 인물 기본 자료에는 수급 자격·소득 정보가 없어 확인 후보로만 묶었습니다. "
    "실제 자격 해당 여부는 현장에서 확인하세요."
)
PANEL_SEPARATION_NOTE = (
    "대표 패널과 영향권 패널을 따로 구분해 기록합니다. "
    "영향권 반응은 전체 경향으로 일반화하지 않습니다."
)
VARIABILITY_NOTE = (
    "같은 문안이라도 표본·표현 순서에 따라 합성 반응이 흔들릴 수 있으며, "
    "이 경로의 오차는 측정되지 않았습니다. 현장에서 직접 확인하세요."
)

# Policy-text inference patterns (pure deterministic regex, zero model calls).
_AGE_RANGE = re.compile(r"(?:만\s*)?(\d{2})\s*[~∼\-–]\s*(\d{2})\s*세")
_AGE_MIN = re.compile(r"(?:만\s*)?(\d{2})\s*세\s*(?:이상|부터|로(?:\s|$|[,.]))")
_AGE_MAX = re.compile(r"(?:만\s*)?(\d{2})\s*세\s*(?:이하|미만)")
_PROVINCE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("서울", re.compile(r"서울(?:특별시)?")),
    ("부산", re.compile(r"부산(?:광역시)?")),
    ("대구", re.compile(r"대구(?:광역시)?")),
    ("인천", re.compile(r"인천(?:광역시)?")),
    ("광주", re.compile(r"광주(?:광역시)?")),
    ("대전", re.compile(r"대전(?:광역시)?")),
    ("울산", re.compile(r"울산(?:광역시)?")),
    ("세종", re.compile(r"세종(?:특별자치시)?")),
    ("경기", re.compile(r"경기도")),
    ("강원", re.compile(r"강원(?:특별자치도|도)?")),
    ("충청북", re.compile(r"충청북도|충북")),
    ("충청남", re.compile(r"충청남도|충남")),
    ("전북", re.compile(r"전북(?:특별자치도)?|전라북도")),
    ("전라남", re.compile(r"전라남도|전남")),
    ("경상북", re.compile(r"경상북도|경북")),
    ("경상남", re.compile(r"경상남도|경남")),
    ("제주", re.compile(r"제주(?:특별자치도|도)?")),
]
_DOMAIN_CLUES: list[tuple[re.Pattern[str], str, list[str]]] = [
    (re.compile(r"도시철도|지하철"), "도시철도·지하철 이용 관련", ["지하철로", "지하철"]),
    (re.compile(r"시내버스|대중교통"), "시내버스·대중교통 이용 관련", ["버스를", "시내버스"]),
    (re.compile(r"농어촌|농촌|어촌|농어민"), "농어촌·농림어업 관련", ["농사를", "농어촌"]),
    (re.compile(r"어린이집|유치원|영유아|보육"), "영유아·보육 관련", ["어린이집", "유치원"]),
    (re.compile(r"소상공인|자영업|전통시장"), "소상공인·자영업 관련", ["소상공인", "자영업"]),
]


class ConditionError(ValueError):
    """Invalid policy condition specification (never echoes caller-supplied secrets)."""


def _clean_str_list(value, field_name: str, *, max_items: int = 20) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConditionError(f"conditions.{field_name} must be a list of strings")
    out: list[str] = []
    for item in value:
        text = item.strip()
        if text and text not in out:
            out.append(text)
    if len(out) > max_items:
        raise ConditionError(f"conditions.{field_name} has too many items (max {max_items})")
    return out


def _clean_age(value, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 130:
        raise ConditionError(f"conditions.{field_name} must be an integer between 0 and 130")
    return value


def _auto_name(cond: dict) -> str:
    parts: list[str] = []
    lo, hi = cond.get("age_min"), cond.get("age_max")
    if lo is not None and hi is not None:
        parts.append(f"{lo}~{hi}세")
    elif lo is not None:
        parts.append(f"{lo}세 이상")
    elif hi is not None:
        parts.append(f"{hi}세 이하")
    provs = [config.PROVINCE_DISPLAY.get(p, p) for p in cond.get("provinces") or []]
    if provs:
        parts.append("·".join(provs[:3]) + (" 등" if len(provs) > 3 else ""))
    if cond.get("eligibility"):
        parts.append("·".join(cond["eligibility"][:2]))
    if cond.get("occupations"):
        parts.append("·".join(cond["occupations"][:2]))
    if cond.get("family_type_like"):
        parts.append("·".join(cond["family_type_like"][:2]) + " 가구")
    if cond.get("housing_type_in"):
        parts.append("·".join(cond["housing_type_in"][:2]))
    if cond.get("education_in"):
        parts.append("·".join(cond["education_in"][:2]))
    if cond.get("sex"):
        parts.append("여성" if cond["sex"] == "여자" else "남성")
    if cond.get("keywords") and not parts:
        parts.append(f"‘{cond['keywords'][0]}’ 관련")
    elif cond.get("keywords") and len(parts) < 3:
        parts.append(f"‘{cond['keywords'][0]}’ 관련")
    return " · ".join(parts) or "문안 조건 집단"


def _normalize_one(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ConditionError("each condition must be a JSON object")
    if set(raw) - CONDITION_KEYS:
        raise ConditionError("unknown keys in conditions; use name, age_min, age_max, provinces, occupations, keywords, eligibility, family_type_like, housing_type_in, education_in, sex, clause_ids")
    age_min = _clean_age(raw.get("age_min"), "age_min")
    age_max = _clean_age(raw.get("age_max"), "age_max")
    if age_min is not None and age_max is not None and age_min > age_max:
        raise ConditionError("conditions.age_min must not exceed conditions.age_max")

    provinces: list[str] = []
    for name in _clean_str_list(raw.get("provinces"), "provinces"):
        raw_prov = config.to_raw_province(name)
        if not raw_prov:
            raise ConditionError("unknown province in conditions.provinces")
        if raw_prov not in provinces:
            provinces.append(raw_prov)

    sex = raw.get("sex")
    if sex is not None and sex not in ("남자", "여자"):
        raise ConditionError("conditions.sex must be 남자 or 여자")

    housing = _clean_str_list(raw.get("housing_type_in"), "housing_type_in")
    if set(housing) - set(config.HOUSING_ORDER):
        raise ConditionError("invalid value in conditions.housing_type_in")

    education = _clean_str_list(raw.get("education_in"), "education_in")
    if set(education) - set(config.EDUCATION_ORDER):
        raise ConditionError("invalid value in conditions.education_in")

    occupations = _clean_str_list(raw.get("occupations"), "occupations")
    keywords = _clean_str_list(raw.get("keywords"), "keywords")
    eligibility = _clean_str_list(raw.get("eligibility"), "eligibility")
    family = _clean_str_list(raw.get("family_type_like"), "family_type_like")
    clause_ids = _clean_str_list(raw.get("clause_ids"), "clause_ids")

    raw_name = raw.get("name") if raw.get("name") is not None else raw.get("label")
    if raw_name is not None and (not isinstance(raw_name, str) or not raw_name.strip()):
        raise ConditionError("conditions.name must be a non-empty string")
    name = raw_name.strip()[:80] if isinstance(raw_name, str) else ""
    if name and (public_rules.PERSON.search(name) or public_rules.ELECTION.search(name)):
        raise ConditionError("conditions.name must describe a group, not an individual or election")

    has_criterion = any([
        age_min is not None, age_max is not None, provinces, occupations,
        keywords, eligibility, family, housing, education, sex is not None,
    ])
    if not has_criterion:
        raise ConditionError("each condition must specify at least one target criterion")

    # Map well-known household/housing eligibility terms into usable DB clues too.
    for term in eligibility:
        if any(k in term for k in ("1인", "독거", "혼자")) and "혼자" not in family:
            family.append("혼자")
        elif "한부모" in term and "한부모" not in family:
            family.append("한부모")

    cond = {
        "name": name,
        "age_min": age_min,
        "age_max": age_max,
        "provinces": provinces,
        "occupations": occupations,
        "keywords": keywords,
        "eligibility": eligibility,
        "family_type_like": family,
        "housing_type_in": housing,
        "education_in": education,
        "sex": sex,
        "clause_ids": clause_ids,
        "confirmed": True,
    }
    if not cond["name"]:
        cond["name"] = _auto_name(cond)
    needs_caution = bool(eligibility) or any(
        ELIGIBILITY_CLUE.search(text) for text in (cond["name"], *keywords)
    )
    cond["eligibility_caution"] = ELIGIBILITY_CAUTION if needs_caution else None
    return cond


def normalize_conditions(raw) -> list[dict]:
    """Validate and normalize caller-confirmed policy conditions (`None`, one dict, or a list)."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        if "groups" in raw and set(raw) == {"groups"}:
            items = raw["groups"]
        else:
            items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        raise ConditionError("conditions must be a JSON object or a list of objects")
    if not isinstance(items, list):
        raise ConditionError("conditions.groups must be a list of objects")
    if len(items) > MAX_CONDITION_GROUPS:
        raise ConditionError(f"conditions may contain at most {MAX_CONDITION_GROUPS} groups")
    out: list[dict] = []
    seen_names: set[str] = set()
    for item in items:
        explicit_name = isinstance(item, dict) and bool(item.get("name") or item.get("label"))
        cond = _normalize_one(item)
        if cond["name"] in seen_names:
            if explicit_name:
                raise ConditionError("conditions contain duplicate group names; give each group a distinct name")
            suffix = _auto_name(cond)
            if suffix and suffix != cond["name"] and f"{cond['name']} ({suffix})" not in seen_names:
                cond["name"] = f"{cond['name']} ({suffix})"
        if cond["name"] in seen_names:
            raise ConditionError("conditions contain duplicate group names; give each group a distinct name")
        seen_names.add(cond["name"])
        out.append(cond)
    return out


def infer_conditions(policy_text: str, occupation_names: list[str] | None = None) -> list[dict]:
    """Deterministically infer policy-aligned candidate groups from policy text (zero model calls)."""
    text = policy_text or ""
    out: list[dict] = []
    seen_names: set[str] = set()

    def add(cond: dict) -> None:
        if len(out) >= MAX_INFERRED_GROUPS:
            return
        if cond["name"] in seen_names:
            return
        seen_names.add(cond["name"])
        cond.setdefault("confirmed", False)
        cond.setdefault("provinces", [])
        cond.setdefault("occupations", [])
        cond.setdefault("keywords", [])
        cond.setdefault("eligibility", [])
        cond.setdefault("family_type_like", [])
        cond.setdefault("housing_type_in", [])
        cond.setdefault("education_in", [])
        cond.setdefault("sex", None)
        cond.setdefault("age_min", None)
        cond.setdefault("age_max", None)
        cond.setdefault("clause_ids", [])
        cond.setdefault("eligibility_caution", None)
        out.append(cond)

    # 1. Explicit age ranges / bounds in policy text (adult panel is 19+)
    found_age = False
    for match in _AGE_RANGE.finditer(text):
        lo, hi = int(match.group(1)), int(match.group(2))
        if hi >= 19 and lo <= hi <= 100:
            eff_lo = max(19, lo)
            found_age = True
            add({"name": f"{eff_lo}~{hi}세(문안 언급 연령)", "age_min": eff_lo, "age_max": hi})
    for match in _AGE_MIN.finditer(text):
        lo = int(match.group(1))
        if 19 <= lo <= 100:
            found_age = True
            add({"name": f"{lo}세 이상(문안 언급 연령)", "age_min": lo})
    for match in _AGE_MAX.finditer(text):
        hi = int(match.group(1))
        if 19 <= hi <= 100:
            found_age = True
            add({"name": f"19~{hi}세(문안 언급 연령)", "age_min": 19, "age_max": hi})
    if not found_age:
        if re.search(r"어르신|고령자|경로우대|노인복지", text):
            add({"name": "65세 이상(문안 언급 연령)", "age_min": 65})
        elif re.search(r"청년", text):
            add({"name": "19~34세 청년(문안 언급 대상)", "age_min": 19, "age_max": 34})

    # 2. Named provinces in policy text
    provs = [raw for raw, pat in _PROVINCE_PATTERNS if pat.search(text)]
    if provs:
        disp = [config.PROVINCE_DISPLAY.get(p, p) for p in provs]
        label = "·".join(disp[:4]) + (" 등" if len(disp) > 4 else "")
        add({"name": f"문안 언급 지역 주민({label})", "provinces": provs})

    # 3. Household clues
    if re.search(r"독거노인|독거|1인\s*가구|혼자\s*사는", text):
        add({"name": "혼자 사는 가구(문안 언급 조건)", "family_type_like": ["혼자"]})
    elif re.search(r"한부모", text):
        add({"name": "배우자 없이 자녀와 사는 가구(문안 언급 조건)", "family_type_like": ["한부모"]})

    # 4. Occupations literally appearing in policy text
    occ_hits = panel_provider.occupations_in_text(occupation_names or [], text, limit=6)
    if occ_hits:
        label = "·".join(occ_hits[:3]) + (" 등" if len(occ_hits) > 3 else "")
        add({"name": f"문안 언급 직종({label})", "occupations": occ_hits})

    # 5. Domain FTS keyword clues
    for pattern, label, kws in _DOMAIN_CLUES:
        if pattern.search(text):
            add({"name": f"{label}(문안 언급 조건)", "keywords": kws})

    return out


def _condition_sql_filter(cond: dict) -> dict:
    group: dict = {}
    if cond.get("occupations"):
        group["occupation_like"] = list(cond["occupations"])
    if cond.get("provinces"):
        group["province_in"] = list(cond["provinces"])
    if cond.get("age_min") is not None:
        group["age_min"] = cond["age_min"]
    if cond.get("age_max") is not None:
        group["age_max"] = cond["age_max"]
    if cond.get("family_type_like"):
        group["family_type_like"] = list(cond["family_type_like"])
    if cond.get("housing_type_in"):
        group["housing_type_in"] = list(cond["housing_type_in"])
    if cond.get("education_in"):
        group["education_in"] = list(cond["education_in"])
    if cond.get("sex") is not None:
        group["sex"] = cond["sex"]
    return group


def _person_matches_demographics(p: dict, cond: dict) -> bool:
    if cond.get("age_min") is not None and int(p["age"]) < cond["age_min"]:
        return False
    if cond.get("age_max") is not None and int(p["age"]) > cond["age_max"]:
        return False
    if cond.get("provinces"):
        raw_prov = config.to_raw_province(p.get("province", "")) or p.get("province", "")
        if raw_prov not in cond["provinces"]:
            return False
    if cond.get("sex") is not None and p.get("sex") != cond["sex"]:
        return False
    if cond.get("occupations"):
        occ = p.get("occupation", "")
        if not any(target == occ or target in occ for target in cond["occupations"]):
            return False
    if cond.get("family_type_like"):
        fam = p.get("family_type", "")
        if not any(part in fam for part in cond["family_type_like"]):
            return False
    if cond.get("housing_type_in") and p.get("housing_type") not in cond["housing_type_in"]:
        return False
    if cond.get("education_in") and p.get("education_level") not in cond["education_in"]:
        return False
    return True


def _person_matches_keywords(p: dict, words: list[str]) -> bool:
    if not words:
        return True
    haystack = " ".join(str(p.get(k) or "") for k in ("persona", "profile", "occupation", "district"))
    return any(w in haystack for w in words)


def _person_matches_condition(p: dict, cond: dict, *, allow_keyword_fallback: bool = False) -> bool:
    has_demo = bool(_condition_sql_filter(cond))
    if has_demo and not _person_matches_demographics(p, cond):
        return False
    words = [w for w in (cond.get("keywords") or []) + (cond.get("eligibility") or []) if w]
    if not words:
        return has_demo
    if _person_matches_keywords(p, words):
        return True
    # When demographic criteria exist and eligibility/keyword had no DB text hits, demographic proxy applies.
    return bool(has_demo and allow_keyword_fallback)


def select_panel(
    policy_text: str,
    sample: int,
    seed: int,
    confirmed_conditions: list[dict],
    db_path: Path | None = None,
) -> tuple[dict, list[dict], str]:
    """Select representative (stratified) + condition-targeted affected panel with full receipt."""
    provider = panel_provider.Provider(db_path)
    try:
        if confirmed_conditions:
            active = [dict(c) for c in confirmed_conditions]
            basis = "confirmed_conditions"
        else:
            active = infer_conditions(policy_text, provider.occupation_names)
            basis = "inferred_policy_conditions" if active else "life_condition_bands"

        affected_req = sample // 4
        if not active:
            sampled = provider.provide({
                "policy_text": policy_text, "n": sample, "affected": affected_req, "seed": seed,
            })
            for p in sampled["people"]:
                p["matched_conditions"] = []
            return sampled, [], basis

        strata = provider.index.strata()
        available = sum(len(ids) for ids in strata.values())
        if not available:
            raise panel_provider.PanelRequestError("no one in the database matches the request")

        n_rep = sample - affected_req
        representative = panel.sample_representative(strata, n_rep, seed=seed)
        initial_rep = list(representative)
        exclude = set(representative)

        # Match each active condition independently, then interleave round-robin for balanced coverage.
        per_cond_ids: list[list[int]] = []
        cond_names_by_pid: dict[int, list[str]] = {}
        found_by: dict[int, list[str]] = {}
        filter_specs: list[dict] = []
        all_keywords: list[str] = []
        keyword_fallback: dict[str, bool] = {}
        cond_receipts: list[dict] = []
        filter_total = 0
        fts_total = 0

        for cond in active:
            sql_filter = _condition_sql_filter(cond)
            if sql_filter:
                filter_specs.append(sql_filter)
            raw_words = [*(cond.get("keywords") or []), *(cond.get("eligibility") or [])]
            usable = personas.usable_keywords(raw_words)
            for w in usable:
                if w not in all_keywords:
                    all_keywords.append(w)

            f_ids = personas.filter_ids(provider.conn, sql_filter, limit=300, seed=seed) if sql_filter else []
            k_ids = personas.fts_ids(provider.conn, usable, limit=300) if usable else []
            filter_total += len(f_ids)
            fts_total += len(k_ids)

            f_set = set(f_ids)
            k_set = set(k_ids)
            used_fallback = False
            if sql_filter and usable:
                both = [pid for pid in f_ids if pid in k_set]
                if both:
                    matched = both + [pid for pid in f_ids if pid not in k_set]
                else:
                    matched = list(f_ids)
                    used_fallback = True
            elif sql_filter:
                matched = list(f_ids)
            else:
                matched = list(k_ids)

            keyword_fallback[cond["name"]] = used_fallback
            cond["keyword_fallback"] = used_fallback

            eligible_ids = [pid for pid in matched if pid not in exclude]
            per_cond_ids.append(eligible_ids)
            for pid in eligible_ids:
                cond_names_by_pid.setdefault(pid, [])
                if cond["name"] not in cond_names_by_pid[pid]:
                    cond_names_by_pid[pid].append(cond["name"])
                tags = found_by.setdefault(pid, [])
                if pid in f_set and "filter" not in tags:
                    tags.append("filter")
                if pid in k_set and "fts" not in tags:
                    tags.append("fts")
            cond_receipts.append({
                "name": cond["name"],
                "confirmed": bool(cond.get("confirmed")),
                "filter_hits": len(f_ids),
                "fts_hits": len(k_ids),
                "keyword_fallback": used_fallback,
            })

        merged_ids = panel.interleave(per_cond_ids)[:300]
        rows_for_aff = personas.fetch(provider.conn, merged_ids) if merged_ids else []
        cands = [
            {
                "id": r["id"], "province": r["province"], "age": r["age"],
                "occupation": r["occupation"], "found_by": found_by.get(r["id"], ["filter"]),
            }
            for r in rows_for_aff
        ]
        affected = panel.diversify(cands, affected_req, seed=seed) if affected_req and cands else []
        aff_found_by = {c["id"]: c["found_by"] for c in affected}

        refill: list[int] = []
        short = affected_req - len(affected)
        if short > 0:
            taken = set(representative) | set(aff_found_by)
            rest = {key: [i for i in ids if i not in taken] for key, ids in strata.items()}
            refill = panel.sample_representative(rest, short, seed=seed + 1)
            representative += refill

        all_ids = representative + list(aff_found_by)
        fetched = {row["id"]: row for row in personas.fetch(provider.conn, all_ids)}
        people: list[dict] = []
        for pid in representative:
            if pid in fetched:
                person = panel_provider.to_person(fetched[pid], "representative", [])
                person["matched_conditions"] = [
                    c["name"] for c in active
                    if _person_matches_condition(person, c, allow_keyword_fallback=keyword_fallback[c["name"]])
                ]
                people.append(person)
        for pid in aff_found_by:
            if pid in fetched:
                person = panel_provider.to_person(fetched[pid], "affected", aff_found_by[pid])
                matched_names = list(cond_names_by_pid.get(pid, []))
                for c in active:
                    if c["name"] not in matched_names and _person_matches_condition(
                        person, c, allow_keyword_fallback=keyword_fallback[c["name"]]
                    ):
                        matched_names.append(c["name"])
                person["matched_conditions"] = matched_names
                people.append(person)

        affected_info = {
            "grouping_basis": basis,
            "condition_groups": cond_receipts,
            "keywords_used": all_keywords,
            "filters": filter_specs,
            "channels": {"filter": filter_total, "fts": fts_total, "semantic": 0},
        }
        receipt = selection.receipt(
            source=provenance.artifact(provider.db_path),
            requested_spec={
                "n": sample, "affected": affected_req, "seed": seed,
                "policy_hash": provenance.input_hash(policy_text),
                "conditions": [{k: v for k, v in c.items() if k != "keyword_fallback"} for c in active],
            },
            spec={
                "filters": filter_specs, "keywords": all_keywords, "semantic_query": "",
                "demographic_limits": {"provinces": [], "age_min": None, "age_max": None, "sex": None},
            },
            strata=strata, rep_ids=representative, affected=affected, rows=list(fetched.values()),
            n_rep=n_rep, seed=seed, pool_uuids=None,
            affected_receipt=affected_info, channel_counts=affected_info["channels"],
            missing_semantic_uuids=[], semantic_note="not used",
        )
        receipt["representative"]["strata_basis"] = "initial_draw_only"
        receipt["representative"]["draws"] = [
            {"seed": seed, "requested_count": n_rep, "uuids": [fetched[i]["uuid"] for i in initial_rep]},
            {
                "seed": seed + 1, "requested_count": short,
                "uuids": [fetched[i]["uuid"] for i in refill],
                "exclude_uuids": [fetched[i]["uuid"] for i in initial_rep + list(aff_found_by)],
            },
        ]
        sampled = {
            "schema": panel_provider.SCHEMA,
            "synthetic": True,
            "notice": panel_provider.NOTICE,
            "source": {**panel_provider.SOURCE, "population": len(provider.index.ids)},
            "counts": {
                "requested": sample, "returned": len(people), "eligible": available,
                "representative": len(representative), "affected_requested": affected_req,
                "affected_found": len(aff_found_by),
            },
            "affected_search": affected_info,
            "selection": receipt,
            "people": people,
        }
        return sampled, active, basis
    finally:
        provider.close()


def _public_criteria(cond: dict) -> dict:
    out = {}
    for key in ("age_min", "age_max", "provinces", "occupations", "keywords", "eligibility",
                "family_type_like", "housing_type_in", "education_in", "sex", "clause_ids"):
        val = cond.get(key)
        if val is not None and val != []:
            if key == "provinces":
                out[key] = [config.PROVINCE_DISPLAY.get(p, p) for p in val]
            else:
                out[key] = val
    return out


def _panel_scope(member_people: list[dict]) -> str:
    kinds = {p.get("kind") for p in member_people}
    if kinds == {"representative", "affected"}:
        return "대표·영향권 분리"
    if kinds == {"affected"}:
        return "영향권"
    if kinds == {"representative"}:
        return "대표"
    return "표본 미배정"


def _fold_repeated_outreach(items: list[dict]) -> tuple[list[dict], dict]:
    """Collapse repeated method/question/caution sentences across outreach items into shared notes."""
    method_groups: dict[str, list[str]] = {}
    question_groups: dict[str, list[str]] = {}
    cautions_seen: list[str] = []
    for item in items:
        method_groups.setdefault(item["method"], []).append(item["group"])
        question_groups.setdefault(item["question"], []).append(item["group"])
        for caution in item.get("cautions") or []:
            if caution not in cautions_seen:
                cautions_seen.append(caution)

    folded_methods = {m: gs for m, gs in method_groups.items() if len(gs) > 1}
    folded_questions = {q: gs for q, gs in question_groups.items() if len(gs) > 1}
    seen_method: set[str] = set()
    seen_question: set[str] = set()
    cleaned: list[dict] = []

    for item in items:
        row = {
            "group": item["group"],
            "venues": item["venues"],
            "channels": item["channels"],
            "where": item["where"],
            "method": item["method"],
            "question": item["question"],
        }
        if item["method"] in folded_methods:
            if item["method"] in seen_method:
                row["method"] = "공통 접근 방식 참고(outreach_notes)"
            else:
                seen_method.add(item["method"])
        if item["question"] in folded_questions:
            if item["question"] in seen_question:
                row["question"] = "공통 현장 질문 참고(outreach_notes)"
            else:
                seen_question.add(item["question"])
        cleaned.append(row)

    notes = {
        "venue_basis_note": visit_shared.VENUE_BASIS_NOTE,
        "folded_methods": [{"text": text, "groups": gs} for text, gs in folded_methods.items()],
        "folded_questions": [{"text": text, "groups": gs} for text, gs in folded_questions.items()],
        "cautions": cautions_seen,
    }
    return cleaned, notes


def build_consultation_views(
    policy_text: str,
    segments: list[dict],
    people: list[dict],
    reactions: list[dict],
    issues: list[dict],
    qa: list[dict],
    clarity: dict,
    active_conditions: list[dict],
    grouping_basis: str,
) -> tuple[dict, list[str], dict, list[str]]:
    """Build all qualitative consultation views + diagnostics + warnings + limits for pp.run/3.

    Returns `(public_payload, warnings, diag, limits)` where `public_payload` has already passed
    through `public_rules.check_output`.
    """
    by_uuid = {p["uuid"]: p for p in people}
    by_rid = {r["rid"]: r for r in reactions}
    clause_order = {s["id"]: i for i, s in enumerate(segments)}

    reaction_segments = {r["rid"]: r.get("segment_id") for r in reactions}
    issue_segments = {it["id"]: {reaction_segments[rid] for rid in it["member_ids"]} for it in issues}
    clause_issues = [
        {**s, "issues": [it["id"] for it in issues if s["id"] in issue_segments[it["id"]]]}
        for s in segments
    ]

    # 1. Assign people to policy-aligned groups (confirmed conditions / inferred / coarse age bands).
    cond_by_name = {c["name"]: c for c in active_conditions}
    group_people: dict[str, list[dict]] = {}
    group_kind: dict[str, str] = {}
    person_groups: dict[str, list[str]] = {p["uuid"]: [] for p in people}
    unmatched_conditions: list[dict] = []

    if active_conditions:
        for cond in active_conditions:
            members = [p for p in people if cond["name"] in (p.get("matched_conditions") or [])]
            if members:
                group_people[cond["name"]] = members
                group_kind[cond["name"]] = "confirmed_condition" if cond.get("confirmed") else "inferred_condition"
                for p in members:
                    person_groups[p["uuid"]].append(cond["name"])
            elif cond.get("confirmed"):
                unmatched_conditions.append(cond)
        others = [p for p in people if not person_groups[p["uuid"]]]
        if others:
            group_people[REP_OTHER_GROUP] = others
            group_kind[REP_OTHER_GROUP] = "representative_other"
            for p in others:
                person_groups[p["uuid"]].append(REP_OTHER_GROUP)
    else:
        # Fallback when policy text has no explicit conditions: coarse visit.py age bands (max 6, never 95 occupations).
        band_order = [label for _, _, label in config.AGE_BANDS]
        for label in band_order:
            members = [p for p in people if p.get("age_band") == label]
            if members:
                group_people[label] = members
                group_kind[label] = "life_condition_band"
                for p in members:
                    person_groups[p["uuid"]].append(label)

    # Order groups strictly by earliest referenced source clause, then definition order (never counts/votes).
    reactions_by_uuid = {r["uuid"]: r for r in reactions}
    ordered_groups = list(group_people.keys())
    ordered_groups.sort(key=lambda group: min(
        (clause_order.get(reactions_by_uuid[p["uuid"]].get("segment_id"), len(segments))
         for p in group_people[group] if p["uuid"] in reactions_by_uuid),
        default=len(segments),
    ))

    # 2. Build missing_perspectives from visit_shared (PARTIES + ALWAYS_MISSING + panel limits + clauses + underheard).
    missing: list[dict] = []
    for item in visit_shared.missing_people(policy_text):
        if item["party"]:
            missing.append({
                "kind": "policy_party",
                "group": item["who"],
                "route": item["route"],
                "reason": "문안에 언급된 직접 당사자·이해관계자; 합성 인물만으로 대신할 수 없어 별도 청취 필요",
                "party": True,
            })
        else:
            reason = (
                "합성 패널만으로는 조직된 이해관계를 대신할 수 없음"
                if "단체" in item["who"]
                else "원본 합성 패널에 포함되지 않음"
            )
            missing.append({
                "kind": "panel_limit",
                "group": item["who"],
                "route": item["route"],
                "reason": reason,
                "party": False,
            })
    missing.append({
        "kind": "panel_limit",
        "group": "소득별 관점",
        "route": "행정복지센터 복지 창구·현장 면담으로 생활 여건 직접 확인",
        "reason": "패널에 소득 정보 없음",
        "party": False,
    })
    missing += [
        {
            "kind": "uncovered_clause",
            "segment_id": c["id"],
            "reason": "검증된 인용으로 연결된 쟁점이 없어 실제 의견수렴에서 별도 확인 필요",
        }
        for c in clause_issues if not c["issues"]
    ]
    for cond in unmatched_conditions:
        missing.append({
            "kind": "unmatched_condition",
            "group": cond["name"],
            "route": " · ".join(visit_shared.venue_guidance(cond["name"], [], condition=cond)["venues"]),
            "reason": "확인된 문안 조건에 맞는 합성 인물이 이번 표본에 없어 현장에서 직접 확인 필요",
        })

    # 3. Build group_reactions (with representative/affected separation) and visit_shared outreach.
    group_reactions: list[dict] = []
    raw_outreach: list[dict] = []
    group_venues_map: dict[str, list[str]] = {}
    group_meta_list: list[dict] = []

    def reaction_view(r: dict, p: dict) -> dict:
        return {
            **{k: r[k] for k in ("reason", "trigger_quote", "quote_verified", "segment_id", "suggestion")},
            "panel": "affected" if p.get("kind") == "affected" else "representative",
        }

    for group in ordered_groups:
        members = group_people[group]
        rows = [reactions_by_uuid[p["uuid"]] for p in members if p["uuid"] in reactions_by_uuid]
        rep_rows = [reaction_view(r, by_uuid[r["uuid"]]) for r in rows if by_uuid[r["uuid"]].get("kind") != "affected"]
        aff_rows = [reaction_view(r, by_uuid[r["uuid"]]) for r in rows if by_uuid[r["uuid"]].get("kind") == "affected"]
        combined_rows = [reaction_view(r, by_uuid[r["uuid"]]) for r in rows]

        cond = cond_by_name.get(group)
        guidance = visit_shared.venue_guidance(group, members, reactions=rows, condition=cond)
        group_venues_map[group] = guidance["venues"]

        group_reactions.append({
            "group": group,
            "grouping_basis": group_kind[group],
            "panel_scope": _panel_scope(members),
            "status": "AI가 상상한 반응" if rows else "반응을 만들지 못함",
            "reactions": combined_rows,
            "panel_separation": {
                "note": PANEL_SEPARATION_NOTE,
                "representative_reactions": rep_rows,
                "affected_reactions": aff_rows,
            },
        })
        group_meta_list.append({
            "name": group,
            "basis": group_kind[group],
            "panel_scope": _panel_scope(members),
            "criteria": _public_criteria(cond) if cond else {},
            "eligibility_caution": cond.get("eligibility_caution") if cond else None,
        })

        if any(not r["would_comment"] for r in rows):
            missing.append({
                "kind": "underheard_group",
                "group": group,
                "route": " · ".join(guidance["venues"]),
                "reason": "스스로 의견을 내기 어려울 수 있다는 AI 짐작; 현장 확인 필요",
            })
            if cond and cond.get("eligibility_caution") and cond["eligibility_caution"] not in guidance["cautions"]:
                guidance["cautions"].append(cond["eligibility_caution"])
            raw_outreach.append(guidance)

    outreach, outreach_notes = _fold_repeated_outreach(raw_outreach)

    # Fold raw occupations (instead of emitting 95 mismatched occupation groups).
    folded_occupations = list(dict.fromkeys(p["occupation"] for p in people if p.get("occupation")))
    folded_occupations.sort(key=lambda occ: min(
        (clause_order.get(r.get("segment_id"), len(segments))
         for r in reactions if by_uuid[r["uuid"]].get("occupation") == occ),
        default=len(segments),
    ))
    grouping = {
        "basis": grouping_basis,
        "confirmed": grouping_basis == "confirmed_conditions",
        "groups": group_meta_list,
        "collapsed": {
            "occupation_groups_folded": True,
            "reason": "문안 조건과 어긋나는 세부 직업 묶음은 접고 문안 조건·생활 여건 기준으로 묶었습니다.",
            "note": "세부 직업 목록은 참고용으로만 보관하며 대표성이나 중요도 판단의 근거로 쓰지 않습니다.",
            "occupations": folded_occupations,
        },
    }

    # 4. Build who_to_ask using policy-condition groups + visit_shared venues.
    who: list[dict] = []
    for it in issues:
        issue_group_set: set[str] = set()
        issue_panels: set[str] = set()
        for rid in it["member_ids"]:
            uuid = by_rid[rid]["uuid"]
            issue_group_set.update(person_groups.get(uuid, []))
            issue_panels.add(by_uuid[uuid].get("kind", "representative"))
        groups = [g for g in ordered_groups if g in issue_group_set]
        venues: list[str] = []
        for g in groups:
            for v in group_venues_map.get(g, []):
                if v not in venues:
                    venues.append(v)
                    if len(venues) >= 4:
                        break
            if len(venues) >= 4:
                break
        questions = [q["question"] for q in qa if q["issue_id"] == it["id"]]
        scope = (
            "대표·영향권 분리" if issue_panels == {"representative", "affected"}
            else "영향권" if issue_panels == {"affected"}
            else "대표"
        )
        who.append({
            "issue_id": it["id"],
            "groups": groups,
            "venues": venues,
            "panel_scope": scope,
            "questions": questions or ["이 조항으로 생활에서 무엇이 달라지며 무엇을 확인해야 하나요?"],
            "basis": "문안 조항과 조건에 연결된 집단; 현장 확인 필요",
        })

    # 5. Diagnostics & anti-overconfidence warnings (instability, rep/aff separation, attribution, diagnostics).
    diag = {
        "reliability_findings": diagnostics.question_reliability_findings(policy_text, []),
        "warnings": [],
        "status": "qualitative_only",
        "note": "정량 확률 응답을 수집하지 않아 분산·집단 차이 진단은 계산하지 않았습니다.",
        "variability_note": VARIABILITY_NOTE,
        "panel_separation_note": PANEL_SEPARATION_NOTE,
    }
    warnings = [public_rules.WARNING, diag["note"], VARIABILITY_NOTE]
    warnings += [item["message"] for item in diag["reliability_findings"] + diag["warnings"]]
    for cond in active_conditions:
        caution = cond.get("eligibility_caution")
        if caution and caution not in warnings:
            warnings.append(caution)
        if cond.get("keyword_fallback") and cond.get("keywords"):
            note = f"조건 ‘{cond['name']}’의 낱말 검색 결과가 없어 연령·지역 등 기본 속성 후보로 대체했습니다."
            if note not in warnings:
                warnings.append(note)

    public_payload = public_rules.check_output({
        "clauses": clause_issues,
        "issues": [{k: it[k] for k in ("id", "title", "summary")} for it in issues],
        "missing_perspectives": missing,
        "who_to_ask": who,
        "outreach": outreach,
        "outreach_notes": outreach_notes,
        "questions": qa,
        "grouping": grouping,
        "group_reactions": group_reactions,
        "clarity": clarity,
    }, policy_text, warnings)

    limits = [
        "반응은 합성 프로필마다 별도 호출로 만들고 공개 시 문안 조건·생활 여건 기준으로 묶었습니다(세부 직업 묶음은 접음).",
        "대표 패널과 영향권 패널은 분리해 기록합니다. 영향권 반응은 전체 경향으로 일반화하지 않습니다.",
        "당사자 목록은 문안의 모든 조항에서 추출한 전수 목록이 아니며, 명단 밖 당사자는 현장에서 따로 만나야 합니다.",
        "반응의 비율·건수·순위는 제공하지 않습니다. 비용 산정용 sample은 의견의 수가 아닙니다.",
        "같은 문안이라도 표본·표현 순서에 따라 반응이 흔들릴 수 있으며, 이 모델 구성의 오차는 측정되지 않았습니다. 실제 당사자에게 확인하세요.",
        "Jev 명료성 점검은 조항 맥락 4,000자·전체 안내 6,000자를 사용합니다.",
        "큰 문안의 계층 요약에서 쟁점을 놓칠 수 있습니다.",
    ]
    return public_payload, warnings, diag, limits
