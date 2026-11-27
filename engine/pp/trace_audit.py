"""Optional deterministic trace exporter (NeMo Compass v3 JSONL) and contract auditor.

Zero model calls, zero external dependencies, default-off (only invoked explicitly via
`python -m pp.trace_audit` or direct import). Existing CLI/HTTP/MCP defaults are unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TRACE_SCHEMA_VERSION = "3"
DEFAULT_MIN_RECURRING_CASES = 3
LATE_NOTICE_CHAR_LIMIT = 800
HIGH_CACHE_WRITE_RATIO = 0.20

_MOCK_MARKERS = ("MOCK 요약", "MOCK 질문", "MOCK 쟁점")


def _content_text(value: Any) -> str:
    """MCP results may contain text blocks rather than a single text string."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in value
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return json.dumps(value, ensure_ascii=False)


def _clean_error_mechanism(raw: str) -> str:
    """Normalize tool error text so identical error_codes group into one card across versions."""
    text = (raw or "").strip()
    # Strip any prepended safety notice line before a JSON error object
    if "{" in text:
        candidate = text[text.find("{") :]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                code = parsed.get("error_code") or parsed.get("code")
                if code:
                    return str(code)
                if parsed.get("http_status") and int(parsed["http_status"]) >= 400:
                    body = parsed.get("body") or {}
                    bcode = body.get("error_code") or body.get("code") if isinstance(body, dict) else None
                    return f"http_{parsed['http_status']}:{bcode or 'error'}"
                if parsed.get("error"):
                    return str(parsed["error"])[:80]
        except json.JSONDecodeError:
            pass
    return text[:80] or "unknown_error"


def _detect_source_kind(record: dict[str, Any]) -> str:
    if "turns" in record and isinstance(record["turns"], list):
        return "mcp_session"
    if "conversation_messages" in record or "pp_scenario_id" in record:
        return "usersim"
    if str(record.get("schema", "")).startswith("pp.run/"):
        return "engine_run"
    return "generic"


