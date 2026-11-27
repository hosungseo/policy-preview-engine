"""Source and terms that travel with every output, so a file copied out of the repository still credits its data.

A run bundle, a consultation plan, a survey result, the visit cards and the people map each leave as one JSON file.
Each carries an `attribution` block: who made the synthetic personas, under which licence (CC BY 4.0), at which source
revision, how this project changed them, which public statistics were used, and that the answers are model output.
`data/SOURCES.md` stays the per-file ledger; this module is the machine-readable part the code attaches.

Revisions are never guessed: a run's recorded `source_revision` is used, else a panel whose content hash was verified
file by file (docs/provenance/nemotron-source-revision.md), else the revision is reported as not recorded.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

SCHEMA = "pp-attribution-v1"
REPO = "https://github.com/hosungseo/policy-preview-engine"
SOURCES_URL = f"{REPO}/blob/main/data/SOURCES.md"
PROVENANCE_URL = f"{REPO}/blob/main/docs/provenance/nemotron-source-revision.md"

NEMOTRON_REPO = "nvidia/Nemotron-Personas-Korea"
NEMOTRON_URL = "https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea"
CC_BY = "CC BY 4.0"
CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"
APACHE_URL = "https://www.apache.org/licenses/LICENSE-2.0"
KOGL1_URL = "https://www.kogl.or.kr/info/licenseType1.do"

# The 20k panel bundle whose source revision was checked against the nine downloaded parquet files and every saved
# field (docs/provenance/nemotron-source-revision.md). Key: the bundle's content hash (panel_version before any
# '+addons-' suffix).
VERIFIED_PANELS = {"4b5aa1c42bfd": "ada0f5b53a38bb5a30cce09358adde883c1ab63a"}

# What this project did to the source data, by output. Each output names the ones that apply.
CHANGES = {
    "sampled": "100만 명 원본에서 일부 인물만 골랐습니다(시도 × 연령대 × 성별 비율 또는 정책 조건 검색).",
    "profile": "인물 서술을 줄이고 속성 줄과 함께 프로필 문장으로 다시 엮었습니다.",
    "grouped": "가구 유형·나이 같은 값을 집계용 묶음 이름(예: 연령대, ‘배우자 없이 자녀와 거주’)으로 나눴습니다.",
    "addons": "공공 통계로 배정한 생활 여건(가정)을 덧붙였습니다. 원본에 없는 값이며 그 사람의 사실이 아닙니다.",
    "answers": "AI 판단·문장 모델이 이 인물이라고 가정하고 낸 답과 문장을 붙였습니다.",
    "dots": "시군구 안의 점 위치는 읍면동 넓이에 비례해 흩어 놓은 것이며 실제 주소가 아닙니다.",
    "dropped_id": "변환한 DB의 행 번호(id)만 빼고 원본 필드를 그대로 옮겼습니다.",
    "db": "원본 parquet을 SQLite 표와 전문 검색 색인으로 옮기고 행 번호(id)를 붙였습니다.",
}
DEFAULT_CHANGES = ("sampled", "profile", "grouped", "answers")

BOUNDARIES = {
    "role": "boundaries", "provider": "국토교통부",
    "name": "행정구역도(브이월드 2D 데이터 API 2.0, LT_C_ADSIDO_INFO·LT_C_ADSIGG_INFO·LT_C_ADEMD_INFO)",
    "url": None, "license": "공공누리 제1유형(출처표시)", "license_url": KOGL1_URL, "modified": True,
    "changes": ["경계선을 단순화하고, 읍면동 넓이로 점을 흩는 데 썼습니다."],
}

RECORDED_KEYS = ("source_repo", "source_revision", "revision_status")


def recorded(path: Path) -> dict:
    """The source fields of `<file>.meta.json` beside a panel or persona DB, without hashing the file itself."""
    from .provenance import metadata_path

    sidecar = metadata_path(Path(path))
    if not sidecar.exists():
        return {}
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    return {k: data[k] for k in RECORDED_KEYS if data.get(k) is not None}


def revision(meta: dict | None) -> tuple[str | None, str]:
    """(source revision, status) from a run's meta: the recorded value, else a verified saved panel, else unknown."""
    meta = meta or {}
    rev = meta.get("source_revision")
    if rev:
        return rev, meta.get("revision_status") or "recorded"
    base = (meta.get("panel_version") or "").split("+", 1)[0]
    if base in VERIFIED_PANELS:
        return VERIFIED_PANELS[base], "verified_saved_panel"
    return None, "unknown"


def addon_statistics(addons: Iterable[str]) -> list[str]:
    """Public statistics behind the life-context add-ons attached to a run, in first-seen order."""
    from . import life_context

    out: list[str] = []
    for name in addons:
        for item in life_context.ADDONS.get(name, {}).get("sources", []):
            if item not in out:
                out.append(item)
    return out


def personas(meta: dict | None = None, changes: Iterable[str] = DEFAULT_CHANGES) -> dict:
    rev, status = revision(meta)
    return {
        "role": "synthetic_personas", "provider": "NVIDIA", "name": "Nemotron-Personas-Korea",
        "repo": NEMOTRON_REPO, "url": NEMOTRON_URL, "license": CC_BY, "license_url": CC_BY_URL,
        "source_revision": rev, "revision_status": status,
        "revision_evidence": PROVENANCE_URL if status == "verified_saved_panel" else None,
        "modified": True, "changes": [CHANGES[c] for c in changes],
        "synthetic": True, "note": "공공 통계 분포로 만든 합성 인물이며 실존 인물이 아닙니다.",
    }


