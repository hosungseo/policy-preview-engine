"""Unit tests for optional deterministic trace exporter and auditor (pp.trace_audit)."""
from __future__ import annotations

import json
from pathlib import Path

from pp import trace_audit


def _sample_mcp_session(session_id: str, *, include_notice: bool, tool_error: str | None = None) -> dict:
    tool_res_content = (
        tool_error
        if tool_error is not None
        else json.dumps(
            {
                "status": "completed",
                "mode": "mock",
                "trial_notice": "구조만 보여 주는 0원 체험입니다.",
                "questions": [{"question": "MOCK 질문 1"}],
            },
            ensure_ascii=False,
        )
    )
    reply_text = (
        "AI가 상상한 반응입니다. 사람 응답은 0명입니다. 여론도 통계도 아닙니다.\nMOCK 질문 1"
        if include_notice
        else "구조만 보여 주는 0원 체험입니다.\nMOCK 질문 1"
    )
    return {
        "id": session_id,
        "session": session_id,
        "turns": [
            {
                "text": "이 안 검토해 줘",
                "events": [
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {
                                "input_tokens": 100,
                                "cache_read_input_tokens": 500,
                                "cache_creation_input_tokens": 400,
                                "output_tokens": 50,
                            },
                            "content": [
                                {"type": "tool_use", "id": "call-1", "name": "mcp__policy-preview__get_run", "input": {"id": "abc"}}
                            ],
                        },
                    },
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "call-1",
                                    "is_error": tool_error is not None,
                                    "content": tool_res_content,
                                }
                            ]
                        },
                    },
                    {
                        "type": "assistant",
                        "message": {
                            "usage": {
                                "input_tokens": 100,
                                "cache_read_input_tokens": 900,
                                "cache_creation_input_tokens": 0,
                                "output_tokens": 80,
                            },
                            "content": [{"type": "text", "text": reply_text}],
                        },
                    },
                ],
            }
        ],
    }


def test_export_compass_v3_and_error_code_normalization():
    # Even when v1 prepends NOTICE text before JSON error, normalized error should equal "run_not_found"
    v1_err = 'AI가 상상한 반응입니다. 사람 응답은 0명입니다.\n{"error_code": "run_not_found", "error": "원인: 없음"}'
    sess = _sample_mcp_session("ux-v1:C", include_notice=True, tool_error=v1_err)
    exported = trace_audit.export_compass_trace(sess)
    assert exported["schema_version"] == "3"
    assert exported["case_id"] == "ux-v1:C"
    tool_span = exported["root_spans"][0]["children"][0]
    assert tool_span["kind"] == "TOOL"
    assert tool_span["error"] == "run_not_found"


def test_audit_groups_same_error_code_across_v1_and_v2_into_recurring_card():
    v1_err = 'AI가 상상한 반응입니다.\n{"error_code": "run_not_found"}'
    v2_err = '{"error_code": "run_not_found", "message": "이 서버에서 해당 작업을 찾지 못했습니다."}'
    records = [
        _sample_mcp_session("ux-v1:C", include_notice=True, tool_error=v1_err),
        _sample_mcp_session("ux-v2:B", include_notice=True, tool_error=v2_err),
        _sample_mcp_session("ux-v2:C", include_notice=True, tool_error=v2_err),
    ]
    report = trace_audit.audit_traces(records, min_cases=3)
    cards_by_key = {(c["issue_type"], c["mechanism"]): c for c in report["cards"]}
    assert ("tool_failure", "run_not_found") in cards_by_key
    card = cards_by_key[("tool_failure", "run_not_found")]
    assert card["independent_case_count"] == 3
    assert card["recurring"] is True


def test_audit_detects_missing_notice_mock_leak_and_trial_mask():
    sess = _sample_mcp_session("ux-v2:A-S3", include_notice=False)
    findings = trace_audit.audit_trace_record(sess)
    types = {f["issue_type"] for f in findings}
    assert "safety_notice_missing_or_late" in types
    assert "mock_placeholder_leak" in types
    assert "trial_notice_without_core_phrase" in types


def test_audit_detects_usersim_tool_count_telemetry_bug():
    row = {
        "input_id": "pp-test-1",
        "pp_scenario_id": "pp_missing_key",
        "num_tool_calls": 2,
        "simulation_outcome": json.dumps({"status": "ok", "n_tool_calls": 0}),
        "conversation_messages": json.dumps(
            [
                {"role": "user", "content": "실행해 주세요"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "c1", "function": {"name": "start_run", "arguments": "{}"}}],
                },
                {
                    "role": "tool",
                    "tool_call_id": "c1",
                    "content": json.dumps({"http_status": 400, "body": {"error_code": "missing_key"}}),
                },
            ],
            ensure_ascii=False,
        ),
    }
    findings = trace_audit.audit_trace_record(row)
    keys = {(f["issue_type"], f["mechanism"]) for f in findings}
    assert ("usersim_tool_count_mismatch", "simulation_outcome_zero_tool_calls") in keys
    assert ("tool_failure", "http_400:missing_key") in keys


def test_cli_export_and_audit(tmp_path: Path, capsys):
    run_file = tmp_path / "run.json"
    run_file.write_text(
        json.dumps(
            {
                "schema": "pp.run/3",
                "mode": "mock",
                "trial_notice": "구조만 보여 주는 0원 체험입니다.",
                "issues": [{"id": "i1", "title": "MOCK 쟁점 1"}],
                "questions": [{"question": "MOCK 질문 1"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out_jsonl = tmp_path / "compass.jsonl"
    rc = trace_audit.main([str(run_file), "--export-compass", str(out_jsonl), "--min-cases", "1"])
    assert rc == 0
    exported = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(exported) == 1
    assert exported[0]["schema_version"] == "3"
    stdout_report = json.loads(capsys.readouterr().out)
    assert stdout_report["trace_count"] == 1
    assert stdout_report["recurring_card_count"] >= 2


def test_mcp_text_block_error_is_normalized():
    session = _sample_mcp_session("blocks", include_notice=True, tool_error='{"error_code":"run_not_found"}')
    result = session["turns"][0]["events"][1]["message"]["content"][0]
    result["content"] = [{"type": "text", "text": result["content"]}]
    findings = trace_audit.audit_trace_record(session)
    assert any(f["mechanism"] == "run_not_found" for f in findings)
    exported = trace_audit.export_compass_trace(session)
    assert exported["root_spans"][0]["children"][0]["error"] == "run_not_found"


def test_same_filename_from_different_runs_counts_as_distinct_cases(tmp_path: Path):
    paths = []
    for name in ("first", "second", "third"):
        directory = tmp_path / name
        directory.mkdir()
        path = directory / "run.json"
        path.write_text(json.dumps({"schema": "pp.run/3", "issues": [{"title": "MOCK 쟁점"}]}))
        paths.append(path)
    records = trace_audit._load_records(paths)
    report = trace_audit.audit_traces(records)
    assert report["cards"][0]["independent_case_count"] == 3
    assert report["cards"][0]["recurring"]


def test_duplicate_trace_id_does_not_inflate_recurring_cases():
    record = {"id": "same-case", "schema": "pp.run/3", "issues": [{"title": "MOCK 쟁점"}]}
    report = trace_audit.audit_traces([record, record, record])
    assert report["cards"][0]["finding_count"] == 3
    assert report["cards"][0]["independent_case_count"] == 1
    assert not report["cards"][0]["recurring"]