def export_compass_trace(
    record: dict[str, Any],
    *,
    trace_id: str | None = None,
    source_kind: str = "auto",
) -> dict[str, Any]:
    """Convert a Policy Preview execution record into a NeMo Compass canonical Trace v3 dict."""
    kind = _detect_source_kind(record) if source_kind == "auto" else source_kind
    tid = trace_id or str(record.get("id") or record.get("input_id") or record.get("session") or "trace-1")
    now_iso = datetime.now(timezone.utc).isoformat()

    children: list[dict[str, Any]] = []
    turns_out: list[dict[str, Any]] = []
    eval_results: dict[str, Any] = {}
    attrs: dict[str, Any] = {"source_kind": kind}

    if kind == "engine_run":
        mode = str(record.get("mode") or "unknown")
        attrs["mode"] = mode
        attrs["schema"] = str(record.get("schema") or "")
        issues = record.get("issues") or []
        questions = record.get("questions") or []
        eval_results["issue_count"] = len(issues)
        eval_results["question_count"] = len(questions)
        eval_results["is_mock"] = int(mode == "mock")
        children.append(
            {
                "id": "tool-1",
                "kind": "TOOL",
                "start_time": now_iso,
                "end_time": now_iso,
                "tool_name": "policy_preview_run",
                "input": {"input_hash": record.get("input_hash"), "mode": mode},
                "output": {
                    "schema": record.get("schema"),
                    "mode": mode,
                    "trial_notice": record.get("trial_notice"),
                    "issue_titles": [i.get("title") for i in issues if isinstance(i, dict)],
                },
                "tool_call": {
                    "call_id": f"{tid}:run",
                    "index": 0,
                    "result_id": f"{tid}:run",
                    "result_count": 1,
                    "results": [{"content": json.dumps({"mode": mode, "issues": len(issues)}, ensure_ascii=False), "is_error": False}],
                },
            }
        )

    elif kind == "usersim":
        raw_conv = record.get("conversation_messages") or "[]"
        conv = json.loads(raw_conv) if isinstance(raw_conv, str) else list(raw_conv)
        sim_out = json.loads(record["simulation_outcome"]) if isinstance(record.get("simulation_outcome"), str) else (record.get("simulation_outcome") or {})
        attrs["probe"] = record.get("pp_scenario_id")
        attrs["row_num_tool_calls"] = int(record.get("num_tool_calls") or 0)
        attrs["sim_outcome_n_tool_calls"] = int(sim_out.get("n_tool_calls") or 0)
        eval_results["tool_count_mismatch"] = int(
            attrs["row_num_tool_calls"] > 0 and attrs["sim_outcome_n_tool_calls"] == 0
        )

        tool_map: dict[str, dict[str, Any]] = {}
        turn_i = 0
        call_i = 0
        for m in conv:
            role = m.get("role")
            content = str(m.get("content") or "")
            if role == "user":
                turn_i += 1
                turns_out.append(
                    {
                        "id": f"agent-root/turn/{turn_i}",
                        "index": turn_i,
                        "role": "user",
                        "authorship": "harness",
                        "content": content,
                        "llm_span_ids": [],
                        "tool_call_span_ids": [],
                    }
                )
            elif role == "assistant":
                t_ids = []
                for tc in m.get("tool_calls") or []:
                    call_i += 1
                    cid = str(tc.get("id") or f"call-{call_i}")
                    fn = tc.get("function") or {}
                    raw_args = fn.get("arguments")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = raw_args
                    sp_id = f"tool-{call_i}"
                    t_ids.append(sp_id)
                    sp = {
                        "id": sp_id,
                        "kind": "TOOL",
                        "start_time": now_iso,
                        "end_time": now_iso,
                        "tool_name": str(fn.get("name") or "unknown"),
                        "input": args,
                        "tool_call": {"call_id": cid, "index": call_i - 1, "result_count": 0, "results": []},
                    }
                    tool_map[cid] = sp
                    children.append(sp)
                turn_i += 1
                turns_out.append(
                    {
                        "id": f"agent-root/turn/{turn_i}",
                        "index": turn_i,
                        "role": "agent",
                        "authorship": "model",
                        "content": content,
                        "llm_span_ids": [],
                        "tool_call_span_ids": t_ids,
                    }
                )
            elif role == "tool":
                cid = str(m.get("tool_call_id") or "")
                is_err = False
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and int(parsed.get("http_status", 200)) >= 400:
                        is_err = True
                except json.JSONDecodeError:
                    pass
                if cid in tool_map:
                    sp = tool_map[cid]
                    sp["output"] = content
                    if is_err:
                        sp["error"] = _clean_error_mechanism(content)
                    sp["tool_call"]["result_id"] = cid
                    sp["tool_call"]["results"].append({"content": content, "is_error": is_err})
                    sp["tool_call"]["result_count"] = len(sp["tool_call"]["results"])

    elif kind == "mcp_session":
        attrs["session"] = record.get("session")
        attrs["scenario"] = record.get("scenario")
        tool_map = {}
        turn_i = 0
        call_i = 0
        for raw_turn in record.get("turns") or []:
            turn_i += 1
            turns_out.append(
                {
                    "id": f"agent-root/turn/{turn_i}",
                    "index": turn_i,
                    "role": "user",
                    "authorship": "human",
                    "content": str(raw_turn.get("text") or ""),
                    "llm_span_ids": [],
                    "tool_call_span_ids": [],
                }
            )
            assistant_texts: list[str] = []
            t_ids: list[str] = []
            for ev in raw_turn.get("events") or []:
                et = ev.get("type")
                if et == "assistant":
                    for blk in (ev.get("message") or {}).get("content") or []:
                        if not isinstance(blk, dict):
                            continue
                        if blk.get("type") == "text":
                            assistant_texts.append(str(blk.get("text") or ""))
                        elif blk.get("type") == "tool_use":
                            call_i += 1
                            cid = str(blk.get("id") or f"call-{call_i}")
                            sp_id = f"tool-{call_i}"
                            t_ids.append(sp_id)
                            sp = {
                                "id": sp_id,
                                "kind": "TOOL",
                                "start_time": now_iso,
                                "end_time": now_iso,
                                "tool_name": str(blk.get("name") or "unknown"),
                                "input": blk.get("input"),
                                "tool_call": {"call_id": cid, "index": call_i - 1, "result_count": 0, "results": []},
                            }
                            tool_map[cid] = sp
                            children.append(sp)
                elif et == "user":
                    for blk in (ev.get("message") or {}).get("content") or []:
                        if isinstance(blk, dict) and blk.get("type") == "tool_result":
                            cid = str(blk.get("tool_use_id") or "")
                            raw_content = blk.get("content")
                            txt = _content_text(raw_content)
                            is_err = bool(blk.get("is_error"))
                            if cid in tool_map:
                                sp = tool_map[cid]
                                sp["output"] = txt
                                if is_err:
                                    sp["error"] = _clean_error_mechanism(txt)
                                sp["tool_call"]["result_id"] = cid
                                sp["tool_call"]["results"].append({"content": txt, "is_error": is_err})
                                sp["tool_call"]["result_count"] = len(sp["tool_call"]["results"])
            turn_i += 1
            turns_out.append(
                {
                    "id": f"agent-root/turn/{turn_i}",
                    "index": turn_i,
                    "role": "agent",
                    "authorship": "model",
                    "content": "\n".join(assistant_texts),
                    "llm_span_ids": [],
                    "tool_call_span_ids": t_ids,
                }
            )

    agent_span: dict[str, Any] = {
        "id": "agent-root",
        "kind": "AGENT",
        "start_time": now_iso,
        "end_time": now_iso,
        "agent": {"name": f"policy-preview:{kind}"},
        "children": children,
    }
    if turns_out:
        agent_span["turns"] = turns_out

    return {
        "id": tid,
        "schema_version": TRACE_SCHEMA_VERSION,
        "case_id": tid,
        "root_spans": [agent_span],
        "aggregate": {},
        "evaluator_results": eval_results,
        "attributes": attrs,
    }


