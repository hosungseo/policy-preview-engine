"""Which models this server runs with, for the screen: overseas, Korean (confirmed KR region), or local.

Every public setup is for public or synthetic policy drafts only (no pre-announcement confidential drafts or PII).

The setup is read from the same environment variables the engine uses, so the badge always shows what is actually
connected. PP_MODEL_PROFILE may name the setup explicitly, but never overrides a non-Korean or non-local endpoint
into claiming 'korean' or 'local'.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

PROFILES = {
    "global": {"label": "해외 모델", "use": "공개된 자료나 가상 정책 문안만 입력하세요. 발표 전 비공개 문안·개인정보는 넣지 마세요. 해외 API로 전송됩니다."},
    "korean": {"label": "국산 모델(국내 리전 확인)", "use": "공개된 자료나 가상 정책 문안만 입력하세요. 발표 전 비공개 문안·개인정보는 넣지 마세요. 국내 리전 API로 전송됩니다."},
    "local": {"label": "로컬 모델", "use": "공개된 자료나 가상 정책 문안만 입력하세요. 발표 전 비공개 문안·개인정보는 넣지 마세요(기관 내부 별도 구축·보안심사 시에만 예외)."},
    "mock": {"label": "모의 실행", "use": "키 없이 화면과 흐름만 확인합니다. 공개·가상 문안만 입력하며 실제 AI 추론이 아닙니다."},
    "mixed": {"label": "혼합 구성", "use": "공개된 자료나 가상 정책 문안만 입력하세요. 발표 전 비공개 문안·개인정보는 넣지 마세요. 일부 요청이 해외 API로 전송될 수 있습니다."},
}


def _env(name: str, default: str = "") -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local") or host.startswith(
        ("10.", "192.168.")) or any(host.startswith(f"172.{n}.") for n in range(16, 32))


def _sentence() -> dict:
    from pp import jev

    provider = _env("PP_LLM_PROVIDER", "cli").lower()
    if provider == "mock":
        return {"name": "모의 응답", "where": "mock"}
    if provider == "exaone":
        return {"name": "LG EXAONE k-exaone_v2.5", "where": "korean"}
    if provider == "openai":
        url = _env("PP_LLM_BASE_URL")
        name = _env("PP_LLM_MODEL", "OpenAI 호환 모델")
        if _is_local(url):
            return {"name": name.split("/")[-1], "where": "local"}
        return {"name": name, "where": "korean" if jev.is_korean_host(url) else "global"}
    return {"name": "Claude", "where": "global"}


def _decision() -> dict:
    from pp import jev

    provider = jev.provider()
    if provider == "mock":
        return {"name": "모의 응답", "where": "mock"}
    if provider == "upstage":
        is_kr = jev.upstage_is_korean_region()
        where = "korean" if is_kr else "global"
        region_label = "한국 리전" if is_kr else "글로벌"
        family = "Upstage Solar Decide Flash" if jev.model().lower() == "solar-decide-flash" else "Upstage Solar Decide"
        return {"name": f"{family} ({jev.model()} · {region_label})", "where": where}
    if jev.custom_endpoint():
        return {"name": jev.model(), "where": "local" if _is_local(jev.api_url()) else "global"}
    return {"name": "TypeSafe Jev", "where": "global"}


def current() -> dict:
    sentence, decision = _sentence(), _decision()
    inferred = sentence["where"] if sentence["where"] == decision["where"] else "mixed"
    explicit = _env("PP_MODEL_PROFILE").lower()
    if explicit in PROFILES:
        if explicit == "korean" and not (sentence["where"] == "korean" and decision["where"] == "korean"):
            kind = inferred
        elif explicit == "local" and not (sentence["where"] == "local" and decision["where"] == "local"):
            kind = inferred
        else:
            kind = explicit
    else:
        kind = inferred
    return {"kind": kind, **PROFILES[kind], "sentence": sentence, "decision": decision,
            "choices": [{"kind": k, **PROFILES[k]} for k in ("global", "korean", "local")]}


def holdout() -> dict | None:
    """Unseen-item accuracy of the running decision model from the latest holdout record, if it was measured."""
    import json
    from pathlib import Path

    from pp import jev

    if jev.provider() == "mock":
        return None
    records = sorted((Path(__file__).resolve().parent / "data" / "persona-accuracy").glob("holdout-*.json"))
    if not records:
        return None
    record = json.loads(records[-1].read_text(encoding="utf-8"))
    name = jev.model().lower()
    # Only solar-decide itself was measured; the Flash variant must not borrow its accuracy.
    key = ("solar" if name == "solar-decide" else None) if "solar" in name else \
        "tev1" if "tev1" in name else "jev" if "jev" in name else None
    entry = record.get("models", {}).get(key) if key else None
    new = ((entry or {}).get("fwd") or {}).get("new")
    if not new:
        return None
    return {"mae_pp": new["mae_pp"], "worst_pp": new["worst_pp"], "items": sum(
        1 for i in record["items"].values() if i["group"] == "new"), "measured_on": record["measured_on"],
            "model": entry["model"]}
