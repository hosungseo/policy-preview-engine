"""Semantic channel: 1M persona embeddings (Qwen3-Embedding-0.6B) kept on the SSD."""
from __future__ import annotations

import os

try:
    import numpy as np
except ImportError:  # the service image has no numpy; semantic search is then simply unavailable
    np = None

from . import config

_index = None
_model = None


def available() -> bool:
    """False when the embedding files are missing, when PP_SEMANTIC=off, or when PP_PERSONA_SOURCE=bundle
    (the embedding matrix indexes the 1M-person DB, not the 20k bundle)."""
    if np is None or os.environ.get("PP_SEMANTIC", "").strip() == "off" or os.environ.get("PP_PERSONA_SOURCE", "").strip() == "bundle":
        return False
    return config.emb_matrix().exists() and config.emb_uuids().exists()


class EmbIndex:
    """Row-normalized float16 matrix (memory-mapped) plus the uuid of each row."""

    def __init__(self, matrix: np.ndarray, uuids: list[str]):
        self.matrix = matrix
        self.uuids = uuids
        self.row = {u: i for i, u in enumerate(uuids)}

    @classmethod
    def load(cls) -> "EmbIndex":
        matrix = np.load(config.emb_matrix(), mmap_mode="r")
        uuids = [u for u in config.emb_uuids().read_text(encoding="utf-8").split("\n") if u]
        if len(uuids) != matrix.shape[0]:
            raise ValueError(f"uuid count {len(uuids)} != matrix rows {matrix.shape[0]}")
        return cls(matrix, uuids)

    def search(self, query: np.ndarray, k: int, chunk: int = 131072) -> list[tuple[str, float]]:
        q = (query / np.linalg.norm(query)).astype(np.float32)
        best_idx = np.empty(0, dtype=np.int64)
        best_score = np.empty(0, dtype=np.float32)
        for start in range(0, self.matrix.shape[0], chunk):
            block = np.asarray(self.matrix[start:start + chunk], dtype=np.float32)
            scores = block @ q
            take = min(k, scores.shape[0])
            part = np.argpartition(-scores, take - 1)[:take]
            best_idx = np.concatenate([best_idx, part + start])
            best_score = np.concatenate([best_score, scores[part]])
            if best_idx.shape[0] > k:
                keep = np.argpartition(-best_score, k - 1)[:k]
                best_idx, best_score = best_idx[keep], best_score[keep]
        order = np.argsort(-best_score)[:k]
        return [(self.uuids[int(best_idx[i])], float(best_score[i])) for i in order]

    def similar_within(self, uuids: list[str], k: int = 3) -> dict[str, list[str]]:
        present = [u for u in uuids if u in self.row]
        out: dict[str, list[str]] = {u: [] for u in uuids}
        if len(present) < 2:
            return out
        sub = np.asarray(self.matrix[[self.row[u] for u in present]], dtype=np.float32)
        sims = sub @ sub.T
        np.fill_diagonal(sims, -np.inf)
        for i, uuid in enumerate(present):
            out[uuid] = [present[j] for j in np.argsort(-sims[i])[:k]]
        return out


def index() -> EmbIndex:
    global _index
    if _index is None:
        _index = EmbIndex.load()
    return _index


def _load_model():
    global _model
    if _model is None:
        os.environ.setdefault("HF_HOME", str(config.data_dir() / "hf"))
        import torch
        from sentence_transformers import SentenceTransformer

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        _model = SentenceTransformer(config.QUERY_MODEL, device=device)
    return _model


def embed_query(text: str) -> np.ndarray:
    """Embed a query with the same model as the persona matrix (instruction-prefixed)."""
    prompt = f"Instruct: {config.QUERY_INSTRUCTION}\nQuery: {text}"
    return _load_model().encode([prompt], normalize_embeddings=True)[0].astype(np.float32)


def embed_documents(texts: list[str], batch_size: int = 16) -> np.ndarray:
    return _load_model().encode(texts, batch_size=batch_size, normalize_embeddings=True).astype(np.float32)


# The published persona embeddings include the persona's name many times, so names like
# "노인자" or "전철기" dominate queries about the elderly or the subway (seen in the
# 2026-09-24 smoke test: 7 of the top 10 hits were name matches). Re-embedding a
# candidate set with the name removed and re-ranking fixes that at small cost.
def strip_name(text: str, name: str) -> str:
    if not name:
        return text
    return text.replace(f"{name} 씨", "이 사람").replace(f"{name}씨", "이 사람").replace(name, "이 사람")


def persona_text_without_name(row: dict) -> str:
    name = row.get("name") or ""
    parts = [f"{row['age']}세 {row['sex']}, {row['district']}, 직업 {row['occupation']}, {row['family_type']}"]
    for key in ("persona", "professional_persona", "family_persona", "cultural_background"):
        if row.get(key):
            parts.append(strip_name(row[key], name))
    return "\n".join(parts)


def rerank_without_names(rows: list[dict], query: np.ndarray, k: int, encode=embed_documents) -> list[tuple[int, float]]:
    """Re-embed candidates with names removed and return the top k (id, score)."""
    if not rows:
        return []
    vectors = encode([persona_text_without_name(r) for r in rows])
    q = (np.asarray(query, dtype=np.float32) / np.linalg.norm(query)).astype(np.float32)
    scores = vectors @ q
    order = np.argsort(-scores)[:k]
    return [(rows[i]["id"], float(scores[i])) for i in order]


def similar_by_text(rows: list[dict], k: int = 3, key: str = "uuid", encode=embed_documents) -> dict:
    """Nearest neighbours inside a panel, using name-free text embeddings."""
    out = {r[key]: [] for r in rows}
    if len(rows) < 2:
        return out
    vectors = encode([persona_text_without_name(r) for r in rows])
    sims = vectors @ vectors.T
    np.fill_diagonal(sims, -np.inf)
    for i, row in enumerate(rows):
        out[row[key]] = [rows[j][key] for j in np.argsort(-sims[i])[:k]]
    return out