def _finding(trace_id: str, issue_type: str, mechanism: str, summary: str, *, severity: str = "medium") -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "issue_type": issue_type,
        "mechanism": mechanism,
        "severity": severity,
        "summary": summary,
    }


def audit_trace_record(
    record: dict[str, Any],
    *,
    trace_id: str | None = None,
    source_kind: str = "auto",
) -> list[dict[str, Any]]:
    """Run deterministic 0-cost failure/contract checks on a single execution record."""
    kind = _detect_source_kind(record) if source_kind == "auto" else source_kind
    tid = trace_id or str(record.get("id") or record.get("input_id") or record.get("session") or "trace-1")
    findings: list[dict[str, Any]] = []

    if kind == "engine_run":
        blob = json.dumps(record, ensure_ascii=False)
        if any(m in blob for m in _MOCK_MARKERS):
            findings.append(
                _finding(
                    tid,
                    "mock_placeholder_leak",
                    "mock_template_cards",
                    "모의 실행 결과에 MOCK 자리 채움 카드/질문이 포함되어 있습니다.",
                    severity="high",
                )
            )
        trial_notice = str(record.get("trial_notice") or "")
        if record.get("mode") == "mock" and trial_notice and ("0명" not in trial_notice and "여론" not in trial_notice):
            findings.append(
                _finding(
                    tid,
                    "trial_notice_without_core_phrase",
                    "missing_non_poll_phrase",
                    "검토 후보: trial_notice 자체에 핵심 고지 문구가 없음(별도 notice 누락을 뜻하지 않음).",
                    severity="medium",
                )
            )
        return findings

    if kind == "usersim":
        sim_out = json.loads(record["simulation_outcome"]) if isinstance(record.get("simulation_outcome"), str) else (record.get("simulation_outcome") or {})
        row_tools = int(record.get("num_tool_calls") or 0)
        sim_tools = int(sim_out.get("n_tool_calls") or 0)
        if row_tools > 0 and sim_tools == 0:
            findings.append(
                _finding(
                    tid,
                    "usersim_tool_count_mismatch",
                    "simulation_outcome_zero_tool_calls",
                    f"실제 도구 호출은 {row_tools}건이나 simulation_outcome.n_tool_calls가 0으로 기록됨.",
                    severity="low",
                )
            )
        raw_conv = record.get("conversation_messages") or "[]"
        conv = json.loads(raw_conv) if isinstance(raw_conv, str) else list(raw_conv)
        for m in conv:
            if m.get("role") == "tool":
                txt = str(m.get("content") or "")
                try:
                    parsed = json.loads(txt)
                    if isinstance(parsed, dict) and int(parsed.get("http_status", 200)) >= 400:
                        mech = _clean_error_mechanism(txt)
                        findings.append(
                            _finding(
                                tid,
                                "tool_failure",
                                mech,
                                f"User Sim HTTP 도구 호출이 오류({mech})를 반환했습니다.",
                                severity="medium",
                            )
                        )
                except json.JSONDecodeError:
                    pass
        return findings

    if kind == "mcp_session":
        saw_reaction_tool = False
        saw_mock = False
        saw_trial_mask = False
        in_total = 0
        c_write = 0
        tool_names: dict[str, str] = {}

        for raw_turn in record.get("turns") or []:
            for ev in raw_turn.get("events") or []:
                et = ev.get("type")
                if et == "assistant":
                    msg = ev.get("message") or {}
                    usage = msg.get("usage") or {}
                    in_tok = int(usage.get("input_tokens") or 0)
                    cr = int(usage.get("cache_read_input_tokens") or 0)
                    cw = int(usage.get("cache_creation_input_tokens") or 0)
                    in_total += in_tok + cr + cw
                    c_write += cw

                    for blk in msg.get("content") or []:
                        if not isinstance(blk, dict):
                            continue
                        if blk.get("type") == "tool_use":
                            cid = str(blk.get("id") or "")
                            nm = str(blk.get("name") or "")
                            tool_names[cid] = nm
                            if nm.endswith("try_example") or nm.endswith("get_run"):
                                saw_reaction_tool = True
                        elif blk.get("type") == "text":
                            txt = str(blk.get("text") or "")
                            if any(m in txt for m in _MOCK_MARKERS):
                                saw_mock = True
                            if saw_reaction_tool and txt.strip():
                                pos_poll = txt.find("여론")
                                pos_zero = txt.find("0명")
                                pos = min([p for p in (pos_poll, pos_zero) if p >= 0], default=-1)
                                if pos < 0 or pos > LATE_NOTICE_CHAR_LIMIT:
                                    findings.append(
                                        _finding(
                                            tid,
                                            "safety_notice_missing_or_late",
                                            "omitted" if pos < 0 else "buried_after_800_chars",
                                            "반응 요약 답변 앞부분(800자 이내)에 '여론 아님/0명' 고지가 없습니다.",
                                            severity="high",
                                        )
                                    )
                                saw_reaction_tool = False
                elif et == "user":
                    for blk in (ev.get("message") or {}).get("content") or []:
                        if isinstance(blk, dict) and blk.get("type") == "tool_result":
                            raw_content = blk.get("content")
                            txt = _content_text(raw_content)
                            if any(m in txt for m in _MOCK_MARKERS):
                                saw_mock = True
                            if "trial_notice" in txt and "{" in txt:
                                try:
                                    payload = json.loads(txt[txt.find("{") :])
                                    notice = payload.get("trial_notice") if isinstance(payload, dict) else None
                                    if isinstance(notice, str) and notice and "0명" not in notice and "여론" not in notice:
                                        saw_trial_mask = True
                                except json.JSONDecodeError:
                                    pass
                            if blk.get("is_error"):
                                mech = _clean_error_mechanism(txt)
                                tname = tool_names.get(str(blk.get("tool_use_id") or ""), "tool")
                                findings.append(
                                    _finding(
                                        tid,
                                        "tool_failure",
                                        mech,
                                        f"MCP 도구 {tname} 호출 실패({mech}).",
                                        severity="high" if mech == "run_not_found" else "medium",
                                    )
                                )

        if saw_mock:
            findings.append(
                _finding(
                    tid,
                    "mock_placeholder_leak",
                    "mock_template_cards",
                    "MCP 모의 실행에서 MOCK 자리 채움 문구가 사용자 답변/도구 결과에 노출됨.",
                    severity="high",
                )
            )
        if saw_trial_mask:
            findings.append(
                _finding(
                    tid,
                    "trial_notice_without_core_phrase",
                    "missing_non_poll_phrase",
                    "검토 후보: trial_notice 자체에 핵심 고지 문구가 없음(별도 notice 누락을 뜻하지 않음).",
                    severity="medium",
                )
            )
        if in_total > 0 and (c_write / in_total) > HIGH_CACHE_WRITE_RATIO:
            findings.append(
                _finding(
                    tid,
                    "high_cache_write_ratio",
                    "cold_cache_overhead",
                    f"입력 토큰 중 캐시 쓰기 비율이 {100.0 * c_write / in_total:.1f}%로 높음.",
                    severity="low",
                )
            )
    return findings


