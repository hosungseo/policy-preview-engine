"""One small orchestration function shared by CLI, HTTP and MCP; no account or key storage."""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from . import analyze_llm, attribution, budget, config, diagnostics, jev, jev_panel, llm, panel_provider, personas, policy_groups, public_rules, provenance, react, segment, visit_shared
from . import mcp_setup
from . import run_progress
from . import numbers

DEFAULT_SAMPLE = 200
MAX_SAMPLE = panel_provider.MAX_N
MAX_CHARS = 30_000
MODEL = "claude-haiku-4-5-20251001"


class RequestError(mcp_setup.SetupError):
    def __init__(self, message: str, code: str = "input_rejected"):
        super().__init__(code, message)


@dataclass(frozen=True)
class Credentials:
    anthropic: str = field(default="", repr=False)
    typesafe: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("ANTHROPIC_API_KEY", ""), os.environ.get("TYPESAFE_API_KEY", ""))

    def require(self):
        if not mcp_setup.mock_mode() and not self.anthropic.strip():
            raise RequestError("실제 실행용 Anthropic API 키가 없습니다.", "missing_model_key")


def validate(policy_text: str, sample: int = DEFAULT_SAMPLE, seed: int = 42, i_confirm_public: bool = False) -> None:
    if not isinstance(policy_text, str) or not policy_text.strip():
        raise RequestError("정책 문안(policy_text)을 비어 있지 않은 글로 넣으세요.")
    if type(i_confirm_public) is not bool:
        raise RequestError("공개 확인(i_confirm_public)은 true 또는 false로 넣으세요.")
    problem = public_rules.input_problem(policy_text, i_confirm_public)
    if problem:
        raise RequestError(problem + " " + public_rules.WARNING)
    if len(policy_text) > MAX_CHARS:
        raise RequestError(f"문안이 {MAX_CHARS}자를 넘습니다. 확인할 범위를 나눠 넣으세요.")
    if type(sample) is not int or not 1 <= sample <= MAX_SAMPLE:
        raise RequestError(f"합성 프로필 수(sample)는 1~{MAX_SAMPLE} 사이 정수로 넣으세요.")
    if type(seed) is not int or not 0 <= seed <= 2_147_483_647:
        raise RequestError("추출 기준값(seed)은 0~2147483647 사이 정수로 넣으세요.")


def normalize_limits(limits=None):
    if isinstance(limits, budget.Limits):
        limits = asdict(limits)
    if limits is not None and (not isinstance(limits, dict) or limits.keys() - asdict(budget.Limits()).keys()):
        raise RequestError("비용 한도(limits)에 지원하지 않는 항목이 있습니다.")
    try:
        values = limits or {}
        if any(isinstance(v, bool) for v in values.values()) or values.get("max_cost_usd", 10) is None:
            raise ValueError("a finite monetary cap is required")
        return budget.Limits(**values)
    except (TypeError, ValueError):
        raise RequestError("비용 상한은 0 이상의 유한한 숫자, 호출·토큰·재시도·동시 실행 한도는 정수로 넣으세요.") from None


def normalize_conditions(conditions=None) -> list[dict]:
    try:
        return policy_groups.normalize_conditions(conditions)
    except policy_groups.ConditionError as exc:
        raise RequestError(str(exc)) from None


def normalize_decision_sample(value=None):
    try:
        return numbers.decision_sample(value)
    except ValueError as exc:
        raise RequestError(str(exc)) from None


def normalize_baseline(policy_text, baseline=None):
    try:
        return numbers.baseline_for(policy_text, baseline)
    except ValueError as exc:
        raise RequestError(str(exc)) from None


