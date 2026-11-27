"""Single-process, in-memory jobs. Restarting the server loses run IDs and results."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from uuid import uuid4
from time import monotonic

from . import run_progress, summary_card
from .run_experience import RunExperience
from .run_plans import Plans

from . import public_rules, service, mcp_setup


class Jobs(RunExperience):
    def __init__(self):
        self._runs: dict[str, dict] = {}
        self._lock = Lock()
        self._plans = Plans()
        self._started_at = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pp-run")

    def start(self, policy_text: str, sample: int = service.DEFAULT_SAMPLE, seed: int = 42,
              credentials: service.Credentials | None = None, i_confirm_public: bool = False, limits=None,
              conditions=None) -> dict:
        service.validate(policy_text, sample, seed, i_confirm_public)
        limits = service.normalize_limits(limits)
        service.normalize_conditions(conditions)
        credentials = credentials or service.Credentials.from_env()
        mcp_setup.preflight(credentials)
        run_id = uuid4().hex
        initial = public_rules.envelope({
            "id": run_id, "status": "queued",
            "mode": "mock" if mcp_setup.mock_mode() else "real",
            **({"result_label": mcp_setup.TRIAL_LABEL, "trial_notice": mcp_setup.TRIAL_NOTICE} if mcp_setup.mock_mode() else {}),
            "estimate": service.estimate(policy_text, sample, i_confirm_public=i_confirm_public,
                                         limits=limits, conditions=conditions),
        })
        with self._lock:
            self._runs[run_id] = initial
        self._pool.submit(self._run, run_id, policy_text, sample, seed, credentials, i_confirm_public,
                          limits, deepcopy(conditions))
        return deepcopy(initial)

    def _run(self, run_id, policy_text, sample, seed, credentials, i_confirm_public, limits, conditions=None):
        with self._lock:
            self._runs[run_id] = {**self._runs[run_id], "status": "running", "stage": "preparing"}
            self._started_at[run_id] = monotonic()
        try:
            with run_progress.track(lambda stage: self._stage(run_id, stage)):
                result = service.run_policy(policy_text, sample=sample, seed=seed, credentials=credentials, i_confirm_public=i_confirm_public, limits=limits, conditions=conditions)
            update = {"status": "completed", "result": result}
        except Exception as exc:
            update = {"status": "failed", **mcp_setup.error_payload(exc)}
            if hasattr(exc, "budget_snapshot"):
                update["budget"] = exc.budget_snapshot
        with self._lock:
            self._runs[run_id] = {**self._runs[run_id], **update}

    def get(self, run_id: str, view="full") -> dict:
        if view not in {"summary", "full"}:
            raise service.RequestError("view는 summary 또는 full이어야 합니다.")
        with self._lock:
            if run_id not in self._runs:
                if run_id in self._plans.items:
                    raise mcp_setup.SetupError("plan_id_as_run_id")
                raise KeyError("작업을 찾을 수 없습니다. ID가 다르거나 서버 재시작으로 사라졌을 수 있습니다. 저장본을 확인하거나 다시 견적을 내세요.")
            state = deepcopy(self._runs[run_id])
            started_at = self._started_at.get(run_id)
        state = run_progress.snapshot(state, started_at)
        if state["status"] == "completed":
            state["save_notice"] = summary_card.SAVE_NOTICE
        return summary_card.response(state) if view == "summary" else state

    def close(self):
        self._pool.shutdown(wait=True)