def audit_traces(
    records: Iterable[dict[str, Any]],
    *,
    min_cases: int = DEFAULT_MIN_RECURRING_CASES,
) -> dict[str, Any]:
    """Audit multiple execution records and group findings into Compass-style recurring cards."""
    all_findings: list[dict[str, Any]] = []
    trace_count = 0
    for idx, rec in enumerate(records, 1):
        trace_count += 1
        tid = str(rec.get("id") or rec.get("input_id") or rec.get("session") or f"trace-{idx}")
        all_findings.extend(audit_trace_record(rec, trace_id=tid))

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for f in all_findings:
        grouped[(f["issue_type"], f["mechanism"])].append(f)

    cards: list[dict[str, Any]] = []
    for (issue_type, mechanism), items in sorted(grouped.items(), key=lambda kv: (-len({x["trace_id"] for x in kv[1]}), kv[0])):
        trace_ids = sorted({x["trace_id"] for x in items})
        cards.append(
            {
                "issue_type": issue_type,
                "mechanism": mechanism,
                "severity": items[0]["severity"],
                "finding_count": len(items),
                "independent_case_count": len(trace_ids),
                "recurring": len(trace_ids) >= min_cases,
                "trace_ids": trace_ids,
                "sample_summary": items[0]["summary"],
            }
        )

    return {
        "schema": "pp.trace-audit/1",
        "trace_count": trace_count,
        "finding_count": len(all_findings),
        "card_count": len(cards),
        "recurring_card_count": sum(1 for c in cards if c["recurring"]),
        "min_cases_threshold": min_cases,
        "cards": cards,
        "findings": all_findings,
    }


