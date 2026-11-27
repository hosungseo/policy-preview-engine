import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from pp import config, semantic

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_embeddings.py"


def load_script():
    spec = importlib.util.spec_from_file_location("build_embeddings", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def encoder(seen):
    def encode(texts, batch_size=16):
        matrix = np.zeros((len(texts), config.EMBEDDING_DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            n = len(seen)
            matrix[i, n % config.EMBEDDING_DIM] = 3
            seen.append(text)
        return matrix
    return encode


def test_build_from_original_text_search_and_similar(persona_db):
    seen = []
    manifest = load_script().main(encode=encoder(seen), batch_size=8)
    assert manifest["model"] == config.QUERY_MODEL
    assert manifest["rows"] == 170 and manifest["complete"]
    assert len(seen) == 170 and all("김영숙" not in d for d in seen)
    assert semantic.available()
    idx = semantic.EmbIndex.load()
    assert idx.uuids[:2] == ["u00001", "u00002"]
    assert np.allclose(np.linalg.norm(np.asarray(idx.matrix, dtype=np.float32), axis=1), 1)
    q = np.zeros(config.EMBEDDING_DIM, dtype=np.float32)
    q[0] = 1
    assert idx.search(q, k=1, chunk=1)[0] == ("u00001", 1.0)
    assert idx.similar_within(["u00001", "u00002", "missing"], k=1) == {
        "u00001": ["u00002"], "u00002": ["u00001"], "missing": []}
    with pytest.raises(FileExistsError):
        load_script().main(encode=encoder([]))


def test_legacy_or_mismatched_vectors_are_not_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path))
    old = tmp_path / "emb"
    old.mkdir()
    np.save(old / "emb.f16.npy", np.ones((1, 1024), dtype=np.float16))
    (old / "emb_uuids.txt").write_text("old-uuid\n")
    assert not semantic.available()
    with pytest.raises(OSError):
        semantic.EmbIndex.load()
    config.emb_dir().mkdir()
    np.save(config.emb_matrix(), np.ones((1, config.EMBEDDING_DIM), dtype=np.float16))
    config.emb_uuids().write_text("new-uuid\n")
    assert not semantic.available()  # no manifest is never considered compatible
    config.emb_manifest().write_text(json.dumps({**semantic.embedding_identity(), "model": "retired-model",
                                                "complete": True, "rows": 1}))
    assert not semantic.available()
    with pytest.raises(ValueError, match="metadata"):
        semantic.EmbIndex.load()
    config.emb_manifest().write_text(json.dumps({**semantic.embedding_identity(), "complete": True, "rows": 1}))
    assert semantic.available()
    # Same metadata with an incompatible matrix cannot reach retrieval.
    np.save(config.emb_matrix(), np.ones((1, config.EMBEDDING_DIM + 1), dtype=np.float16))
    with pytest.raises(ValueError, match="shape/dtype"):
        semantic.EmbIndex.load()


def test_pilot_and_interrupted_build_never_activate(persona_db):
    manifest = load_script().main(limit=4, encode=encoder([]))
    assert not manifest["complete"] and manifest["rows"] == 4
    assert not semantic.available()
    assert not config.emb_dir().exists()

    def failed(*args, **kwargs):
        raise RuntimeError("encoder stopped")

    with pytest.raises(RuntimeError, match="stopped"):
        load_script().main(encode=failed)
    assert not semantic.available() and not config.emb_dir().exists()
    assert not list(config.emb_dir().parent.glob(".multilingual-*"))


def test_runtime_uses_e5_prefixes_without_network(monkeypatch):
    calls = []

    class Model:
        def encode(self, texts, **kwargs):
            calls.append((texts, kwargs))
            return np.ones((len(texts), config.EMBEDDING_DIM), dtype=np.float32)

    monkeypatch.setattr(semantic, "_model", Model())
    semantic.embed_query("야간 돌봄 확대")
    semantic.embed_documents(["야간 근무 중인 보호자"])
    assert calls[0][0] == ["query: 야간 돌봄 확대"]
    assert calls[1][0] == ["passage: 야간 근무 중인 보호자"]
    assert all(kwargs["normalize_embeddings"] for _, kwargs in calls)


@pytest.mark.parametrize("flag,value", [("PP_SEMANTIC", "off"), ("PP_PERSONA_SOURCE", "bundle")])
def test_optional_channel_can_stay_off(persona_db, monkeypatch, flag, value):
    load_script().main(encode=encoder([]))
    monkeypatch.setenv(flag, value)
    assert not semantic.available()
