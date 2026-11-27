"""Observed stage completion, isolated per worker context (never guessed percentages)."""
from time import monotonic
from contextlib import contextmanager
from contextvars import ContextVar

_callback = ContextVar('pp_run_progress', default=None)
STAGES = ('preparing', 'reactions', 'questions', 'finalizing')
LABELS = dict(queued='실행 대기 중', preparing='문안·패널 확인 중', reactions='가상 반응 생성 중',
              questions='쟁점·현장 질문 정리 중', finalizing='결과·근거 정리 중', completed='완료', failed='실패')


def report(stage):
    callback = _callback.get()
    if callback:
        callback(stage)


@contextmanager
def track(callback):
    token = _callback.set(callback)
    try:
        yield
    finally:
        _callback.reset(token)


def snapshot(state, started_at):
    status = state["status"]
    observed = state.get("stage", "preparing")
    stage = status if status in {"queued", "completed", "failed"} else observed
    done = len(STAGES) if status == "completed" else (STAGES.index(observed) if status != "queued" and observed in STAGES else 0)
    state.update(stage=stage, stage_label=LABELS[stage], progress={"completed_stages": done, "total_stages": len(STAGES),
                 "basis": "관측한 단계 완료 수입니다. 작업량 비율이 아닙니다."},
                 poll_after_ms=0 if status in {"completed", "failed"} else 1500)
    elapsed = monotonic() - started_at if started_at is not None else 0
    seconds = state.get("estimate", {}).get("estimated_seconds", {})
    state["estimated_remaining_seconds"] = ({"low": 0, "high": 0} if status in {"completed", "failed"} else
        {"low": max(0, int(seconds.get("low", 0) - elapsed)), "high": max(0, int(seconds.get("high", 0) - elapsed)),
         "basis": "견적에서 경과 시간을 뺀 예상 범위이며 보장 시간이 아닙니다. 대기열 시간은 알 수 없습니다."})
    return state
