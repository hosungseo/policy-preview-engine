"""Validate portable test cards and distinguish usable evidence from deferred evidence.

No model calls or third-party packages are needed. The structural checker implements
the JSON Schema keywords used by schema-v1.json; it is not a general schema engine.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from uuid import UUID

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "scenarios" / "schema-v1.json"


def text_sha256(text: str) -> str:
    """Hash the exact UTF-8 text, without whitespace or Unicode normalization."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check(value, rule: dict, root: dict, path: str) -> None:
    if "$ref" in rule:
        return _check(value, root["$defs"][rule["$ref"].removeprefix("#/$defs/")], root, path)
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
    types = rule.get("type", [])
    types = [types] if isinstance(types, str) else types
    if types and not any(isinstance(value, kinds[k]) for k in types):
        raise ValueError(f"{path}: expected {types}")
    if "enum" in rule and value not in rule["enum"]:
        raise ValueError(f"{path}: expected one of {rule['enum']}")
    if isinstance(value, dict):
        absent = set(rule.get("required", [])) - set(value)
        if absent:
            raise ValueError(f"{path}: missing {sorted(absent)}")
        props = rule.get("properties", {})
        if rule.get("additionalProperties") is False and set(value) - set(props):
            raise ValueError(f"{path}: unknown fields {sorted(set(value) - set(props))}")
        for key in value.keys() & props.keys():
            _check(value[key], props[key], root, f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            raise ValueError(f"{path}: too few items")
        if rule.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise ValueError(f"{path}: duplicate items")
        for i, item in enumerate(value):
            _check(item, rule.get("items", {}), root, f"{path}[{i}]")
    elif isinstance(value, str):
        if len(value) < rule.get("minLength", 0) or ("pattern" in rule and not re.search(rule["pattern"], value)):
            raise ValueError(f"{path}: invalid string")
        try:
            if rule.get("format") == "date":
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("expected YYYY-MM-DD")
                date.fromisoformat(value)
            if rule.get("format") == "uuid":
                if str(UUID(value)) != value.lower():
                    raise ValueError("expected hyphenated UUID")
        except ValueError as exc:
            raise ValueError(f"{path}: invalid {rule['format']}") from exc


def validate_scenario(card: dict) -> dict:
    """Raise ValueError for invalid cards; return ready/deferred evidence status.

    'ready' means the recorded evidence may be used for evaluation. It does not
    mean that an answer passed, that facts were independently verified, or that
    a synthetic persona is eligible for a public benefit.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _check(card, schema, schema, "scenario")
    observed, assumed = set(card["observed_fields"]), set(card["assumed_context"])
    if observed & assumed or set(card["unknown_fields"]) & (observed | assumed):
        raise ValueError("observed_fields, assumed_context and unknown_fields must be disjoint")
    documents = card["reference_documents"]
    ref_ids = [doc["id"] for doc in documents]
    behaviors = card["expected"] + card["forbidden"]
    if len(set(ref_ids)) != len(ref_ids):
        raise ValueError("duplicate reference document IDs")
    if len({b["id"] for b in behaviors}) != len(behaviors):
        raise ValueError("duplicate behavior IDs")
    for behavior in behaviors:
        missing = set(behavior["reference_ids"]) - set(ref_ids)
        if missing:
            raise ValueError(f"{behavior['id']}: unknown reference IDs {sorted(missing)}")
    for doc in [card["guidance"], *documents]:
        if text_sha256(doc["text"]) != doc["sha256"]:
            raise ValueError(f"{doc['id']}: text sha256 mismatch")
    reasons = []
    if card["guidance"]["placeholder"]:
        reasons.append("안내문이 예시·임시 자료입니다.")
    for doc in documents:
        start, end = doc["effective_from"], doc["effective_until"]
        if end is not None and end < start:
            raise ValueError(f"{doc['id']}: effective_until precedes effective_from")
        if doc["placeholder"] or doc["review_status"] != "reviewed":
            reasons.append(f"{doc['id']}: 근거가 예시·임시 자료이거나 검토되지 않았습니다.")
        if doc["jurisdiction"] != card["jurisdiction"]:
            reasons.append(f"{doc['id']}: 적용 지역이 다릅니다.")
        if card["as_of"] < start or (end is not None and card["as_of"] > end):
            reasons.append(f"{doc['id']}: 기준일에 유효한 근거가 아닙니다.")
    return {"scenario_id": card["scenario_id"], "status": "deferred" if reasons else "ready",
            "reasons": reasons, "note": "판정 보류" if reasons else "기록된 근거를 평가에 사용할 수 있습니다."}
