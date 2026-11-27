import json

import pytest

from pp import __main__ as cli
from pp import attribution, export

POLICY = {
    "id": "e2e", "title": "무임승차 연령 조정(테스트)", "kind": "가상 정책안", "agency": "테스트부",
    "source": {"note": "테스트"},
    "text": "1. 추진 배경\n고령화로 도시철도 무임수송 손실이 커지고 있어 제도를 손보려는 것이다.\n"
            "2. 주요 내용\n가. 무임승차 기준 연령을 단계적으로 70세까지 올린다.\n"
            "나. 기초연금 수급자는 무임승차를 계속 유지하도록 예외를 둔다.\n",
}


def test_full_pipeline_with_mock(persona_db, tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("PP_WEB_RUNS_DIR", str(tmp_path / "public"))
    monkeypatch.setenv("PP_WEB_DEV_RUNS_DIR", str(tmp_path / "dev"))
    policy = tmp_path / "e2e.json"
    policy.write_text(json.dumps(POLICY, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(export.ExportError):
        cli.main(["run", str(policy), "--n-rep", "30", "--n-aff", "10", "--n-jev", "60", "--n-alt", "20", "--workers", "4"])
    cli.main(["export", "e2e", "--allow-mock"])
    bundle = json.loads((tmp_path / "dev" / "e2e.json").read_text(encoding="utf-8"))
    assert export.validate_bundle(bundle, allow_mock=True) == []
    assert len(bundle["meta"]["input_hash"]) == 64
    assert bundle["meta"]["budget"]["calls"] > 0
    assert attribution.validate(bundle["attribution"]) == []
    assert attribution.validate(bundle["plan"]["attribution"]) == []
    assert bundle["plan"]["diagnostics"] == bundle["analysis"]["diagnostics"]
    assert bundle["analysis"]["diagnostics"]["n"] == 60
    assert bundle["plan"]["warnings"]
    assert bundle["analysis"]["overall"]["n"] == 30
    assert sum(p["panel"] == "aff" for p in bundle["personas"]) == 10
    assert len(bundle["hearing"]["turns"]) == 21
    assert bundle["selection"]["uuids"] == [p["uuid"] for p in bundle["personas"]]
    assert bundle["selection"]["selected_count"] == 40
    assert bundle["hearing"]["policy_truncated"] is False
    assert bundle["meta"]["hearing_context"]["shown_chars"] == bundle["hearing"]["shown_chars"]
    assert any("의미 검색 경로 생략" in f for f in bundle["meta"]["fallbacks"])
    assert not (tmp_path / "public").exists()
    assert [s["name"] for s in bundle["meta"]["stages"]] == ["segment", "clarity", "panel", "react", "issues", "jev",
                                                            "alternatives", "review", "analyze", "hearing", "debrief",
                                                            "plan"]
    jv = bundle["analysis"]["jev"]
    assert jv["n"] == 60 and len(jv["overall"]["mass"]) == 5 and jv["compare"]["n"] == 30
    assert jv["compare_aff"]["n"] == 10 and jv["compare_aff"]["caution"] == "전체 비율로 읽지 않음"
    assert set(jv["clauses"]["overall"]) == {s["id"] for s in bundle["segments"]}
    assert all(p["jev"] is not None for p in bundle["personas"])
    seg_ids = {s["id"] for s in bundle["segments"]}
    assert set(jv["positions"]["overall"]) == seg_ids and set(jv["explain"]["overall"]) == seg_ids
    issues = bundle["analysis"]["issues"]
    assert set(jv["issue_prevalence"]["overall"]) == {it["id"] for it in issues}
    assert all(0 <= it["jev_mean"] <= 1 for it in issues)
    assert jv["methods"] and all(o.get("methods") for o in bundle["analysis"]["outreach"])
    assert sum(t["n"] for t in jv["provinces"]) == 60
    alts = bundle["analysis"]["alternatives"]
    assert alts["n"] == 20 and alts["baseline"]["n"] == 20 and len(alts["items"]) == 3
    assert all(it["n"] == 20 and it["text"].startswith("[수정안]") for it in alts["items"])
    assert bundle["analysis"]["consistency"]["n"] == 40
    usage = bundle["meta"]["jev_usage"]
    assert usage["jev"]["panel"]["calls"] == bundle["meta"]["counts"]["jev_calls"]
    assert usage["alternatives"]["alternatives"]["calls"] == 100  # 20 people x (original, 3 amendments, placebo)
    assert alts["placebo"]["n"] == 20 and all("net_mean" in it for it in alts["items"])
    assert usage["issues"]["consistency"]["calls"] == 40
    qa = bundle["plan"]["qa"]
    assert qa and all(0 <= q["jev_p"] <= 1 for q in qa) and [q["jev_p"] for q in qa] == sorted((q["jev_p"] for q in qa), reverse=True)
    assert usage["plan"]["questions"]["calls"] == 60
    # clarity, review (order check, lenses, batching, repeat, occupations) and hearing reads
    assert [c["segment_id"] for c in bundle["clarity"]["clauses"]] == [seg["id"] for seg in bundle["segments"]]
    quality = bundle["analysis"]["quality"]
    assert quality["order"]["reactions"] == 40 and quality["batching"]["n"] == 60 and quality["repeat"]["n"] == 60
    assert quality["occupations"]["n"] > 0
    assert len(bundle["analysis"]["lenses"]["items"]) == 12 and all("lenses" in r for r in bundle["reactions"])
    assert len(bundle["hearing"]["reads"]) == 18 and len(bundle["hearing"]["trajectories"]["participants"]) == 6
    assert usage["review"]["order"]["calls"] == 80 and usage["review"]["lenses"]["calls"] == 40
    assert usage["review"]["repeat"]["calls"] == 60 and usage["debrief"]["debrief"]["calls"] == 18
    assert usage["clarity"]["clarity"]["calls"] == len(bundle["segments"]) + 1
    assert "clarity" in bundle["plan"]