def _load_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".jsonl":
            for idx, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    rec = json.loads(line)
                    rec.setdefault("id", f"{p.resolve()}:{idx}")
                    records.append(rec)
        else:
            obj = json.loads(text)
            if isinstance(obj, list):
                # MCP turns.json file; include parent suite dir when under .../runs/<session>/turns.json
                suite = p.parents[2].name if len(p.parents) >= 3 and p.parents[1].name == "runs" else p.parent.parent.name
                tid = f"{suite}:{p.parent.name}" if suite else p.parent.name
                records.append({"id": tid, "session": p.parent.name, "turns": obj})
            elif isinstance(obj, dict):
                obj.setdefault("id", str(p.resolve()))
                records.append(obj)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pp.trace_audit",
        description="Optional 0-cost trace auditor and NeMo Compass v3 JSONL exporter.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="JSON or JSONL trace/run files")
    parser.add_argument("--export-compass", type=Path, default=None, help="Write NeMo Compass v3 JSONL to path")
    parser.add_argument("--min-cases", type=int, default=DEFAULT_MIN_RECURRING_CASES)
    args = parser.parse_args(argv)

    records = _load_records(args.inputs)
    if args.export_compass is not None:
        with args.export_compass.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(export_compass_trace(rec), ensure_ascii=False) + "\n")

    report = audit_traces(records, min_cases=args.min_cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