def statistics(items: Iterable[str]) -> dict | None:
    items = [i for i in items if i]
    if not items:
        return None
    return {
        "role": "public_statistics", "provider": "각 통계 작성기관(통계청·국가데이터처 등)",
        "name": "공공 통계(KOSIS 국가통계포털 등)", "items": items, "url": "https://kosis.kr",
        "license": "출처 표기(각 작성기관의 이용 조건)", "license_url": None, "modified": True,
        "changes": ["공표된 표의 분포로 합성 인물에게 값을 확률 배정하거나 비교 기준으로 썼습니다. 개인의 실제 값이 아닙니다."],
        "details": SOURCES_URL,
    }


def generated() -> dict:
    return {
        "role": "generated", "provider": "policy-preview-engine", "name": "이 프로젝트가 만든 결과",
        "url": REPO, "license": "Apache-2.0", "license_url": APACHE_URL, "modified": False, "changes": [],
        "note": "판단·문장 모델이 합성 인물이라고 가정하고 낸 추정입니다. 실제 사람의 응답이나 여론이 아닙니다.",
    }


def _notice(sources: list[dict]) -> str:
    p = next(s for s in sources if s["role"] == "synthetic_personas")
    rev = p["source_revision"]
    if rev:
        rev_text = f"원본 revision {rev[:7]}" + (" (사용자 입력, 검증 안 됨)" if p["revision_status"] == "user_supplied" else "")
    else:
        rev_text = "원본 revision 기록 없음"
    parts = [f"합성 인물: NVIDIA, Nemotron-Personas-Korea ({NEMOTRON_URL}), {CC_BY} ({CC_BY_URL}), {rev_text}. "
             "이 프로젝트가 가공했습니다. " + " ".join(p["changes"]) + " 실존 인물이 아닙니다."]
    stats = next((s for s in sources if s["role"] == "public_statistics"), None)
    if stats:
        parts.append(f"공공 통계: {', '.join(stats['items'])} — 각 작성기관, 출처 표기 조건.")
    for s in sources:
        if s["role"] not in ("synthetic_personas", "public_statistics", "generated"):
            parts.append(f"{s['name']}: {s['provider']}, {s['license']}.")
    if any(s["role"] == "generated" for s in sources):
        parts.append("답과 문장은 AI 모델의 추정이며 실제 여론이 아닙니다.")
    parts.append(f"파일별 출처: {SOURCES_URL}")
    return " ".join(parts)


def build(meta: dict | None = None, *, changes: Iterable[str] = DEFAULT_CHANGES, stats: Iterable[str] = (),
          extra: Iterable[dict] = (), model_output: bool = True) -> dict:
    """The attribution block for one output. `meta` holds the run's source fields (source_revision,
    revision_status, panel_version); `stats` names the public statistics the output actually used."""
    sources = [personas(meta, changes)]
    table = statistics(stats)
    if table:
        sources.append(table)
    sources += [dict(e) for e in extra]
    if model_output:
        sources.append(generated())
    return {"schema": SCHEMA, "notice": _notice(sources), "sources": sources, "details": SOURCES_URL}


def short(block: dict) -> str:
    """One line for text people copy out (a card summary): the persona credit, its revision and that it was changed."""
    p = next(s for s in block["sources"] if s["role"] == "synthetic_personas")
    rev = f", revision {p['source_revision'][:7]}" if p.get("source_revision") else ""
    return f"자료: NVIDIA Nemotron-Personas-Korea({CC_BY}{rev})를 이 프로젝트가 가공했습니다. 출처·이용 조건: {SOURCES_URL}"


def validate(block: dict | None) -> list[str]:
    """Problems that would let an output travel without its credit; [] when complete."""
    if not isinstance(block, dict):
        return ["attribution missing"]
    errors = []
    if block.get("schema") != SCHEMA:
        errors.append(f"attribution schema is not {SCHEMA}")
    sources = block.get("sources") or []
    p = next((s for s in sources if s.get("role") == "synthetic_personas"), None)
    if p is None:
        errors.append("attribution lacks the synthetic persona source")
    else:
        wanted = (("provider", "NVIDIA"), ("license", CC_BY), ("license_url", CC_BY_URL), ("url", NEMOTRON_URL))
        for key, want in wanted:
            if p.get(key) != want:
                errors.append(f"attribution persona {key} is not {want}")
        if not (p.get("modified") and p.get("changes")):
            errors.append("attribution does not say how the personas were changed")
        if "source_revision" not in p or not p.get("revision_status"):
            errors.append("attribution lacks the source revision fields")
    for s in sources:
        if s.get("role") == "public_statistics" and not (s.get("items") and s.get("license")):
            errors.append("attribution public statistics lack items or terms")
    notice = block.get("notice") or ""
    if CC_BY not in notice or "Nemotron-Personas-Korea" not in notice:
        errors.append("attribution notice lacks the persona credit")
    return errors
