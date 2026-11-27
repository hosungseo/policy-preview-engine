"""Opt-in local NVIDIA cross-encoder, isolated behind a process timeout and model lock.

Download the pinned snapshot explicitly before enabling PP_RERANK=nvidia.
No API client, automatic download, or model load occurs on the default path.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys

MODEL = "nvidia/llama-nemotron-rerank-1b-v2"
REVISION = "828765652b05bd439c9789d2a6d093db1caa1443"
MAX_CANDIDATES = 300


def enabled() -> bool:
    return os.environ.get("PP_RERANK", "off").strip() == "nvidia"


class _LocalReranker:
    """Internal scorer; instantiate only inside a bounded process holding the model lock."""

    def __init__(self):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        options = dict(revision=REVISION, local_files_only=True, trust_remote_code=True)
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL, padding_side="left", **options)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.model = AutoModelForSequenceClassification.from_pretrained(
            MODEL, torch_dtype=torch.float32, attn_implementation="eager", **options).eval()
        self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model.to(self.device)

    def score(self, query: str, texts: list[str]) -> list[float]:
        scores = []
        with self.torch.inference_mode():
            for start in range(0, len(texts), 2):
                batch = self.tokenizer([f"question:{query} \n \n passage:{text}" for text in texts[start:start + 2]],
                                       padding=True, truncation=True, max_length=512, return_tensors="pt")
                logits = self.model(**{k: v.to(self.device) for k, v in batch.items()}).logits
                scores.extend(logits.reshape(-1).float().cpu().tolist())
        return scores


def score_texts(query: str, texts: list[str]) -> list[float]:
    return _LocalReranker().score(query, texts)


def rank(rows: list[dict], query: str, timeout: float = 180) -> list[tuple[int, float]]:
    from .semantic import persona_text_without_name

    if not rows:
        return []
    if len(rows) > MAX_CANDIDATES:
        raise ValueError("rerank accepts at most 300 candidates")
    payload = {"query": query, "texts": [persona_text_without_name(r) for r in rows]}
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    result = subprocess.run([sys.executable, "-m", "pp.rerank", "--worker"],
                            input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True,
                            timeout=timeout, check=True, env=env)
    scores = json.loads(result.stdout)
    if (not isinstance(scores, list) or len(scores) != len(rows)
            or any(isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s) for s in scores)):
        raise ValueError("invalid reranker score count or value")
    return sorted([(r["id"], float(s)) for r, s in zip(rows, scores)], key=lambda item: -item[1])


def _worker() -> None:
    from .filelock_util import lock_file

    payload = json.load(sys.stdin)
    if not isinstance(payload.get("texts"), list) or len(payload["texts"]) > MAX_CANDIDATES:
        raise ValueError("invalid rerank input")
    path = Path(os.environ.get("PP_LOCAL_MODEL_LOCK", "~/.cache/policy-preview/local-model.lock")).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        lock_file(handle, nonblocking=True)
        scores = score_texts(payload["query"], payload["texts"])
        print(json.dumps(scores, allow_nan=False))


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("Use PP_RERANK=nvidia in the panel pipeline")
    _worker()
