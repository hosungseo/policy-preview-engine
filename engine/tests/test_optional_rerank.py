import json
import subprocess
import os
import sys
from pathlib import Path

import pytest

from pp import panel, personas, rerank


def test_rerank_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PP_RERANK", raising=False)
    assert not rerank.enabled()
    monkeypatch.setenv("PP_RERANK", "nvidia")
    assert rerank.enabled()


def test_panel_rerank_preserves_diversity_and_exclusions(persona_db):
    conn = personas.connect()
    spec = {"filters": [{"age_min": 19}], "semantic_query": "정책 관련 인물"}
    calls = []

    def rank(rows, query):
        calls.append(rows)
        assert query == "정책 관련 인물"
        return [(r["id"], float(r["id"])) for r in rows]

    audit = {}
    original, _ = panel.build_affected(conn, spec, {1}, k=20)
    picked, _ = panel.build_affected(conn, spec, {1}, k=20, ranker=rank, receipt=audit)
    assert len(picked) == 20 and 1 not in {c["id"] for c in picked}
    assert len(calls[0]) == 169  # all candidates below the 300-person scoring budget
    assert {(c["province"], c["age"]) for c in picked} != set()
    from pp import config
    strata = lambda rows: {(config.REGION_OF[c["province"]], config.age_band(c["age"])) for c in rows}
    assert strata(picked) == strata(original)
    assert audit["rerank"]["status"] == "applied"


@pytest.mark.parametrize("failure", [TimeoutError, RuntimeError, ValueError])
def test_panel_rerank_failure_keeps_original_order(persona_db, failure):
    conn = personas.connect()
    spec = {"filters": [{"age_min": 19}], "semantic_query": "돌봄 정책"}
    expected, _ = panel.build_affected(conn, spec, set(), k=20)

    def broken(*args):
        raise failure("unavailable")

    audit = {}
    actual, _ = panel.build_affected(conn, spec, set(), k=20, ranker=broken, receipt=audit)
    assert actual == expected
    assert audit["rerank"] == {"enabled": True, "status": "fallback", "error_type": failure.__name__}


def test_invalid_partial_scores_do_not_modify_candidates(persona_db):
    spec = {"filters": [{"age_min": 19}], "semantic_query": "청년"}
    conn = personas.connect()
    expected, _ = panel.build_affected(conn, spec, set(), k=20)
    actual, _ = panel.build_affected(conn, spec, set(), k=20,
                                    ranker=lambda rows, query: [(rows[0]["id"], float("nan"))])
    assert actual == expected


def test_subprocess_is_offline_name_free_and_bounded(persona_db, monkeypatch):
    rows = personas.fetch(personas.connect(), [1, 2])

    def run(command, **kwargs):
        assert command[-3:] == ["-m", "pp.rerank", "--worker"]
        assert kwargs["timeout"] == 3 and kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        payload = json.loads(kwargs["input"])
        assert all(rows[0]["name"] not in text for text in payload["texts"])
        return subprocess.CompletedProcess(command, 0, "[0.2, 0.8]")

    monkeypatch.setattr(subprocess, "run", run)
    assert rerank.rank(rows, "돌봄", timeout=3) == [(2, 0.8), (1, 0.2)]
    with pytest.raises(ValueError, match="300"):
        rerank.rank(rows * 151, "돌봄")


def test_shared_model_lock_rejects_second_process_before_loading(tmp_path):
    from pp.filelock_util import lock_file
    path = tmp_path / "local-model.lock"
    with path.open("a+") as handle:
        lock_file(handle)
        result = subprocess.run([sys.executable, "-m", "pp.rerank", "--worker"],
                                input=json.dumps({"query": "돌봄", "texts": ["야간 보육이 필요하다"]}),
                                text=True, capture_output=True, timeout=5,
                                env={**os.environ, "PP_LOCAL_MODEL_LOCK": str(path),
                                     "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
    assert result.returncode != 0 and "BlockingIOError" in result.stderr