def estimate(policy_text: str, sample: int = DEFAULT_SAMPLE, *, i_confirm_public: bool = False,
             limits=None, conditions=None, decision_sample=None, credentials=None, baseline=None) -> dict:
    """Transparent planning assumptions, never a quote or a measured runtime guarantee."""
    validate(policy_text, sample, i_confirm_public=i_confirm_public)
    limits = normalize_limits(limits)
    norm_conditions = normalize_conditions(conditions)
    decision_sample = normalize_decision_sample(decision_sample)
    decision = numbers.plan(policy_text, sample, decision_sample, credentials or Credentials.from_env())
    baseline = normalize_baseline(policy_text, baseline)
    # Budget all reaction prompts and an upper bound for grouping, outreach and QA.
    input_tokens = sample * (len(policy_text) + 1200) + sample * 1400 + 16000
    output_tokens = sample * 550 + 16000
    usd = 0 if mcp_setup.mock_mode() else (input_tokens * 1.0 + output_tokens * 5.0) / 1_000_000
    mock = mcp_setup.mock_mode()
    distribution_seconds = 0 if mock or not decision["available"] else math.ceil(decision["n"] / 18)
    seconds = 1 if mock else math.ceil(sample / 8) * 6 + 90 + distribution_seconds
    credit = ({"schema": attribution.SCHEMA, "sources": [attribution.generated()],
               "notice": "0원 체험의 가상 인물·모의 응답입니다. 실제 분석 결과가 아닙니다."}
              if mock and not mcp_setup.panel_ready() else attribution.build())
    hash_inputs = {"policy": policy_text, "sample": sample, "limits": asdict(limits)}
    hash_inputs["decision_sample"] = decision_sample
    if baseline:
        hash_inputs["baseline"] = baseline
    if norm_conditions:
        hash_inputs["conditions"] = norm_conditions
    return public_rules.envelope({"sample": sample, "policy_chars": len(policy_text), "model": "mock" if mcp_setup.mock_mode() else MODEL,
            "input_hash": provenance.input_hash(hash_inputs),
            "budget_limits": asdict(limits), "attribution": credit,
            "mode": "mock" if mock else "real", "requires_consent": not mock,
            **({"result_label": mcp_setup.TRIAL_LABEL, "trial_notice": mcp_setup.TRIAL_NOTICE} if mock else {}),
            "target_conditions": norm_conditions,
            "decision_sample": decision_sample,
            "baseline": baseline or {"available": False, "notice": "동일 문항 과거 공개 기준선 없음"},
            "stages": {"distribution": decision,
                       "reasons": {"n": sample, "model": "mock" if mock else MODEL,
                                   "estimated_cost_usd": {"low": round(usd * .5, 4), "high": round(usd * 2, 4)}}},
            "missing_people": visit_shared.missing_people(policy_text),
            "estimated_cost_usd": {"low": round(usd * .5 + decision["estimated_cost_usd"]["low"], 4), "high": round(usd * 2 + decision["estimated_cost_usd"]["high"], 4)},
            "estimated_seconds": {"low": seconds, "high": seconds * 3},
            "assumptions": {"input_usd_per_million": 1, "output_usd_per_million": 5,
                            "input_tokens": input_tokens, "output_tokens": output_tokens, "workers": min(8, limits.max_concurrency)},
            "warnings": [public_rules.WARNING],
            "budget_notice": "계획용 추정이며 청구액·완료 시간을 보장하지 않습니다. 재시도·문안 길이에 따라 늘어납니다. "
                      "분포 판단과 이유 수집 비용을 분리했으며 선택적 Jev 명료성 점검 비용은 포함하지 않습니다."})


def _api_transport(credentials: Credentials):
    def call(task, system, prompt, model, timeout):
        body = json.dumps({"model": MODEL, "max_tokens": budget.output_limit(16384 if task != "react" else 1024),
                           "system": system, "messages": [{"role": "user", "content": prompt}]}).encode()
        request = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": credentials.anthropic, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
            budget.record_usage(result.get("usage"))
            return "\n".join(c["text"] for c in result["content"] if c.get("type") == "text")
        except budget.BudgetExceeded:
            raise
        except Exception:
            # Provider response bodies and exception reprs may echo credentials; never export them.
            raise llm.LLMError("Model API call failed; check key, balance, network and model access") from None
    return call


