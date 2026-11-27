"""Tests for MCP UX 3 (ux-core): visit_shared extraction, policy-condition grouping, and safeguards."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pp import api, attribution, cli, llm, mcp, policy_groups, provenance, public_rules, service, visit_shared
from pp.jobs import Jobs
from ppservice.survey import visit
from test_public_interfaces import POLICY, SECRET, fake_models, wait_job  # noqa: F401

SUBWAY_POLICY = json.loads((Path(__file__).resolve().parents[1] / "policies" / "subway-free-ride.json").read_text(encoding="utf-8"))["text"]
RURAL_POLICY = json.loads((Path(__file__).resolve().parents[1] / "policies" / "rural-basic-income.json").read_text(encoding="utf-8"))["text"]

OLD_HARDCODED_OUTREACH = (
    "현장 방문 또는 중간 다리를 통한 짧은 질문",
    "해당 집단을 만나는 지역 지원 담당 부서에 접점을 문의",
    "의견을 내는 데 무엇이 걸리고 어떤 통로가 편한가요?",
)


# ---- 1. visit_shared extraction & single source of truth ----

def test_visit_reexports_shared_tables_and_helpers():
    assert visit.ALWAYS_MISSING is visit_shared.ALWAYS_MISSING
    assert visit.PARTIES is visit_shared.PARTIES
    assert visit.ADDON_GROUPS is visit_shared.ADDON_GROUPS
    assert visit.header is visit_shared.header
    assert visit.young_child_candidate is visit_shared.young_child_candidate
    assert visit._base_groups is visit_shared.base_groups


def test_missing_people_matches_policy_parties_first_then_always_missing():
    text = "농어민 직불금과 장애인 이동지원, 소상공인 임대료 지원을 확대한다."
    items = visit_shared.missing_people(text)
    parties = [m for m in items if m["party"]]
    always = [m for m in items if not m["party"]]
    assert [m["who"] for m in parties] == ["장애 당사자와 가족", "규제를 받는 사업자", "농어민"]
    assert [m["who"] for m in always] == [m["who"] for m in visit_shared.ALWAYS_MISSING]
    assert items[:len(parties)] == parties


def test_venue_guidance_uses_visit_tables_and_channels_without_hardcoded_boilerplate():
    senior_person = {
        "uuid": "u1", "age": 72, "age_band": "70세 이상", "sex": "여자",
        "province": "서울", "region": "수도권", "education_level": "중학교",
        "marital_status": "사별", "family_type": "혼자 거주", "housing_type": "단독주택",
        "occupation": "무직", "profile": "학력: 중학교 / 혼인: 사별\n가구: 혼자 거주 / 주거: 단독주택",
    }
    youth_person = {
        "uuid": "u2", "age": 24, "age_band": "19–29세", "sex": "남자",
        "province": "부산", "region": "동남권", "education_level": "4년제 대학교",
        "marital_status": "미혼", "family_type": "혼자 거주", "housing_type": "아파트",
        "occupation": "소프트웨어 개발자", "profile": "학력: 4년제 대학교 / 혼인: 미혼\n가구: 혼자 거주 / 주거: 아파트",
    }
    g_senior = visit_shared.venue_guidance(
        "70세 이상 어르신", [senior_person],
        reactions=[{"channel": "경로당"}, {"channel": "주민센터"}],
        condition={"age_min": 70},
    )
    g_youth = visit_shared.venue_guidance(
        "19–29세", [youth_person],
        reactions=[{"channel": "유튜브"}],
        condition={"age_min": 19, "age_max": 29},
    )
    assert "경로당·노인복지관" in g_senior["venues"]
    assert g_senior["channels"] == ["경로당", "주민센터"]
    assert "대학·청년센터" in g_youth["venues"]
    assert g_youth["channels"] == ["유튜브"]
    assert g_senior["method"] != g_youth["method"]
    assert g_senior["where"] != g_youth["where"]
    for item in (g_senior, g_youth):
        for old in OLD_HARDCODED_OUTREACH:
            assert old not in json.dumps(item, ensure_ascii=False)


def test_fast_path_replaces_hardcoded_outreach_and_connects_always_missing_and_parties(fake_models):
    text = "농어민과 장애인, 소상공인을 위한 지역 교통 지원 정책안\n1. 농어촌 버스 요금을 지원한다."
    preview = service.estimate(text, sample=12)
    preview_whos = [m["who"] for m in preview["missing_people"]]
    assert "장애 당사자와 가족" in preview_whos
    assert "규제를 받는 사업자" in preview_whos
    assert "농어민" in preview_whos
    assert "만 19세 미만" in preview_whos
    assert "외국인 주민(귀화하지 않은 결혼이민자 포함)" in preview_whos
    assert "단체·업계의 조직된 의견" in preview_whos

    result = service.run_policy(text, sample=16)
    missing_groups = {m["group"] for m in result["missing_perspectives"] if "group" in m}
    assert {"장애 당사자와 가족", "규제를 받는 사업자", "농어민",
            "만 19세 미만", "외국인 주민(귀화하지 않은 결혼이민자 포함)",
            "단체·업계의 조직된 의견", "소득별 관점"} <= missing_groups
    assert result["outreach"]
    dump = json.dumps(result["outreach"], ensure_ascii=False)
    for old in OLD_HARDCODED_OUTREACH:
        assert old not in dump
    for row in result["outreach"]:
        assert row["venues"]
        assert "where" in row and "method" in row and "question" in row


# ---- 2. Policy-condition targeting, grouping, folding & schema pp.run/3 ----

def test_confirmed_conditions_target_affected_and_group_by_exact_names(fake_models):
    conds = [
        {
            "name": "65~69세 도시철도 이용자",
            "age_min": 65, "age_max": 69,
            "provinces": ["서울", "부산", "대구", "인천", "광주", "대전"],
            "keywords": ["지하철로"],
        },
        {
            "name": "65세 이상 기초연금 수급자",
            "age_min": 65,
            "eligibility": ["기초연금 수급자"],
        },
        {
            "name": "도시철도 미운행 지역 어르신",
            "age_min": 65,
            "provinces": ["강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"],
        },
    ]
    result = service.run_policy(SUBWAY_POLICY, sample=24, conditions=conds)
    assert result["schema"] == "pp.run/3"
    assert result["conditions"]["grouping_basis"] == "confirmed_conditions"
    assert result["conditions"]["confirmed_conditions"] is True
    assert result["grouping"]["basis"] == "confirmed_conditions"
    assert result["grouping"]["confirmed"] is True

    group_names = [g["group"] for g in result["group_reactions"]]
    # Confirmed names appear directly; raw occupations are folded instead of creating 10+ occupation buckets.
    assert "65세 이상 기초연금 수급자" in group_names
    assert "도시철도 미운행 지역 어르신" in group_names
    assert len(group_names) <= 4
    assert result["grouping"]["collapsed"]["occupation_groups_folded"] is True
    assert result["grouping"]["collapsed"]["occupations"]

    # Affected panel selection actually found candidates using the confirmed conditions!
    assert len(result["selection"]["affected"]["uuids"]) > 0
    # Eligibility caution is surfaced honestly (base panel cannot verify 기초연금 eligibility).
    assert any("수급 자격·소득 정보가 없어" in w for w in result["warnings"])

    # Every group keeps representative and affected reactions explicitly separated.
    for g in result["group_reactions"]:
        sep = g["panel_separation"]
        assert "대표 패널과 영향권 패널" in sep["note"]
        assert len(sep["representative_reactions"]) + len(sep["affected_reactions"]) == len(g["reactions"])

    # who_to_ask references condition group names and visit venues, never raw occupation list.
    for row in result["who_to_ask"]:
        assert set(row["groups"]) <= set(group_names)
        assert row["venues"]
        assert row["panel_scope"] in {"대표", "영향권", "대표·영향권 분리"}


def test_unmatched_confirmed_condition_is_reported_honestly(fake_models):
    conds = [{"name": "100세 이상 초고령자", "age_min": 100}]
    result = service.run_policy(SUBWAY_POLICY, sample=12, conditions=conds)
    unmatched = [m for m in result["missing_perspectives"] if m["kind"] == "unmatched_condition"]
    assert len(unmatched) == 1
    assert unmatched[0]["group"] == "100세 이상 초고령자"


def test_inferred_and_plain_policies_fold_occupations_and_collapse_repeated_outreach(fake_models):
    # Subway policy without explicit conditions -> inferred policy conditions (not 10+ raw occupations).
    res_subway = service.run_policy(SUBWAY_POLICY, sample=60)
    assert res_subway["grouping"]["basis"] == "inferred_policy_conditions"
    assert len(res_subway["group_reactions"]) <= 5
    assert res_subway["grouping"]["collapsed"]["occupation_groups_folded"] is True
    assert len(res_subway["grouping"]["collapsed"]["occupations"]) == 10
    # Repeated outreach sentences are folded into outreach_notes instead of repeated verbatim.
    folded_m = res_subway["outreach_notes"]["folded_methods"]
    folded_q = res_subway["outreach_notes"]["folded_questions"]
    if folded_m:
        assert any(o["method"] == "공통 접근 방식 참고(outreach_notes)" for o in res_subway["outreach"])
    if folded_q:
        assert any(o["question"] == "공통 현장 질문 참고(outreach_notes)" for o in res_subway["outreach"])

    # Rural policy without explicit conditions -> region inferred + 농어민 party detected.
    res_rural = service.run_policy(RURAL_POLICY, sample=24)
    assert res_rural["grouping"]["basis"] == "inferred_policy_conditions"
    assert any("농어민" == m.get("group") and m["kind"] == "policy_party" for m in res_rural["missing_perspectives"])

    # Plain policy with no demographic/regional/keyword cues -> coarse age bands (max 6), never raw occupations.
    plain = "공공 데이터 개방 기준을 정비한다.\n1. 개방 절차 표준화 방안을 마련한다."
    res_plain = service.run_policy(plain, sample=36)
    assert res_plain["grouping"]["basis"] == "life_condition_bands"
    assert len(res_plain["group_reactions"]) <= 6
    assert res_plain["grouping"]["collapsed"]["occupation_groups_folded"] is True


def test_schema_v3_preserves_backwards_compatible_fields_and_safeguards(fake_models):
    text = POLICY + "\n교통비 지원의 만족도를 확인한다."
    result = service.run_policy(text, sample=16)

    # Backwards-compatible pp.run/2 top-level fields all preserved.
    legacy_keys = {
        "notice", "schema", "synthetic", "warnings", "diagnostics", "input_hash",
        "execution_inputs", "selection", "attribution", "budget", "conditions",
        "estimate", "clauses", "issues", "missing_perspectives", "who_to_ask",
        "outreach", "questions", "group_reactions", "clarity", "limits",
    }
    assert legacy_keys <= set(result)
    assert result["schema"] == "pp.run/3"

    # Requirement 3: Anti-overconfidence markers (흔들림 · 대표/영향권 분리 · 출처 · 진단 경고).
    assert next(iter(result)) == "notice"
    assert result["notice"] == public_rules.NOTICE
    assert "흔들릴 수" in result["diagnostics"]["variability_note"]
    assert result["diagnostics"]["variability_note"] in result["warnings"]
    assert result["conditions"]["panel_separation"] is True
    assert "대표 패널과 영향권 패널" in result["diagnostics"]["panel_separation_note"]
    assert attribution.validate(result["attribution"]) == []
    assert result["diagnostics"]["status"] == "qualitative_only"
    assert result["diagnostics"]["reliability_findings"][0]["code"] == "reliability_subjective_topic"
    assert result["diagnostics"]["reliability_findings"][0]["message"] in result["warnings"]

    # Zero non-mock redactions from public_rules.check_output on our own generated prose.
    for section in ("missing_perspectives", "who_to_ask", "outreach", "outreach_notes", "grouping"):
        assert "규칙 검사로 문장을 제외함" not in json.dumps(result[section], ensure_ascii=False), section


def test_conditions_validation_rejects_bad_inputs_without_echoing_secrets(fake_models):
    for bad in (
        {"api_key": SECRET, "age_min": 65},
        {"age_min": 70, "age_max": 60},
        {"provinces": ["없는지역"]},
        {"sex": "기타"},
        {"name": "홍길동 의원", "age_min": 65},
        {"name": "빈 조건"},
        [{"name": "같은이름", "age_min": 65}, {"name": "같은이름", "age_min": 65}],
        "not-an-object",
    ):
        with pytest.raises(service.RequestError) as caught:
            service.estimate(POLICY, conditions=bad)
        assert SECRET not in str(caught.value)


# ---- 3. End-to-end adapter wiring: MCP, HTTP API, CLI ----

def test_conditions_work_across_mcp_http_and_cli_and_update_input_hash(fake_models, tmp_path, capsys):
    conds = [{"name": "70세 이상 어르신", "age_min": 70}]

    # Input hash tracks confirmed conditions cleanly.
    est_plain = service.estimate(POLICY, sample=12)
    est_cond = service.estimate(POLICY, sample=12, conditions=conds)
    assert est_plain["input_hash"] != est_cond["input_hash"]
    assert est_cond["target_conditions"][0]["name"] == "70세 이상 어르신"

    # HTTP API
    with TestClient(api.create_app()) as client:
        est_resp = client.post("/estimate", json={"policy_text": POLICY, "sample": 12, "conditions": conds})
        assert est_resp.status_code == 200
        assert est_resp.json()["input_hash"] == est_cond["input_hash"]
        run_resp = client.post("/runs", json={"policy_text": POLICY, "sample": 12, "conditions": conds})
        assert run_resp.status_code == 202
        state = wait_job(lambda rid: client.get(f"/runs/{rid}").json(), run_resp.json()["id"])
        assert state["status"] == "completed"
        assert state["result"]["schema"] == "pp.run/3"
        assert "70세 이상 어르신" in [g["group"] for g in state["result"]["group_reactions"]]
        assert state["result"]["input_hash"] == provenance.input_hash(state["result"]["execution_inputs"])

    # MCP
    jobs = Jobs()
    server = mcp.create_server(jobs)
    try:
        async def run_mcp():
            est = await server.call_tool("estimate", {"policy_text": POLICY, "sample": 12, "conditions": conds})
            assert not est.isError
            assert est.structuredContent["target_conditions"][0]["name"] == "70세 이상 어르신"
            started = await server.call_tool("start_run", {"policy_text": POLICY, "sample": 12, "conditions": conds})
            assert not started.isError
            done = wait_job(jobs.get, started.structuredContent["id"])
            got = await server.call_tool("get_run", {"id": done["id"], "view": "full"})
            assert not got.isError
            res = got.structuredContent["result"]
            assert res["schema"] == "pp.run/3"
            assert "70세 이상 어르신" in [g["group"] for g in res["group_reactions"]]
            # Bad condition key with secret never echoes secret
            bad = await server.call_tool("estimate", {"policy_text": POLICY, "conditions": {"api_key": SECRET}})
            assert bad.isError and SECRET not in bad.model_dump_json()

        asyncio.run(run_mcp())
    finally:
        jobs.close()

    # CLI (inline JSON and @file.json)
    draft = tmp_path / "policy.md"
    cond_file = tmp_path / "conds.json"
    out = tmp_path / "result.json"
    draft.write_text(POLICY, encoding="utf-8")
    cond_file.write_text(json.dumps(conds, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["estimate", str(draft), "--sample", "12", "--conditions", json.dumps(conds, ensure_ascii=False)]) == 0
    cli_est = json.loads(capsys.readouterr().out)
    assert cli_est["input_hash"] == est_cond["input_hash"]
    assert cli.main(["run", str(draft), "--sample", "12", "--conditions", f"@{cond_file}", "--out", str(out)]) == 0
    cli_res = json.loads(out.read_text(encoding="utf-8"))
    assert cli_res["schema"] == "pp.run/3"
    assert "70세 이상 어르신" in [g["group"] for g in cli_res["group_reactions"]]
