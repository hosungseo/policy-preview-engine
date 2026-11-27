"""Optional MCP plan and export operations, kept apart from the legacy job contract."""
from copy import deepcopy
from uuid import uuid4

from . import public_rules, review_export, service, mcp_setup


class RunExperience:
    def try_example(self, example="subway-free-ride"):
        state = mcp_setup.try_example(example)
        state["id"] = uuid4().hex
        with self._lock:
            self._runs[state["id"]] = state
        return self.get(state["id"], view="summary")

    def estimate(self, policy_text, sample=service.DEFAULT_SAMPLE, seed=42, i_confirm_public=False, limits=None, conditions=None):
        with self._lock:
            return self._plans.estimate(policy_text, sample, seed, i_confirm_public, limits, conditions)

    def start_planned(self, policy_text=None, sample=None, seed=None, i_confirm_public=None, limits=None, plan_id=None, conditions=None):
        credentials = service.Credentials.from_env()
        overrides = dict(policy_text=policy_text, sample=sample, seed=seed,
                         i_confirm_public=i_confirm_public, limits=limits, conditions=conditions)
        if plan_id is None:  # Existing callers may still use the legacy direct-start contract.
            return self.start(policy_text, service.DEFAULT_SAMPLE if sample is None else sample,
                              42 if seed is None else seed, credentials,
                              False if i_confirm_public is None else i_confirm_public, limits, conditions)
        with self._lock:
            settings, previous = self._plans.resolve(plan_id, overrides, credentials)
            if previous:
                state = self._runs[previous]
                return public_rules.envelope({"id": previous, "status": state["status"],
                    "plan_id": plan_id, "message": "이미 시작한 계획입니다. get_run으로 같은 작업을 조회하세요."})
            mcp_setup.preflight(credentials)
            # Reserve and bind atomically; _run waits for this lock before updating state.
            run_id = uuid4().hex
            initial = public_rules.envelope({"id": run_id, "status": "queued",
                "mode": "mock" if mcp_setup.mock_mode() else "real",
                **({"result_label": mcp_setup.TRIAL_LABEL, "trial_notice": mcp_setup.TRIAL_NOTICE} if mcp_setup.mock_mode() else {}),
                "estimate": service.estimate(settings["policy_text"], settings["sample"],
                    i_confirm_public=settings["i_confirm_public"], limits=settings["limits"], conditions=settings["conditions"])})
            self._runs[run_id] = initial
            self._plans.items[plan_id]["run_id"] = run_id
            self._pool.submit(self._run, run_id, settings["policy_text"], settings["sample"],
                              settings["seed"], credentials, settings["i_confirm_public"], settings["limits"], deepcopy(settings["conditions"]))
            return deepcopy(initial)

    def _stage(self, run_id, stage):
        with self._lock:
            self._runs[run_id]["stage"] = stage

    def save_review(self, run_id, path=None):
        return review_export.save(self.get(run_id), path)

