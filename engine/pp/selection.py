"""A portable receipt for the actual panel selection, without model calls."""
from __future__ import annotations

from . import panel, personas


def receipt(*, source: dict, requested_spec: dict, spec: dict, strata: dict, rep_ids: list[int],
            affected: list[dict], rows: list[dict], n_rep: int, seed: int, pool_uuids: list[str] | None,
            affected_receipt: dict, channel_counts: dict, missing_semantic_uuids: list[str],
            semantic_note: str) -> dict:
    by_id = {r["id"]: r["uuid"] for r in rows}
    ids = rep_ids + [p["id"] for p in affected]
    missing = [pid for pid in ids if pid not in by_id]
    if missing:
        raise ValueError(f"selected persona IDs not found: {missing}")
    seats = panel.allocate({key: len(v) for key, v in strata.items()}, n_rep)
    rep = [by_id[pid] for pid in rep_ids]
    aff = [by_id[p["id"]] for p in affected]
    return {
        "schema_version": "1", "status": "candidate_not_eligibility", "data": source,
        "requested_spec": requested_spec, "normalized_spec": spec,
        "sql_templates": {"persona-filter-v1": personas.FILTER_SQL},
        "representative": {
            "conditions": {"pool_uuids": pool_uuids}, "eligible_count": sum(map(len, strata.values())),
            "requested_count": n_rep, "selected_count": len(rep), "uuids": rep,
            "selection": "largest_remainder_stratified_seeded_random_without_replacement",
            "order": "strata sorted by str(tuple); source IDs ascending; random.sample draw order",
            "strata_fields": ["province", "age_band", "sex"], "seed": seed,
            "strata": [{"values": list(key), "eligible_count": len(strata[key]), "seats": seats[key]}
                       for key in sorted(strata, key=str)],
        },
        "affected": {**affected_receipt, "channels": channel_counts, "uuids": aff,
                     "found_by": {by_id[p["id"]]: p["found_by"] for p in affected},
                     "semantic": {"query": spec["semantic_query"], "note": semantic_note,
                                  "order": "embedding_similarity_desc_then_name_removed_similarity_desc",
                                  "sampling": "none", "tie_break": "numpy_argsort_unspecified",
                                  "missing_uuids": missing_semantic_uuids}},
        "selected_count": len(ids), "uuids": rep + aff,
        "note": "선택 조건과 검색 단서에 맞춘 확인 후보입니다. 실제 지원 자격이나 국민 대표성을 확정하지 않습니다.",
    }
