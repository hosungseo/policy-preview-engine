"""Optional MCP plan and export operations, kept apart from the legacy job contract."""
from copy import deepcopy
from uuid import uuid4

from . import public_rules, review_export, service


class RunExperience:
    def estimate(self, policy_text, sample=service.DEFAULT_SAMPLE, seed=42, i_confirm_public=False, limits=None):
        with self._lock:
            return self._plans.estimate(policy_text, sample, seed, i_confirm_public, limits)

    def start_planned(self, policy_text=None, sample=None, seed=None, i_confirm_public=None, limits=None, plan_id=None):
        credentials = service.Credentials.from_env()
        overrides = dict(policy_text=policy_text, sample=sample, seed=seed,
                         i_confirm_public=i_confirm_public, limits=limits)
        if plan_id is None:  # Existing callers may still use the legacy direct-start contract.
            return self.start(policy_text, service.DEFAULT_SAMPLE if sample is None else sample,
                              42 if seed is None else seed, credentials,
                              False if i_confirm_public is None else i_confirm_public, limits)
        with self._lock:
            settings, previous = self._plans.resolve(plan_id, overrides, credentials)
            if previous:
                state = self._runs[previous]
                return public_rules.envelope({"id": previous, "status": state["status"],
                    "plan_id": plan_id, "message": "이미 시작한 계획입니다. get_run으로 같은 작업을 조회하세요."})
            credentials.require()
            # Reserve and bind atomically; _run waits for this lock before updating state.
            run_id = uuid4().hex
            initial = public_rules.envelope({"id": run_id, "status": "queued",
                "estimate": service.estimate(settings["policy_text"], settings["sample"],
                    i_confirm_public=settings["i_confirm_public"], limits=settings["limits"])})
            self._runs[run_id] = initial
            self._plans.items[plan_id]["run_id"] = run_id
            self._pool.submit(self._run, run_id, settings["policy_text"], settings["sample"],
                              settings["seed"], credentials, settings["i_confirm_public"], settings["limits"])
            return deepcopy(initial)

    def _stage(self, run_id, stage):
        with self._lock:
            self._runs[run_id]["stage"] = stage

    def save_review(self, run_id, path):
        return review_export.save(self.get(run_id), path)

