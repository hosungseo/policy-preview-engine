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

from . import analyze_llm, attribution, budget, config, diagnostics, jev, jev_panel, llm, panel_provider, personas, public_rules, provenance, react, segment
from . import mcp_setup

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
        raise RequestError("policy_text must be non-empty UTF-8 text")
    if type(i_confirm_public) is not bool:
        raise RequestError("i_confirm_public must be a boolean")
    problem = public_rules.input_problem(policy_text, i_confirm_public)
    if problem:
        raise RequestError(problem + " " + public_rules.WARNING)
    if len(policy_text) > MAX_CHARS:
        raise RequestError(f"policy_text exceeds {MAX_CHARS} characters; split the document explicitly")
    if type(sample) is not int or not 1 <= sample <= MAX_SAMPLE:
        raise RequestError(f"sample must be an integer between 1 and {MAX_SAMPLE}")
    if type(seed) is not int or not 0 <= seed <= 2_147_483_647:
        raise RequestError("seed must be an integer between 0 and 2147483647")


def normalize_limits(limits=None):
    if isinstance(limits, budget.Limits):
        limits = asdict(limits)
    if limits is not None and (not isinstance(limits, dict) or limits.keys() - asdict(budget.Limits()).keys()):
        raise RequestError("Unknown budget limits")
    try:
        values = limits or {}
        if any(isinstance(v, bool) for v in values.values()) or values.get("max_cost_usd", 10) is None:
            raise ValueError("a finite monetary cap is required")
        return budget.Limits(**values)
    except (TypeError, ValueError):
        raise RequestError("Invalid budget limits; use finite nonnegative cost and integer call/token/retry/concurrency caps") from None


