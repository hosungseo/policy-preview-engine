"""Local artifact identities and explicitly recorded source revisions (legacy sources remain unknown)."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path


def metadata_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def write_metadata(path: Path, metadata: dict) -> None:
    metadata_path(path).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@lru_cache(maxsize=8)
def _hash(path: str, size: int, mtime: int, compressed: bool) -> str:
    digest = hashlib.sha256()
    opener = gzip.open if compressed else open
    with opener(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def artifact(path: Path, *, compressed=False) -> dict:
    sidecar = metadata_path(path)
    recorded = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else {}
    stat = path.stat() if path.exists() else None
    version = _hash(str(path.resolve()), stat.st_size, stat.st_mtime_ns, compressed) if stat else None
    return {"panel_version": version, "source_repo": recorded.get("source_repo"),
            "source_revision": recorded.get("source_revision"),
            "revision_status": recorded.get("revision_status", "unknown"),
            "value_schema": recorded.get("value_schema")}


def engine_source() -> dict:
    from . import bundle_db, config, personas

    source = personas.source()
    path = bundle_db.bundle_path() if source == "bundle" else config.persona_db()
    return {"persona_source": source, **artifact(path, compressed=source == "bundle")}


def input_hash(value) -> str:
    """Stable identity of a JSON input; no Python repr or unordered sets."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def model_settings() -> dict:
    from . import config, jev, llm

    # Store endpoint identities as hashes, so URL credentials and query keys cannot leak.
    return {"provider": llm.provider(), "models": [llm.model_label(config.REACT_MODEL), llm.model_label(config.SYNTH_MODEL)],
            "jev_provider": jev.provider(), "jev_model": jev.model(),
            "endpoints": input_hash([os.environ.get("PP_LLM_BASE_URL", ""), jev.api_url()]),
            "generation": {k: os.environ.get(k) for k in ("PP_LLM_TEMPERATURE", "PP_EXAONE_THINKING",
                                                          "PP_EXAONE_MAX_TOKENS")}}


def code_version() -> str:
    """Hash executable engine sources, including prompts and evaluation rules, even without git."""
    root = Path(__file__).parent.parent
    return input_hash({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for folder in ("pp", "ppservice/survey") for p in sorted((root / folder).glob("*.py"))})


def execution_inputs(policy, source, sampling, limits, *, models=None) -> dict:
    from . import prompts
    return {"schema": 1, "policy": input_hash(policy), "source": source, "sampling": sampling,
            "models": model_settings() if models is None else models, "code": code_version(), "limits": limits,
            "prompts": input_hash({k: v for k, v in vars(prompts).items() if k.isupper() and isinstance(v, str)})}


class InputMismatch(RuntimeError):
    pass
