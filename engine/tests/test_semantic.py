import importlib.util
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from pp import config, semantic

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_embeddings.py"


def load_script():
    spec = importlib.util.spec_from_file_location("build_embeddings", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_shards(src: Path):
    src.mkdir(parents=True)
    vecs = {"a": [1, 0, 0, 0], "b": [0.9, 0.1, 0, 0], "c": [0, 0, 3, 0], "d": [0, 0, 0, 2]}
    items = list(vecs.items())
    for n, chunk in enumerate((items[:2], items[2:])):
        table = pa.table({
            "uuid": [u for u, _ in chunk],
            "embedding": pa.array([v for _, v in chunk], type=pa.list_(pa.float32())),
        })
        pq.write_table(table, src / f"train-0000{n}-of-00002.parquet")


def test_build_search_and_similar(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path))
    src = tmp_path / "emb" / "parquet" / "data"
    write_shards(src)
    load_script().main(src=src, dim=4)
    assert semantic.available()
    index = semantic.EmbIndex.load()
    assert index.uuids == ["a", "b", "c", "d"]
    norms = np.linalg.norm(np.asarray(index.matrix, dtype=np.float32), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)
    hits = index.search(np.array([1, 0, 0, 0], dtype=np.float32), k=2)
    assert [u for u, _ in hits] == ["a", "b"]
    sims = index.similar_within(["a", "b", "c", "zz"], k=1)
    assert sims["a"] == ["b"] and sims["b"] == ["a"] and sims["zz"] == []


def test_search_across_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path))
    src = tmp_path / "emb" / "parquet" / "data"
    write_shards(src)
    load_script().main(src=src, dim=4)
    index = semantic.EmbIndex.load()
    hits = index.search(np.array([0, 0, 1, 0.1], dtype=np.float32), k=2, chunk=1)
    assert [u for u, _ in hits] == ["c", "d"]


def test_unavailable_without_files(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path))
    assert not semantic.available()
    assert config.emb_matrix().parent == tmp_path / "emb"