def estimate(policy_text: str, sample: int = DEFAULT_SAMPLE, *, i_confirm_public: bool = False, limits=None) -> dict:
    """Transparent planning assumptions, never a quote or a measured runtime guarantee."""
    validate(policy_text, sample, i_confirm_public=i_confirm_public)
    limits = normalize_limits(limits)
    # Budget all reaction prompts and an upper bound for grouping, outreach and QA.
    input_tokens = sample * (len(policy_text) + 1200) + sample * 1400 + 16000
    output_tokens = sample * 550 + 16000
    usd = 0 if mcp_setup.mock_mode() else (input_tokens * 1.0 + output_tokens * 5.0) / 1_000_000
    seconds = math.ceil(sample / 8) * 6 + 90
    return public_rules.envelope({"sample": sample, "policy_chars": len(policy_text), "model": "mock" if mcp_setup.mock_mode() else MODEL,
            "input_hash": provenance.input_hash({"policy": policy_text, "sample": sample, "limits": asdict(limits)}),
            "budget_limits": asdict(limits), "attribution": attribution.build(),
            "estimated_cost_usd": {"low": round(usd * .5, 4), "high": round(usd * 2, 4)},
            "estimated_seconds": {"low": seconds, "high": seconds * 3},
            "assumptions": {"input_usd_per_million": 1, "output_usd_per_million": 5,
                            "input_tokens": input_tokens, "output_tokens": output_tokens, "workers": min(8, limits.max_concurrency)},
            "warnings": [public_rules.WARNING],
            "budget_notice": "계획용 추정이며 청구액·완료 시간을 보장하지 않습니다. 재시도·문안 길이에 따라 늘어납니다. "
                      "선택적 Jev 명료성 점검 비용은 포함하지 않습니다."})


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
               credentials: Credentials | None = None, i_confirm_public: bool = False, limits=None) -> dict:
    """Text -> sampled reactions -> grounded issues -> consultation plan, using the existing engine."""
    validate(policy_text, sample, seed, i_confirm_public)
    credentials = credentials or Credentials.from_env()
    mcp_setup.preflight(credentials)
    title = policy_text.strip().splitlines()[0][:120]
    # Explicit DBs take precedence. Otherwise use the portable, attributed 20k bundle.
    db = mcp_setup.demo_panel() or config.persona_db()
    panel_version = "external-db-unversioned"
    if not mcp_setup.demo_panel() and personas.source() == "bundle":
        from . import bundle_db
        db = bundle_db.ensure()
        panel_version = db.stem
    sampled = panel_provider.provide({"policy_text": policy_text, "n": sample,
                                      "affected": sample // 4, "seed": seed}, db)
    people = sampled["people"]
    if not people:
        raise RequestError("No panel members match the request")
    source = provenance.artifact(db)
    if panel_version != "external-db-unversioned":
        from . import bundle_db
        source = provenance.artifact(bundle_db.bundle_path(), compressed=True)
    panel_version = source["panel_version"]
    inputs = provenance.execution_inputs(
        {"text": policy_text, "public_confirmed": i_confirm_public},
        source, {"sample": sample, "affected": sample // 4, "seed": seed}, asdict(limits),
        models={"provider": "mock" if mcp_setup.mock_mode() else "anthropic", "model": "mock" if mcp_setup.mock_mode() else MODEL,
                "clarity_provider": "typesafe" if credentials.typesafe and not mcp_setup.mock_mode() else None,
                "clarity_model": (os.environ.get("PP_JEV_MODEL") or "jev-latest") if credentials.typesafe and not mcp_setup.mock_mode() else None})
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
    with mcp_setup.model_transport(credentials, _api_transport), jev.use_key(None if mcp_setup.mock_mode() else credentials.typesafe):
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
    reaction_segments = {r["rid"]: r.get("segment_id") for r in reactions}
    issue_segments = {it["id"]: {reaction_segments[rid] for rid in it["member_ids"]} for it in issues}
    clause_issues = [{**s, "issues": [it["id"] for it in issues if s["id"] in issue_segments[it["id"]]]}
                     for s in segments]
    missing = [{"kind": "uncovered_clause", "segment_id": c["id"],
                "reason": "검증된 인용으로 연결된 쟁점이 없어 실제 의견수렴에서 별도 확인 필요"}
               for c in clause_issues if not c["issues"]]
    missing += [{"kind": "panel_limit", "group": "19세 미만", "reason": "원본 합성 패널에 포함되지 않음"},
                {"kind": "panel_limit", "group": "소득별 관점", "reason": "패널에 소득 정보 없음"}]
    # Group by occupation without exporting individual records, votes, counts, or rankings.
    group_reactions = []
    outreach = []
    # Follow source clause order, with first occurrence in the panel as a stable tie breaker.
    # Never use the number or intensity of reactions to order groups.
    ordered_groups = list(dict.fromkeys(p["occupation"] for p in people))
    ordered_groups.sort(key=lambda group: min(
        (clause_order.get(r.get("segment_id"), len(segments)) for r in reactions
         if by_uuid[r["uuid"]]["occupation"] == group), default=len(segments)))
    for group in ordered_groups:
        rows = [r for r in reactions if by_uuid[r["uuid"]]["occupation"] == group]
        group_reactions.append({"group": group,
            "status": "AI가 상상한 반응" if rows else "반응을 만들지 못함",
            "reactions": [{k: r[k] for k in ("reason", "trigger_quote", "quote_verified", "segment_id", "suggestion")}
                          for r in rows]})
        if any(not r["would_comment"] for r in rows):
            missing.append({"kind": "underheard_group", "group": group,
                            "reason": "스스로 의견을 내기 어려울 수 있다는 AI 짐작; 현장 확인 필요"})
            outreach.append({"group": group, "method": "현장 방문 또는 중간 다리를 통한 짧은 질문",
                             "where": "해당 집단을 만나는 지역 지원 담당 부서에 접점을 문의",
                             "question": "의견을 내는 데 무엇이 걸리고 어떤 통로가 편한가요?"})
    who = []
    for it in issues:
        members = {by_uuid[by_rid[rid]["uuid"]]["occupation"] for rid in it["member_ids"]}
        groups = [group for group in ordered_groups if group in members]
        questions = [q["question"] for q in qa if q["issue_id"] == it["id"]]
        who.append({"issue_id": it["id"], "groups": groups,
                    "questions": questions or ["이 조항으로 생활에서 무엇이 달라지며 무엇을 확인해야 하나요?"],
                    "basis": "문안 조항에 연결된 집단; 현장 확인 필요"})
    diag = {"reliability_findings": diagnostics.question_reliability_findings(policy_text, []), "warnings": []}
    # This route gathers prose, not quantitative survey answers; report unavailable metrics honestly.
    diag["status"] = "qualitative_only"
    diag["note"] = "정량 확률 응답을 수집하지 않아 분산·집단 차이 진단은 계산하지 않았습니다."
    warnings = [public_rules.WARNING, diag["note"]]
    warnings += [item["message"] for item in diag["reliability_findings"] + diag["warnings"]]
    public = public_rules.check_output({
        "clauses": clause_issues,
        "issues": [{k: it[k] for k in ("id", "title", "summary")} for it in issues],
        "missing_perspectives": missing, "who_to_ask": who, "outreach": outreach,
        "questions": qa, "group_reactions": group_reactions,
        "clarity": clarity,
    }, policy_text, warnings)
    return public_rules.envelope({"schema": "pp.run/2", "synthetic": True,
            "warnings": warnings, "diagnostics": diag,
            "input_hash": provenance.input_hash(inputs), "execution_inputs": inputs,
            "selection": selection_receipt, "attribution": attribution.build(source),
            "budget": budget.current().snapshot(),
            "conditions": {"model": "mock" if mcp_setup.mock_mode() else MODEL, "seed": seed, "panel_version": panel_version,
                           "source": sampled["source"], "public_confirmed": i_confirm_public,
                           "reaction_failures": bool(failures), "unverified_quotes": bool(mismatches)},
            "estimate": estimate(policy_text, sample, i_confirm_public=i_confirm_public, limits=limits), **public,
            "limits": ["반응은 합성 프로필마다 별도 호출로 만들고 공개 시 직업 집단으로 묶었습니다.",
                       "당사자 목록은 문안의 모든 조항에서 추출한 전수 목록이 아닙니다.",
                       "반응의 비율·건수·순위는 제공하지 않습니다. 비용 산정용 sample은 의견의 수가 아닙니다.",
                       "이 모델 구성의 오차는 측정되지 않았습니다. 실제 당사자에게 확인하세요.",
                       "Jev 명료성 점검은 조항 맥락 4,000자·전체 안내 6,000자를 사용합니다.",
                       "큰 문안의 계층 요약에서 쟁점을 놓칠 수 있습니다."]})


def run_policy(policy_text: str, *, sample: int = DEFAULT_SAMPLE, seed: int = 42,
               credentials: Credentials | None = None, i_confirm_public: bool = False, limits=None) -> dict:
    validate(policy_text, sample, seed, i_confirm_public)
    limits = normalize_limits(limits)
    ledger = budget.Budget(limits)
    with ledger.scope(), budget.use_prices({"llm": (1.0, 5.0), "jev": (jev.PRICE_PER_M_INPUT, 0.0)}), mcp_setup.runtime(sample):
        try:
            return mcp_setup.mark_result(_run_policy(policy_text, sample=sample, seed=seed, credentials=credentials,
                               i_confirm_public=i_confirm_public, limits=limits))
        except Exception as exc:
            exc.budget_snapshot = ledger.snapshot()
            raise
