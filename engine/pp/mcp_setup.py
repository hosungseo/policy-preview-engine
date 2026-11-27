"""Offline onboarding and safe, actionable errors shared by public adapters."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from tempfile import TemporaryDirectory

from . import attribution, budget, bundle_db, config, llm, personas, public_rules, provenance

TRIAL_LABEL = "체험(모의) 결과"
TRIAL_NOTICE = "실제 여론이 아닙니다. 구조만 보여 주는 0원 체험입니다. 숫자·문장은 가짜이며, 실제 결과에는 API 키와 합성 인물 자료가 필요합니다."
FREE_ALTERNATIVE = "try_example으로 키·패널 없이 무료 예시를 볼 수 있습니다."
_trial = ContextVar("pp_trial", default=False)
_panel = ContextVar("pp_trial_panel", default=None)
GUIDANCE = {
    "missing_model_key": ("실제 실행용 Anthropic API 키가 없습니다.", "서버 환경변수 ANTHROPIC_API_KEY를 설정하고 클라이언트를 다시 켜세요."),
    "panel_not_ready": ("실제 실행에 필요한 합성 인물 자료가 없습니다.", "python engine/scripts/build_panel_from_nemotron.py로 패널을 준비하세요."),
    "input_rejected": ("입력 문안 또는 형식이 실행 규칙에 맞지 않습니다.", "표시된 낱말이나 입력 항목을 고쳐 다시 비용을 확인하세요."),
    "invalid_region": ("권역값이 맞지 않습니다.", "권역을 " + ", ".join(sorted(set(config.REGION_OF.values()))) + " 중에서 골라 무료 재집계를 다시 요청하세요."),
    "budget_exceeded": ("설정한 비용 또는 호출 한도에 닿아 멈췄습니다.", "합성 프로필 수(sample)를 줄여 새 비용을 확인하세요."),
    "run_not_found": ("이 서버에서 해당 실행 번호(run id)를 찾지 못했습니다.", "estimate의 plan_id(견적 번호)가 아니라 start_run이 돌려준 id(실행 번호)를 넣으세요. 서버를 재시작했다면 새 견적부터 시작하세요."),
    "plan_id_as_run_id": ("이 번호는 견적 번호입니다. 실행 번호를 넣으세요.", "이 견적으로 실행해 달라고 말한 뒤, 돌려받은 실행 번호로 결과를 확인하세요."),
    "model_call_failed": ("모델 응답을 받지 못했습니다.", "check_setup으로 실행 준비 상태를 확인하세요."),
    "lawmaking_unavailable": ("국민참여입법센터의 자료를 지금 읽지 못했습니다.", "잠시 뒤 find_notice로 다시 찾아보세요."),
    "notice_not_found": ("고른 입법예고의 이유·주요내용 원문을 찾지 못했습니다.", "find_notice로 예고를 다시 고르세요."),
    "invalid_notice_request": ("입법예고 검색어나 번호 형식이 맞지 않습니다.", "검색어는 2~50자, 번호는 find_notice가 돌려준 seq를 사용하세요."),
    "save_failed": ("결과 파일을 저장하지 못했습니다.", "저장 경로를 생략해 홈 폴더 아래에 저장하거나 ~/Desktop/result-new.json처럼 새 파일 이름을 쓰세요. 기존 파일은 덮어쓰지 않습니다."),
}


class SetupError(ValueError):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        cause, action = GUIDANCE[code]
        self.message = message or cause
        super().__init__(f"원인: {self.message} 할 일: {action} 무료 대안: {FREE_ALTERNATIVE}")


def error_payload(exc: Exception) -> dict:
    """Never include remote exception text, submitted ids, paths or credential values."""
    code = (exc.code if isinstance(exc, SetupError) else
            "run_not_found" if isinstance(exc, KeyError) else
            "budget_exceeded" if isinstance(exc, budget.BudgetExceeded) else
            "panel_not_ready" if isinstance(exc, config.DataMissing) else "model_call_failed")
    safe = exc if isinstance(exc, SetupError) else SetupError(code)
    return {"error": str(safe), "error_code": code, "code": code, "message": safe.message,
            "next_action": GUIDANCE[code][1], "free_alternative": FREE_ALTERNATIVE,
            "retryable": code in {"model_call_failed", "budget_exceeded"}}


def mock_mode() -> bool:
    # A mock request must never silently turn into a paid request, even with keys present.
    return _trial.get() or (os.environ.get("PP_LLM_PROVIDER") or "").strip().lower() == "mock"


def panel_ready() -> bool:
    path = bundle_db.bundle_path() if personas.source() == "bundle" else config.persona_db()
    return path.is_file()


def preflight(credentials) -> None:
    if not mock_mode():
        credentials.require()
        if not panel_ready():
            from .service import RequestError
            raise RequestError(GUIDANCE["panel_not_ready"][0], "panel_not_ready")


def _build_demo_panel(path: Path, sample: int) -> None:
    """Hand-authored fictional fixtures, not a sample of the NVIDIA dataset."""
    occupations = ("사무원", "소규모 상점 경영자", "무직", "요양보호사", "곡물 재배자", "택시 운전원")
    provinces = ("서울", "부산", "경기", "강원", "전북", "제주")
    with sqlite3.connect(path) as conn:
        conn.execute(bundle_db.CREATE_SQL)
        rows = []
        for i in range(max(30, sample)):
            p = {key: "" for key in bundle_db.COLUMNS}
            p.update(id=i + 1, uuid=f"demo-{i:05d}", sex="여자" if i % 2 else "남자",
                     age=19 + i * 7 % 70, occupation=occupations[i % len(occupations)],
                     province=provinces[i % len(provinces)], district=f"{provinces[i % len(provinces)]}-가상지역",
                     education_level="고등학교", marital_status="미혼", family_type="혼자 거주",
                     housing_type="아파트", persona="무료 체험을 위해 만든 가상 인물입니다.",
                     professional_persona="지역에서 생활합니다.", family_persona="혼자 생활합니다.",
                     cultural_background="체험용 가상 설정입니다.")
            rows.append(tuple(p[key] for key in bundle_db.COLUMNS))
        conn.executemany(bundle_db.INSERT_SQL, rows)
        conn.execute(bundle_db.FTS_SQL)
        conn.execute(bundle_db.FTS_FILL_SQL)
    provenance.write_metadata(path, {"source_repo": "policy-preview-engine/demo", "revision_status": "hand_authored"})


@contextmanager
def runtime(sample: int):
    """Request-local overrides propagate to engine threads without changing process env."""
    if not mock_mode() or (panel_ready() and not _trial.get()):
        yield
        return
    with TemporaryDirectory(prefix="pp-demo-") as folder:
        path = Path(folder) / "demo.db"
        _build_demo_panel(path, sample)
        token = _panel.set(path)
        try:
            yield
        finally:
            _panel.reset(token)


def demo_panel() -> Path | None:
    return _panel.get()


def model_transport(credentials, api_transport):
    if mock_mode():
        return llm.use_transport(None, system_rules=public_rules.SYSTEM_RULES, provider_name="mock", model="mock")
    return llm.use_transport(api_transport(credentials), system_rules=public_rules.SYSTEM_RULES,
                             provider_name="anthropic", model="claude-haiku-4-5-20251001")


def mark_result(result: dict) -> dict:
    if not mock_mode():
        return result
    result.update(mode="mock", result_label=TRIAL_LABEL,
                  trial_notice=TRIAL_NOTICE)
    result["warnings"].insert(0, result["trial_notice"])
    result["clarity"] = {"available": False, "reason": "체험 모드: 외부 명료성 API를 호출하지 않았습니다."}
    if demo_panel():
        source = {"dataset": "무료 체험용 직접 작성한 가상 인물", "license": "Apache-2.0", "synthetic": True}
        result["conditions"]["source"] = source
        result["attribution"] = {"schema": attribution.SCHEMA, "sources": [attribution.generated()],
                                 "notice": "직접 작성한 무료 체험용 가상 인물과 모의 응답입니다. 실제 인구를 대표하지 않습니다."}
        result["estimate"]["attribution"] = result["attribution"]
    return result


def check_setup() -> dict:
    """Report presence only; no secret values, arbitrary env values or local paths."""
    mock = mock_mode()
    key = bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())
    panel = panel_ready()
    from . import mcp_copy
    examples = all(name in mcp_copy.EXAMPLES for name in EXAMPLES)
    problems = []
    if not mock and not key:
        problems.append(error_payload(SetupError("missing_model_key")))
    if not mock and not panel:
        problems.append(error_payload(SetupError("panel_not_ready")))
    return public_rules.envelope({"mode": "mock" if mock else "real", "ready": mock or (key and panel),
        "keys": {"anthropic_present": key, "typesafe_present": bool((os.environ.get("TYPESAFE_API_KEY") or "").strip())},
        "panel": {"available": panel, "demo_available": True}, "data": {"examples_available": examples},
        "clarity": {"mode": "skipped_free_trial" if mock else "optional",
                    "message": "무료 체험은 명료성 API를 호출하지 않습니다." if mock else "TYPESAFE_API_KEY가 있으면 선택적 명료성 점검을 합니다."},
        "free_trial_available": examples,
        "message": "무료 체험을 바로 시작할 수 있습니다." if mock else "실제 실행 준비 상태를 확인했습니다.",
        "next_action": "try_example으로 무료 예시를 보세요." if mock or problems else "estimate로 예상 비용을 확인하세요.",
        "problems": problems})


from .archived_examples import EXAMPLES


def try_example(example: str = "subway-free-ride") -> dict:
    from . import archived_examples, mcp_copy

    if example not in EXAMPLES:
        raise SetupError("input_rejected", "이 문안의 보관 결과는 없습니다. " + " / ".join(f"{key}({mcp_copy.EXAMPLES[key].title})" for key in EXAMPLES))
    result = archived_examples.load(example)
    return public_rules.envelope({"status": "completed", "mode": "archived", "result_label": result["result_label"],
        "example": example, "cost_usd": 0, "result": result,
        "available_examples": [{"id": key, "title": mcp_copy.EXAMPLES[key].title} for key in EXAMPLES]})