def _run_policy(policy_text: str, *, sample: int = DEFAULT_SAMPLE, seed: int = 42,
               credentials: Credentials | None = None, i_confirm_public: bool = False, limits=None,
               conditions=None, decision_sample=None, baseline=None) -> dict:
    """Text -> sampled reactions -> grounded issues -> consultation plan, using the existing engine."""
    validate(policy_text, sample, seed, i_confirm_public)
    norm_conditions = normalize_conditions(conditions)
    credentials = credentials or Credentials.from_env()
    decision_sample = normalize_decision_sample(decision_sample)
    decision = numbers.plan(policy_text, sample, decision_sample, credentials)
    baseline = normalize_baseline(policy_text, baseline)
    mcp_setup.preflight(credentials)
    run_progress.report("preparing")
    title = policy_text.strip().splitlines()[0][:120]
    # Explicit DBs take precedence. Otherwise use the portable, attributed 20k bundle.
    db = mcp_setup.demo_panel() or config.persona_db()
    panel_version = "external-db-unversioned"
    if not mcp_setup.demo_panel() and personas.source() == "bundle":
        from . import bundle_db
        db = bundle_db.ensure()
        panel_version = db.stem
    sampled, active_conditions, grouping_basis = policy_groups.select_panel(
        policy_text, sample, seed, norm_conditions, db
    )
    people = sampled["people"]
    if not people:
        raise RequestError("No panel members match the request")
    source = provenance.artifact(db)
    if panel_version != "external-db-unversioned":
        from . import bundle_db
        source = provenance.artifact(bundle_db.bundle_path(), compressed=True)
    panel_version = source["panel_version"]
    sampling_inputs = {"sample": sample, "affected": sample // 4, "seed": seed}
    sampling_inputs["decision_sample"] = decision_sample
    sampling_inputs["distribution_fallback"] = decision["fallback"]
    if norm_conditions:
        sampling_inputs["conditions"] = norm_conditions
    inputs = provenance.execution_inputs(
        {"text": policy_text, "public_confirmed": i_confirm_public},
        source, sampling_inputs, asdict(limits),
        models={"provider": "mock" if mcp_setup.mock_mode() else "anthropic", "model": "mock" if mcp_setup.mock_mode() else MODEL,
                "distribution_provider": decision["provider"], "distribution_model": decision["model"],
                "distribution_fallback": decision["fallback"],
                "clarity_provider": "typesafe" if credentials.typesafe and not mcp_setup.mock_mode() else None,
                "clarity_model": (os.environ.get("PP_JEV_MODEL") or "jev-latest") if credentials.typesafe and not mcp_setup.mock_mode() else None})
    if baseline:
        inputs["baseline"] = baseline
    selection_receipt = sampled["selection"]
    selection_receipt["data"] = source
    # Provider's public province labels are converted back to the engine's raw vocabulary.
    for p in people:
        # Profiles contain synthetic names; remove those before any model sees them too.
        for key in ("persona", "profile"):
            p[key] = public_rules.PERSON.sub("이 집단의 구성원", p[key])
        p["name"] = "이름 없는 집단 구성원"
        p["province"] = config.to_raw_province(p["province"])
        p["panel"] = "aff" if p["kind"] == "affected" else "rep"
        # The provider profile already contains the original clipped long-form narratives.
        lines = p["profile"].splitlines()
        p["professional_persona"] = lines[8] if len(lines) > 8 else ""
        p["family_persona"] = lines[9] if len(lines) > 9 else ""
        p["cultural_background"] = lines[10] if len(lines) > 10 else ""
    segments = segment.split_segments(policy_text)
    run_progress.report("reactions")
    # Solar Decide must retain its provider-owned credential; an empty request key disables TypeSafe disk fallback.
    with mcp_setup.model_transport(credentials, _api_transport), jev.use_key(None if mcp_setup.mock_mode() or jev.provider() in {"upstage", "mock"} else credentials.typesafe), jev.use_mock(mcp_setup.mock_mode()):
        quant_rows = None
        quant_selection = None
        if decision["available"]:
            quant = panel_provider.provide({"n": decision_sample, "affected": 0, "seed": seed}, db)
            quant_selection = quant["selection"]
            quant_rows = numbers.judge(policy_text, quant["people"])
            decision["n"] = len(quant_rows)
        # Existing reaction code is resumable on disk; its private temporary output is deleted on exit.
        with TemporaryDirectory(prefix="pp-") as folder:
            reactions, failures = react.run_reactions(people, policy_text, Path(folder) / "reactions.jsonl")
        if not reactions:
            raise llm.LLMError("No panel reactions succeeded; check the model key, balance and network")
        reactions.sort(key=lambda r: r["uuid"])
        for i, r in enumerate(reactions, 1):
            r["rid"] = f"r{i}"
        mismatches = react.verify_quotes(reactions, policy_text, segments)
        by_uuid = {p["uuid"]: p for p in people}
        # Keep issue order tied to source clauses, never member counts or stance.
        run_progress.report("questions")
        raw_issues = analyze_llm.cluster_issues(reactions, title)
        by_rid = {r["rid"]: r for r in reactions}
        clause_order = {s["id"]: i for i, s in enumerate(segments)}
        raw_issues.sort(key=lambda it: (
            min((clause_order.get(by_rid[rid].get("segment_id"), len(segments))
                 for rid in it["member_ids"]), default=len(segments)), it["title"]))
        issues = [{**it, "id": f"i{i}"} for i, it in enumerate(raw_issues, 1)]
        qa = analyze_llm.plan_qa(issues, title, consultation=True)
        clarity = {"available": False, "reason": "TYPESAFE_API_KEY 없음: 명료성·안내 누락 점검 미실행"}
        if credentials.typesafe and not mcp_setup.mock_mode():
            try:
                checked = jev_panel.check_clarity(title, policy_text, segments)
                labels = {item["key"]: item["label"] for item in checked["indicators"]}
                clarity = {"available": True,
                    "clauses": [{"segment_id": row["segment_id"],
                                 "questions": [labels[key] + "에 관해 문안을 어떻게 읽는지 확인하세요."
                                               for key in sorted(row["flags"])]}
                                for row in checked["clauses"]],
                    "document_questions": [row["label"] + "에 필요한 안내가 문안에 있는지 확인하세요."
                                           for row in checked["document"]]}

            except budget.BudgetExceeded:
                raise
            except Exception:
                clarity = {"available": False, "reason": "Jev 호출 실패: 키·잔액·연결을 확인하세요"}
    run_progress.report("finalizing")
    public, warnings, diag, limits_notes = policy_groups.build_consultation_views(
        policy_text, segments, people, reactions, issues, qa, clarity, active_conditions, grouping_basis
    )
    reason_rows = numbers.reaction_rows(people, reactions)
    numeric_rows = (quant_rows + [r for r in reason_rows if r["panel"] == "affected"]) if quant_rows is not None else reason_rows
    numeric = numbers.build(numeric_rows, population=sampled["source"].get("population"), decision=decision, reason_n=len(reactions), baseline=baseline)
    numeric["slice_data"]["reason_rows"] = reason_rows
    numeric["overall"]["reasons_by_panel"] = {panel: sum(r["panel"] == panel for r in reason_rows)
                                               for panel in ("representative", "affected")}
    numeric["overall"]["distribution_selection"] = quant_selection
    diag["scope"] = "qualitative_reasons"
    diag["numeric_variability"] = numeric["overall"]["variability"]
    old_note = diag.get("variability_note")
    if old_note:
        diag["variability_note"] = "정성 이유 수집: " + old_note
        warnings = [diag["variability_note"] if warning == old_note else warning for warning in warnings]
    limits_notes = ["찬반 숫자는 계산된 overall·by_group에서만 제공합니다. 문장 모델의 이유에서 새 비율이나 순위를 만들지 않습니다."
                    if note.startswith("반응의 비율·건수·순위는 제공하지 않습니다.") else note for note in limits_notes]
    if decision["fallback"]:
        warnings.append(decision["notice"])
    return public_rules.envelope({"schema": numbers.SCHEMA, "synthetic": True,
            "warnings": warnings, "diagnostics": diag,
            "input_hash": provenance.input_hash(inputs), "execution_inputs": inputs,
            "selection": selection_receipt, "attribution": attribution.build(source),
            "budget": budget.current().snapshot(),
            "conditions": {"model": "mock" if mcp_setup.mock_mode() else MODEL, "seed": seed, "panel_version": panel_version,
                           "distribution_model": decision["model"], "distribution_provider": decision["provider"],
                           "distribution_fallback": decision["fallback"],
                           "source": sampled["source"], "public_confirmed": i_confirm_public,
                           "reaction_failures": bool(failures), "unverified_quotes": bool(mismatches),
                           "grouping_basis": grouping_basis, "confirmed_conditions": bool(norm_conditions),
                           "panel_separation": True},
            "estimate": estimate(policy_text, sample, i_confirm_public=i_confirm_public, limits=limits,
                                 conditions=conditions, decision_sample=decision_sample, credentials=credentials, baseline=baseline),
            **public,
            **numeric,
            "limits": limits_notes})


def run_policy(policy_text: str, *, sample: int = DEFAULT_SAMPLE, seed: int = 42,
               credentials: Credentials | None = None, i_confirm_public: bool = False, limits=None,
               conditions=None, decision_sample=None, baseline=None) -> dict:
    validate(policy_text, sample, seed, i_confirm_public)
    limits = normalize_limits(limits)
    decision_sample = normalize_decision_sample(decision_sample)
    baseline = normalize_baseline(policy_text, baseline)
    ledger = budget.Budget(limits)
    with ledger.scope(), budget.use_prices({"llm": (1.0, 5.0), "jev": (jev.price_per_m_input(), 0.0)}), mcp_setup.runtime(max(sample, decision_sample) if mcp_setup.mock_mode() else sample):
        try:
            return mcp_setup.mark_result(_run_policy(policy_text, sample=sample, seed=seed, credentials=credentials,
                               i_confirm_public=i_confirm_public, limits=limits, conditions=conditions, decision_sample=decision_sample, baseline=baseline))
        except Exception as exc:
            exc.budget_snapshot = ledger.snapshot()
            raise
