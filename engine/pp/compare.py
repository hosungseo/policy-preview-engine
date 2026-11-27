"""Paired revision experiment using frozen UUIDs, profiles and one explicit question."""
from __future__ import annotations

import json
from pathlib import Path

from . import budget, provenance, react


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare_runs(parent: Path, policy: Path, destination: Path, *, question: str, repeats=3, workers=8, limits=None):
    if not question.strip():
        raise ValueError("comparison requires the same explicit question for both versions")
    if not 2 <= repeats <= 10:
        raise ValueError("repeats must be between 2 and 10")
    parent, destination = Path(parent), Path(destination)
    if parent.resolve() == destination.resolve():
        raise ValueError("comparison needs a separate destination")
    original, revised = _read(parent / "policy.json"), _read(policy)
    people, meta = _read(parent / "personas.json"), _read(parent / "meta.json")
    uuids = [p["uuid"] for p in people]
    if not people or len(set(uuids)) != len(uuids):
        raise ValueError("comparison requires a nonempty panel with unique UUIDs")
    limits = limits or budget.Limits()
    from dataclasses import asdict
    inputs = {"parent_run_id": original["id"], "parent_input_hash": meta.get("input_hash"),
              "before": original, "after": revised, "personas": people, "question": question,
              "data": {k: meta.get(k) for k in ("panel_version", "source_revision", "persona_source")},
              "models": provenance.model_settings(), "code": provenance.code_version(),
              "repeats": repeats, "limits": asdict(limits)}
    fingerprint = provenance.input_hash(inputs)
    manifest = destination / "comparison-inputs.json"
    if manifest.exists() and _read(manifest).get("input_hash") != fingerprint:
        raise provenance.InputMismatch("comparison inputs changed; choose a new comparison directory")
    destination.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"input_hash": fingerprint, **inputs}, ensure_ascii=False, indent=1), encoding="utf-8")
    ledger = budget.Budget(limits, destination / "budget.json")
    results = {}
    with ledger.scope():
        for arm, text in (("before", original["text"]), ("after", revised["text"])):
            results[arm] = []
            for i in range(repeats):
                rows, failures = react.run_reactions(people, text, destination / f"{arm}-{i + 1}.jsonl",
                                                      question=question, workers=workers)
                if failures or len(rows) != len(people):
                    raise RuntimeError("comparison incomplete; keep partial files and resume with identical inputs")
                results[arm].append({r["uuid"]: r for r in rows})
    paired = []
    for uuid in uuids:
        before = [r[uuid]["support"] for r in results["before"]]
        after = [r[uuid]["support"] for r in results["after"]]
        paired.append({"uuid": uuid, "before": before, "after": after,
                       "mean_delta": sum(a - b for a, b in zip(after, before)) / repeats,
                       "before_range": max(before) - min(before), "after_range": max(after) - min(after)})
    def drift(arm):
        rates = [100 * sum(r["support"] > 0 for r in rows.values()) / len(people) for rows in results[arm]]
        return {"support_share_pp": rates, "repeat_drift_pp": max(rates) - min(rates)}
    changed = [k for k in set(original) | set(revised) if original.get(k) != revised.get(k)]
    result = {"input_hash": fingerprint, "parent_run_id": original["id"], "question": question,
              "n": len(people), "repeats": repeats, "changed_policy_fields": sorted(changed),
              "paired": paired, "before": drift("before"), "after": drift("after"), "budget": ledger.snapshot(),
              "cautions": ["같은 UUID·프로필·질문을 고정했습니다. 합성 응답의 변화는 실제 정책 효과가 아닙니다."]}
    if len(changed) > 1:
        result["cautions"].append("여러 입력 항목이 함께 바뀌어 변화의 원인을 분리해 해석할 수 없습니다.")
    out = destination / "comparison.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
