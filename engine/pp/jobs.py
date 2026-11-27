"""Single-process, in-memory jobs. Restarting the server loses run IDs and results."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from uuid import uuid4

from . import public_rules, service


class Jobs:
    def __init__(self):
        self._runs: dict[str, dict] = {}
        self._lock = Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pp-run")

    def start(self, policy_text: str, sample: int = service.DEFAULT_SAMPLE, seed: int = 42,
              credentials: service.Credentials | None = None, i_confirm_public: bool = False, limits=None) -> dict:
        service.validate(policy_text, sample, seed, i_confirm_public)
        limits = service.normalize_limits(limits)
        credentials = credentials or service.Credentials.from_env()
        credentials.require()
        run_id = uuid4().hex
        initial = public_rules.envelope({"id": run_id, "status": "queued", "estimate": service.estimate(policy_text, sample, i_confirm_public=i_confirm_public, limits=limits)})
        with self._lock:
            self._runs[run_id] = initial
        self._pool.submit(self._run, run_id, policy_text, sample, seed, credentials, i_confirm_public, limits)
        return deepcopy(initial)

    def _run(self, run_id, policy_text, sample, seed, credentials, i_confirm_public, limits):
        with self._lock:
            self._runs[run_id] = {**self._runs[run_id], "status": "running"}
        try:
            result = service.run_policy(policy_text, sample=sample, seed=seed, credentials=credentials, i_confirm_public=i_confirm_public, limits=limits)
            update = {"status": "completed", "result": result}
        except Exception as exc:
            update = {"status": "failed", "error": "실행 실패: 패널 DB, 모델 키·잔액·연결을 확인하세요. "
                      "원격 오류 원문은 키 보호를 위해 저장하지 않습니다."}
            if hasattr(exc, "budget_snapshot"):
                update["budget"] = exc.budget_snapshot
        with self._lock:
            self._runs[run_id] = {**self._runs[run_id], **update}

    def get(self, run_id: str) -> dict:
        with self._lock:
            if run_id not in self._runs:
                raise KeyError("Unknown run id (jobs are lost on server restart)")
            return deepcopy(self._runs[run_id])

    def close(self):
        self._pool.shutdown(wait=True)
